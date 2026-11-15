"""«Починка блока: смена протокола» — move an inbound of a Remnawave config profile to another transport.

When a transport gets blocked (the owner's case: gRPC stopped working, XHTTP did not), the inbound is switched in
four visible stages, each with its own log and time:

1. read the current transport of the inbound;
2. change the transport of the inbound in the profile;
3. update the hosts bound to that inbound (their path / service name);
4. check that the nodes reconnected — a table per node, repeated until all are on-line or the owner stops.

Only the panel API is used; the panel itself hands the new profile to the nodes. The old inbound and the old host
values are saved before the first change. If the panel refuses a change in stage 2 or 3, they are put back at once
and the result says what was restored. If only a part of the nodes came back, the result is «частично», never
«успешно», and the owner can return the previous transport with one button.
"""
from __future__ import annotations

import copy
import json
import re
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import decrypt_secret, encrypt_secret, require_permission

router = APIRouter(prefix="/api/admin/rw/protocol-switch", tags=["remnawave-protocol-switch"])

JOBS_KEY = "rw.protocol_switch"
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
TRANSPORTS = {"tcp": "TCP (RAW)", "xhttp": "XHTTP", "grpc": "gRPC"}
ALIASES = {"raw": "tcp", "splithttp": "xhttp", "gun": "grpc"}
SETTINGS_KEYS = ("tcpSettings", "rawSettings", "grpcSettings", "xhttpSettings", "splithttpSettings", "wsSettings",
                 "httpupgradeSettings", "kcpSettings", "httpSettings")
STAGES = (("read", "Чтение текущего транспорта"), ("switch", "Смена протокола inbound"),
          ("hosts", "Обновление hosts"), ("reconnect", "Проверка реконнекта нод"))
KEEP = 10
BUSY_FOR = timedelta(minutes=3)


class SwitchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_uuid: str
    inbound_tag: str
    target: str

    @field_validator("profile_uuid")
    @classmethod
    def uuid_ok(cls, value: str) -> str:
        if not UUID.match(value):
            raise ValueError("Неверный UUID профиля")
        return value

    @field_validator("inbound_tag")
    @classmethod
    def tag_ok(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.:\- ]{1,64}", value):
            raise ValueError("Неверный тег inbound")
        return value

    @field_validator("target")
    @classmethod
    def target_ok(cls, value: str) -> str:
        if value not in TRANSPORTS:
            raise ValueError("Транспорт: tcp, xhttp или grpc")
        return value


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def network_of(inbound: dict) -> str:
    name = str((inbound.get("streamSettings") or {}).get("network") or "tcp").lower()
    return ALIASES.get(name, name)


def switched(inbound: dict, target: str) -> dict:
    """The same inbound on another transport: port, protocol, security (REALITY keys, certificates) are untouched."""
    if target not in TRANSPORTS:
        raise ValueError(target)
    out = copy.deepcopy(inbound)
    stream = {k: v for k, v in (out.get("streamSettings") or {}).items() if k not in SETTINGS_KEYS}
    stream["network"] = target
    if target == "xhttp":
        stream["xhttpSettings"] = {"path": "/xhttp", "mode": "auto"}
    elif target == "grpc":
        stream["grpcSettings"] = {"serviceName": "grpc", "multiMode": True}
    out["streamSettings"] = stream
    return out


def host_path(target: str) -> str | None:
    """What a host of the inbound must carry for the transport (None: the transport has no path)."""
    return {"xhttp": "/xhttp", "grpc": "grpc"}.get(target)


def _list(value, key: str) -> list[dict]:
    if isinstance(value, dict):
        value = value.get(key, value.get("response", value.get("items", [])))
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


async def _panel(method: str, path: str, **kw):
    from .rw_extensions import _panel as call
    return await call(method, path, **kw)


async def _jobs(db: AsyncSession) -> list[dict]:
    from .node_health import _load
    return list((await _load(db, JOBS_KEY, {"jobs": []})).get("jobs") or [])


async def _save_job(db: AsyncSession, job: dict) -> None:
    from .node_health import _save
    jobs = await _jobs(db)  # newest first; an updated run keeps its place
    jobs = [job if j.get("id") == job["id"] else j for j in jobs] if any(j.get("id") == job["id"] for j in jobs) else [job] + jobs
    await _save(db, JOBS_KEY, {"jobs": jobs[:KEEP]})
    await db.commit()


def _public(job: dict) -> dict:
    """A job for the page: everything except the saved (encrypted) inbound."""
    return {k: v for k, v in job.items() if k != "saved"}


def _inbound_uuid(profile: dict, tag: str) -> str | None:
    return next((i.get("uuid") for i in profile.get("inbounds") or [] if isinstance(i, dict) and i.get("tag") == tag), None)


