"""Pool of ready WireGuard / AmneziaWG configs and the customer's connection keys.

**Pool.** The owner uploads ready ``.conf`` files (one or many in one text; each starts with ``[Interface]``;
AmneziaWG is recognised by its ``Jc``/``Jmin``/``S1``… fields). A customer with an active subscription takes one in
the cabinet, Mini App or apps («Ключи подключения → WireGuard»): the config is fixed to the subscription and the
device (one WireGuard key cannot be shared between devices), at most the subscription's device limit. Configs are
stored encrypted with APP_SECRET. Optionally only for chosen Internal Squads. Off by default.

**Keys.** ``GET /api/me/subscription/keys`` lists every connection key of the customer's subscription — the panel's
hosts (``GET /api/subscriptions/by-short-uuid/{short}``), the proxy's extra keys for the squad and the servers of the
second subscription — one row each, for copy and QR in the cabinet. The panel's subscription page shows them only
with the device limit off; this list does not depend on it.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import decrypt_secret, encrypt_secret, require_permission

router = APIRouter()
CONFIG_KEY = "wg_pool.config"
DEFAULT = {"enabled": False, "squads": [], "name_prefix": "Корги Люси"}
AWG_FIELDS = re.compile(r"^\s*(Jc|Jmin|Jmax|S1|S2|S3|S4|H1|H2|H3|H4|I1)\s*=", re.M | re.I)


async def _config(db: AsyncSession) -> dict:
    from .node_health import _load
    return await _load(db, CONFIG_KEY, DEFAULT)


def split_configs(text: str) -> list[str]:
    parts = re.split(r"(?=^\s*\[Interface\]\s*$)", text.replace("\r\n", "\n"), flags=re.M)
    return [p.strip() + "\n" for p in parts if "[Interface]" in p and "[Peer]" in p and "PrivateKey" in p]


def kind_of(config: str) -> str:
    return "awg" if AWG_FIELDS.search(config) else "wg"


async def active_subscription(db: AsyncSession, user_id: int):
    from .models import Subscription
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user_id, Subscription.expires_at > datetime.utcnow(),
                                                      Subscription.lifecycle_status.in_(("active", "grace")))
                          .order_by(Subscription.is_primary.desc(), Subscription.id.desc()).limit(1))
    if not sub:
        raise HTTPException(402, "Нужна активная подписка")
    return sub


# ---------------------------------------------------------------- customer


@router.get("/api/me/wg-config")
async def my_wg(request: Request, hwid: str = "", db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    from .models import WgConfig
    user = await user_from_token(request, db)
    cfg = await _config(db)
    if not cfg.get("enabled"):
        raise HTTPException(404, "WireGuard не включён")
    sub = await active_subscription(db, user.id)
    if cfg.get("squads") and sub.remnawave_profile_id_snapshot not in cfg["squads"]:
        raise HTTPException(403, "WireGuard не входит в ваш тариф")
    device = (hwid or request.headers.get("x-hwid") or "default")[:128]
    row = await db.scalar(select(WgConfig).where(WgConfig.subscription_id == sub.id, WgConfig.hwid == device))
    if row is None:
        used = await db.scalar(select(func.count()).select_from(WgConfig).where(WgConfig.subscription_id == sub.id)) or 0
        if sub.device_limit_snapshot and used >= int(sub.device_limit_snapshot):
            raise HTTPException(409, "Конфиги выданы на все устройства тарифа — удалите ненужный в кабинете")
        row = await db.scalar(select(WgConfig).where(WgConfig.subscription_id.is_(None)).order_by(WgConfig.id).limit(1).with_for_update())
        if row is None:
            raise HTTPException(503, "Свободные конфиги закончились — мы уже знаем, напишите в поддержку")
        row.subscription_id, row.hwid, row.assigned_at = sub.id, device, datetime.utcnow()
        await db.commit()
    return {"name": f"{cfg.get('name_prefix') or 'VPN'} {row.kind.upper()}", "kind": row.kind, "config": decrypt_secret(row.config),
            "filename": f"corgi-{row.kind}-{row.id}.conf"}


@router.get("/api/me/wg-configs")
async def my_wg_list(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    from .models import Subscription, WgConfig
    user = await user_from_token(request, db)
    subs = [s.id for s in (await db.execute(select(Subscription).where(Subscription.user_id == user.id))).scalars()]
    rows = (await db.execute(select(WgConfig).where(WgConfig.subscription_id.in_(subs)))).scalars().all() if subs else []
    return {"enabled": bool((await _config(db)).get("enabled")),
            "configs": [{"id": r.id, "kind": r.kind, "device": r.hwid, "assigned_at": r.assigned_at.isoformat(timespec="minutes") if r.assigned_at else None}
                        for r in rows]}


@router.delete("/api/me/wg-configs/{config_id}")
async def my_wg_release(config_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """The customer frees a config of an old device; the key goes back only after the owner re-issues it on the server."""
    from .main import user_from_token
    from .models import Subscription, WgConfig
    user = await user_from_token(request, db)
    row = await db.get(WgConfig, config_id)
    sub = await db.get(Subscription, row.subscription_id) if row and row.subscription_id else None
    if not row or not sub or sub.user_id != user.id:
        raise HTTPException(404)
    await db.delete(row)  # a used key is never handed to another customer
    await db.commit()
    return {"ok": True}


def link_name(link: str) -> str:
    return unquote(link.split("#", 1)[1])[:80] if "#" in link else link.split("://", 1)[0].upper()


def qr_data_url(text: str) -> str:
    import base64
    import io

    import qrcode
    buf = io.BytesIO()
    qrcode.make(text).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@router.get("/api/me/subscription/keys/{index}/qr")
async def my_key_qr(index: int, request: Request, db: AsyncSession = Depends(get_db)):
    """QR of one key as a data URL (works in the Mini App, where images cannot carry the Telegram auth header)."""
    keys = (await my_keys(request, db))["keys"]
    if not 0 <= index < len(keys):
        raise HTTPException(404)
    return {"png": qr_data_url(keys[index]["link"])}


@router.get("/api/me/wg-config/qr")
async def my_wg_qr(request: Request, hwid: str = "", db: AsyncSession = Depends(get_db)):
    data = await my_wg(request, hwid, db)
    return {"png": qr_data_url(data["config"]), "name": data["name"]}


@router.get("/api/me/subscription/keys")
async def my_keys(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    from .remnawave import RemnawaveClient
    from .sub_proxy import config as proxy_config, short_uuid_of
    user = await user_from_token(request, db)
    sub = await active_subscription(db, user.id)
    short = short_uuid_of(sub.subscription_url)
    if not short:
        raise HTTPException(404, "Ссылка подписки ещё не готова")
    info = await RemnawaveClient()._request("GET", f"/api/subscriptions/by-short-uuid/{short}")
    links = [x for x in (info or {}).get("links") or [] if isinstance(x, str) and "://" in x and "@0.0.0.0:1" not in x]
    cfg = await proxy_config(db)
    if cfg.get("enabled"):
        links += [x for e in cfg.get("extras") or [] if not e.get("squad") or e.get("squad") == sub.remnawave_profile_id_snapshot
                  for x in e.get("links") or [] if "://" in x]
    seen, keys = set(), []
    for link in links:
        if link not in seen:
            seen.add(link)
            keys.append({"name": link_name(link), "link": link, "protocol": link.split("://", 1)[0]})
    return {"keys": keys, "wireguard": bool((await _config(db)).get("enabled"))}


# ---------------------------------------------------------------- admin


class PoolIn(BaseModel):
    enabled: bool = False
    squads: list[str] = Field(default_factory=list, max_length=50)
    name_prefix: str = Field("Корги Люси", max_length=40)


class UploadIn(BaseModel):
    text: str = Field(..., min_length=20, max_length=2_000_000)


@router.get("/api/admin/wg-pool")
async def get_pool(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    from .models import WgConfig
    rows = (await db.execute(select(WgConfig.kind, WgConfig.subscription_id.is_(None), func.count()).group_by(WgConfig.kind, WgConfig.subscription_id.is_(None)))).all()
    stats: dict = {}
    for kind, free, n in rows:
        s = stats.setdefault(kind, {"free": 0, "assigned": 0})
        s["free" if free else "assigned"] += int(n)
    return {"config": await _config(db), "stats": stats}


@router.put("/api/admin/wg-pool")
async def put_pool(payload: PoolIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    from .node_health import _save
    await _save(db, CONFIG_KEY, payload.model_dump())
    await db.commit()
    return {"ok": True}


@router.post("/api/admin/wg-pool/upload")
async def upload(payload: UploadIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    from .models import WgConfig
    configs = split_configs(payload.text)
    if not configs:
        raise HTTPException(422, "Не нашёл ни одного конфига: каждый начинается с [Interface] и содержит [Peer] и PrivateKey")
    for i, config in enumerate(configs):
        db.add(WgConfig(kind=kind_of(config), name=f"conf-{i + 1}", config=encrypt_secret(config)))
    await db.commit()
    return {"added": len(configs), "awg": sum(1 for c in configs if kind_of(c) == "awg")}


@router.delete("/api/admin/wg-pool/free")
async def drop_free(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    from sqlalchemy import delete
    from .models import WgConfig
    result = await db.execute(delete(WgConfig).where(WgConfig.subscription_id.is_(None)))
    await db.commit()
    return {"deleted": int(result.rowcount or 0)}
