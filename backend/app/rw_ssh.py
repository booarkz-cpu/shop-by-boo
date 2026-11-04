"""Смена SSH-ключа сервера мастера Remnawave (v28.75.0, этап 16; docs/ru/new/SECRETS_MANAGEMENT.md).

``POST /api/admin/rw/servers/{id}/rotate-key`` (право ``provision_nodes`` и подтверждение опасного действия):

1. магазин создаёт новый ключ Ed25519 — свой для каждого сервера;
2. по прежнему доступу (ключ или пароль) дописывает открытую часть в ``authorized_keys`` пользователя SSH с
   пометкой ``corgi-shop-<сервер>-<время>-<случайный хвост>``;
3. входит новым ключом и проверяет ``sudo``; не вошёл — новая строка убирается, всё остаётся как было;
4. убирает строку прежнего ключа магазина (только с его пометкой: ключи владельца не трогаются);
5. хранит новый закрытый ключ зашифрованным; пароль, если входили по паролю, больше не хранится.

Скрипты — закрытый список этого модуля; значения передаются аргументами и проверяются на сервере ещё раз."""
from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from . import rw_jobs, rw_plan, rw_steps
from .db import get_db
from .security import encrypt_secret, require_stepup

router = APIRouter(prefix="/api/admin/rw")
KEY_MAX_AGE_DAYS = 180

_CHECK = r"""u="$1"; marker="$2"
case "$u" in ""|*[!A-Za-z0-9_.-]*) echo "bad user" >&2; exit 2 ;; esac
case "$marker" in corgi-shop-[0-9]*-[0-9]*Z-[0-9a-f]*) ;; *) echo "bad marker" >&2; exit 2 ;; esac
case "$marker" in *[!A-Za-z0-9-]*) echo "bad marker" >&2; exit 2 ;; esac
h="$(getent passwd "$u" | cut -d: -f6)"; [ -n "$h" ] || { echo "no user" >&2; exit 3; }
g="$(id -gn "$u")"
f="$h/.ssh/authorized_keys"
"""
ADD_KEY = "set -eu\n" + _CHECK + r"""key="$(head -c 700)"
case "$key" in "ssh-ed25519 "*" $marker") ;; *) echo "bad key" >&2; exit 2 ;; esac
case "$key" in *"
"*) echo "bad key" >&2; exit 2 ;; esac
install -d -m 700 -o "$u" -g "$g" "$h/.ssh"
touch "$f"; chown "$u:$g" "$f"; chmod 600 "$f"
grep -qxF -- "$key" "$f" || printf '%s\n' "$key" >> "$f"
echo added
"""
REMOVE_KEY = "set -eu\n" + _CHECK + r"""[ -f "$f" ] || { echo none; exit 0; }
grep -v -- " $marker\$" "$f" > "$f.rw-new" || true
cat "$f.rw-new" > "$f"; rm -f "$f.rw-new"
echo removed
"""
VERIFY = r"""echo "rw-key-ok $(id -un)"
"""


def new_key(server_id: int, now: datetime | None = None) -> tuple[str, str, str, str]:
    """(private key in OpenSSH format, authorized_keys line, SHA256 fingerprint, marker)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    blob = base64.b64decode(public.split()[1])
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    # A random tail: two rotations in one second never share a marker (the second would remove the first's line).
    marker = f"corgi-shop-{server_id}-{(now or datetime.utcnow()):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
    return private, f"{public} {marker}", fingerprint, marker


def _ctx(server: dict) -> rw_steps.Context:
    return rw_steps.Context(plan=rw_plan.PlanIn(mode="node", node_server_ids=[server["id"]], tls="internal"),
                            servers={server["id"]: server}, secrets={}, state={}, connect=rw_jobs.CONNECT)


async def _run(server: dict, script: str, *args: str, stdin: bytes | None = None):
    try:
        return await rw_steps._run(_ctx(server), server["id"], script, *args, stdin=stdin, timeout=60)
    except rw_steps.StepError as exc:
        raise HTTPException(502, f"SSH: {exc}") from exc


def key_state(row) -> dict:
    age = (datetime.utcnow() - row.ssh_key_rotated_at).days if row.ssh_key_rotated_at else None
    return {"managed": bool(row.ssh_key_marker), "fingerprint": row.ssh_key_fingerprint,
            "rotated_at": row.ssh_key_rotated_at.isoformat() + "Z" if row.ssh_key_rotated_at else None, "age_days": age,
            "rotation_due": row.ssh_key_marker is None or (age is not None and age >= KEY_MAX_AGE_DAYS)}


@router.post("/servers/{server_id}/rotate-key")
async def rotate_key(server_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_stepup("provision_nodes"))):
    from .main import audit
    from .rw_api import _busy, _server, server_out
    row = await _server(db, server_id, lock=True)
    if await _busy(db, [row.id]):
        raise HTTPException(409, "На сервере идёт установка: смените ключ после неё")
    old = rw_jobs.server_dict(row)
    private, line, fingerprint, marker = new_key(row.id)
    added = await _run(old, ADD_KEY, row.ssh_user, marker, stdin=line.encode())
    if added.code != 0:
        raise HTTPException(502, "Сервер не принял новый ключ: " + (added.err or added.out).strip()[:300])
    fresh = {**old, "key": private, "password": None}
    checked = await _run(fresh, VERIFY)
    if checked.code != 0 or "rw-key-ok" not in checked.out:
        await _run(old, REMOVE_KEY, row.ssh_user, marker)
        raise HTTPException(502, "Вход новым ключом не удался (нужен sudo без пароля): ключ убран, доступ прежний")
    removed = False
    if row.ssh_key_marker:
        gone = await _run(fresh, REMOVE_KEY, row.ssh_user, row.ssh_key_marker)
        removed = gone.code == 0
    previous = row.auth_method
    row.ssh_secret = encrypt_secret(private)
    row.auth_method = "key"
    row.ssh_key_fingerprint, row.ssh_key_marker, row.ssh_key_rotated_at = fingerprint, marker, datetime.utcnow()
    row.updated_at = datetime.utcnow()
    await audit(db, "rw.server.key_rotated", admin.email, str(row.id),
                {"fingerprint": fingerprint, "previous": previous, "previous_key_removed": removed})
    await db.commit()
    return {**server_out(row), "rotation": {"previous": previous, "previous_key_removed": removed,
                                            "note": ("Прежний пароль больше не хранится в магазине. Отключите вход по паролю на сервере, "
                                                     "если он не нужен (PasswordAuthentication no)") if previous == "password" else None}}