def _serving(nodes: list[dict], inbound_uuid: str | None) -> list[dict]:
    out = []
    for node in nodes:
        active = (node.get("configProfile") or {}).get("activeInbounds") or node.get("activeInbounds") or []
        if inbound_uuid and inbound_uuid in {a.get("uuid") if isinstance(a, dict) else a for a in active}:
            out.append(node)
    return out


def matrix(nodes: list[dict], before: dict[str, bool], transport: str) -> list[dict]:
    """One row per node of the inbound: what the panel says right now, and whether the node was on-line before."""
    checked = now()
    rows = []
    for n, node in enumerate(sorted(nodes, key=lambda x: str(x.get("name") or "")), 1):
        disabled = bool(node.get("isDisabled"))
        online = bool(node.get("isConnected")) and not disabled
        reason = None
        if disabled:
            reason = "Нода выключена в панели"
        elif not online:
            reason = str(node.get("lastStatusMessage") or "Нода не подключилась к панели")[:300]
            if before.get(node.get("uuid")) is False:
                reason += " (не была на связи и до смены)"
        rows.append({"n": n, "uuid": node.get("uuid"), "country": node.get("countryCode"), "name": node.get("name"), "online": online,
                     "disabled": disabled, "was_online": before.get(node.get("uuid")), "transport": transport, "error": reason,
                     "checked_at": checked})
    return rows


def _verdict(rows: list[dict]) -> tuple[str, str]:
    expected = [r for r in rows if not r["disabled"]]
    online = [r for r in expected if r["online"]]
    if not expected:
        return "partial", "У этого inbound нет включённых нод: проверять реконнект не на чем."
    if len(online) == len(expected):
        return "succeeded", f"Все ноды на связи: {len(online)} из {len(expected)}."
    return "partial", f"На связи {len(online)} из {len(expected)} нод. Смена не считается успешной, пока не подключились все."


def _stage(job: dict, key: str) -> dict:
    return next(s for s in job["stages"] if s["key"] == key)


def _begin(job: dict, key: str) -> dict:
    stage = _stage(job, key)
    stage.update({"status": "running", "started_at": now()})
    return stage


def _end(stage: dict, status: str, *lines: str) -> None:
    stage["log"] += [f"{now()} {line}" for line in lines]
    stage.update({"status": status, "finished_at": now()})


async def _overview() -> dict:
    profiles = _list(await _panel("GET", "/api/config-profiles"), "configProfiles")
    hosts = _list(await _panel("GET", "/api/hosts"), "hosts")
    nodes = _list(await _panel("GET", "/api/nodes"), "nodes")
    out = []
    for profile in profiles:
        full = profile if isinstance(profile.get("config"), dict) else await _panel("GET", f"/api/config-profiles/{profile['uuid']}")
        rows = []
        for inbound in (full.get("config") or {}).get("inbounds") or []:
            if not isinstance(inbound, dict) or not inbound.get("tag"):
                continue
            uuid = _inbound_uuid(full, inbound["tag"])
            serving = _serving(nodes, uuid)
            rows.append({
                "tag": inbound["tag"], "protocol": inbound.get("protocol"), "port": inbound.get("port"), "network": network_of(inbound),
                "security": (inbound.get("streamSettings") or {}).get("security") or "none",
                "hosts": len([h for h in hosts if (h.get("inbound") or {}).get("configProfileInboundUuid") == uuid]) if uuid else 0,
                "nodes": len(serving), "nodes_online": len([n for n in serving if n.get("isConnected") and not n.get("isDisabled")]),
                # Only VLESS / Trojan stream inbounds are switched here; Hysteria, Shadowsocks and the like have their own transport.
                "switchable": inbound.get("protocol") in ("vless", "trojan") and network_of(inbound) in TRANSPORTS,
            })
        out.append({"uuid": profile.get("uuid"), "name": profile.get("name"), "inbounds": rows})
    return {"profiles": out, "transports": TRANSPORTS}


@router.get("")
async def overview(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    return {**await _overview(), "jobs": [_public(j) for j in await _jobs(db)]}


@router.get("/meta")
async def meta(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    """Answers without the panel: the transports and the saved runs."""
    return {"transports": TRANSPORTS, "stages": [title for _, title in STAGES], "jobs": [_public(j) for j in await _jobs(db)]}


async def _restore(job: dict, profile_changed: bool, hosts_done: list[str]) -> list[str]:
    """Put the saved inbound and host values back; returns what was restored (for the report)."""
    saved, restored = json.loads(decrypt_secret(job["saved"])), []
    for host in saved["hosts"]:
        if host["uuid"] in hosts_done:
            await _panel("PATCH", "/api/hosts", json={"uuid": host["uuid"], "path": host["path"]})
            restored.append(f"host «{host['remark']}»: путь возвращён")
    if profile_changed:
        profile = await _panel("GET", f"/api/config-profiles/{job['profile_uuid']}")
        config = copy.deepcopy(profile.get("config") or {})
        config["inbounds"] = [saved["inbound"] if isinstance(i, dict) and i.get("tag") == job["inbound_tag"] else i for i in config.get("inbounds") or []]
        await _panel("PATCH", "/api/config-profiles", json={"uuid": job["profile_uuid"], "config": config})
        restored.append(f"inbound {job['inbound_tag']}: транспорт {TRANSPORTS[job['from']]} возвращён")
    return restored


@router.post("")
async def start(payload: SwitchIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """Stages 1–3 in one request (seconds); stage 4 is «/check», called by the page until the nodes are back."""
    from .main import audit
    running = [j for j in await _jobs(db) if j.get("status") == "switching" and datetime.fromisoformat(j["created_at"]) > datetime.now(UTC) - BUSY_FOR]
    if running:
        raise HTTPException(409, "Смена протокола уже выполняется. Дождитесь её окончания.")
    job = {"id": secrets.token_hex(8), "created_at": now(), "actor": admin.email, "profile_uuid": payload.profile_uuid, "profile_name": "",
           "inbound_tag": payload.inbound_tag, "from": "", "to": payload.target, "status": "switching", "summary": "", "hosts_updated": 0,
           "restored": [], "nodes": [], "checks": 0,
           "stages": [{"key": key, "title": title, "status": "pending", "started_at": None, "finished_at": None, "log": []} for key, title in STAGES]}
    await _save_job(db, job)

    # ---- 1. read
    stage = _begin(job, "read")
    try:
        profile = await _panel("GET", f"/api/config-profiles/{payload.profile_uuid}")
        inbound = next((i for i in (profile.get("config") or {}).get("inbounds") or [] if isinstance(i, dict) and i.get("tag") == payload.inbound_tag), None)
        if inbound is None:
            raise HTTPException(404, f"В профиле нет inbound {payload.inbound_tag}")
        if inbound.get("protocol") not in ("vless", "trojan") or network_of(inbound) not in TRANSPORTS:
            raise HTTPException(422, f"Inbound {payload.inbound_tag} ({inbound.get('protocol')}, {network_of(inbound)}) здесь не переключается")
        inbound_uuid = _inbound_uuid(profile, payload.inbound_tag)
        hosts = [h for h in _list(await _panel("GET", "/api/hosts"), "hosts") if inbound_uuid and (h.get("inbound") or {}).get("configProfileInboundUuid") == inbound_uuid]
        nodes = _serving(_list(await _panel("GET", "/api/nodes"), "nodes"), inbound_uuid)
    except HTTPException as error:
        _end(stage, "failed", f"Ошибка: {error.detail}")
        job.update({"status": "failed", "summary": f"Не удалось прочитать профиль: {error.detail}. В панели ничего не изменено."})
        await _save_job(db, job)
        return _public(job)
    job.update({"profile_name": profile.get("name") or "", "from": network_of(inbound), "inbound_uuid": inbound_uuid,
                "before": {n.get("uuid"): bool(n.get("isConnected")) and not n.get("isDisabled") for n in nodes},
                # Encrypted at rest: the inbound carries the REALITY private key.
                "saved": encrypt_secret(json.dumps({"inbound": inbound, "hosts": [{"uuid": h["uuid"], "remark": h.get("remark") or "", "path": h.get("path")} for h in hosts]}))})
    online_before = len([v for v in job["before"].values() if v])
    _end(stage, "done", f"Профиль «{job['profile_name']}», inbound {payload.inbound_tag}: {inbound.get('protocol')} · {TRANSPORTS[job['from']]} · "
                        f"{(inbound.get('streamSettings') or {}).get('security') or 'none'}, порт {inbound.get('port')}.",
         f"Hosts этого inbound: {len(hosts)}. Нод: {len(nodes)}, на связи {online_before}.", "Прежний inbound и пути hosts сохранены для отката.")
    if job["from"] == payload.target:
        for key in ("switch", "hosts", "reconnect"):
            _end(_begin(job, key), "skipped", "Не требуется.")
        job.update({"status": "unchanged", "summary": f"Inbound уже работает на {TRANSPORTS[payload.target]}. В панели ничего не изменено."})
        await _save_job(db, job)
        return _public(job)

    # ---- 2. switch, 3. hosts — with the saved state put back if the panel refuses
    profile_changed, hosts_done = False, []
    stage = _begin(job, "switch")
    try:
        config = copy.deepcopy(profile.get("config") or {})
        config["inbounds"] = [switched(i, payload.target) if isinstance(i, dict) and i.get("tag") == payload.inbound_tag else i for i in config.get("inbounds") or []]
        await _panel("PATCH", "/api/config-profiles", json={"uuid": payload.profile_uuid, "config": config})
        profile_changed = True
        _end(stage, "done", f"Транспорт: {TRANSPORTS[job['from']]} → {TRANSPORTS[payload.target]}. Порт, протокол и защита не менялись.",
             "Панель сама передаёт новый профиль нодам.")
        stage = _begin(job, "hosts")
        path = host_path(payload.target)
        for host in hosts:
            if host.get("path") != path:
                await _panel("PATCH", "/api/hosts", json={"uuid": host["uuid"], "path": path})
                hosts_done.append(host["uuid"])
                stage["log"].append(f"{now()} host «{host.get('remark') or host['uuid']}»: путь {host.get('path')!r} → {path!r}")
        job["hosts_updated"] = len(hosts_done)
        _end(stage, "done", f"Обновлено hosts: {len(hosts_done)} из {len(hosts)}." if hosts else "У inbound нет hosts: обновлять нечего.")
    except HTTPException as error:
        _end(stage, "failed", f"Ошибка панели: {error.detail}")
        try:
            job["restored"] = await _restore(job, profile_changed, hosts_done)
            job.update({"status": "failed", "summary": f"Панель отклонила изменение: {error.detail}. Прежнее состояние восстановлено."
                                                       if job["restored"] else f"Панель отклонила изменение: {error.detail}. В панели ничего не изменено."})
        except HTTPException as second:
            job.update({"status": "failed_inconsistent",
                        "summary": f"Панель отклонила изменение ({error.detail}), и вернуть прежнее состояние не удалось ({second.detail}). "
                                   "Inbound и hosts могут не совпадать: нажмите «Вернуть прежний транспорт», когда панель ответит."})
        await audit(db, "rw.protocol_switch.failed", admin.email, payload.profile_uuid, {"inbound": payload.inbound_tag, "to": payload.target, "status": job["status"]})
        await _save_job(db, job)
        return _public(job)

    job["status"] = "checking"
    _begin(job, "reconnect")
    await audit(db, "rw.protocol_switch.applied", admin.email, payload.profile_uuid,
                {"inbound": payload.inbound_tag, "from": job["from"], "to": payload.target, "hosts": len(hosts_done)})
    await _save_job(db, job)
    return _public(job)


async def _job(db: AsyncSession, job_id: str) -> dict:
    job = next((j for j in await _jobs(db) if j.get("id") == job_id), None)
    if not job:
        raise HTTPException(404, "Запуск не найден")
    return job


@router.post("/{job_id}/check")
async def check(job_id: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """One look at the nodes. The page repeats it; the owner can also press «Проверить ещё раз» later."""
    job = await _job(db, job_id)
    if job["status"] not in ("checking", "partial", "succeeded"):
        raise HTTPException(409, "У этого запуска нет этапа проверки реконнекта")
    stage = _stage(job, "reconnect")
    nodes = _serving(_list(await _panel("GET", "/api/nodes"), "nodes"), job.get("inbound_uuid"))
    job["nodes"] = matrix(nodes, job.get("before") or {}, job["to"])
    job["checks"] = int(job.get("checks") or 0) + 1
    status, summary = _verdict(job["nodes"])
    stage["log"].append(f"{now()} Проверка {job['checks']}: {summary}")
    stage["log"] = stage["log"][-40:]
    stage.update({"status": "done" if status == "succeeded" else "partial", "finished_at": now()})
    job.update({"status": status, "summary": summary})
    await _save_job(db, job)
    return _public(job)


@router.post("/{job_id}/rollback")
async def rollback(job_id: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """«Вернуть прежний транспорт»: the saved inbound and host paths go back; the nodes are then checked again."""
    from .main import audit
    job = await _job(db, job_id)
    if job["status"] not in ("checking", "partial", "succeeded", "failed_inconsistent"):
        raise HTTPException(409, "Этот запуск нечего откатывать")
    jobs = await _jobs(db)  # newest first
    later = jobs[:next(i for i, j in enumerate(jobs) if j["id"] == job["id"])]
    newer = next((j for j in later if j.get("profile_uuid") == job["profile_uuid"] and j.get("inbound_tag") == job["inbound_tag"]
                  and j.get("status") in ("checking", "partial", "succeeded", "failed_inconsistent")), None)
    if newer:
        raise HTTPException(409, "После этого запуска inbound меняли ещё раз. Откатите сначала более поздний запуск.")
    job["restored"] = await _restore(job, True, [h["uuid"] for h in json.loads(decrypt_secret(job["saved"]))["hosts"]])
    job.update({"status": "rolled_back", "summary": f"Возвращён прежний транспорт {TRANSPORTS[job['from']]}. " + "; ".join(job["restored"]) + "."})
    await audit(db, "rw.protocol_switch.rolled_back", admin.email, job["profile_uuid"], {"inbound": job["inbound_tag"], "to": job["from"]})
    await _save_job(db, job)
    return _public(job)
