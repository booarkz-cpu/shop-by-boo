from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .config import settings
from .models import AppSetting, AutomationRule, Campaign, Payment, Subscription, User, UserDevice
from .remnawave import RemnawaveClient
from .security import require_permission

router = APIRouter()

ROUTING_DEFAULTS = {
    "enabled": True,
    "strategy": "latency_load",
    "max_load_percent": 85,
    "preferred_countries": [],
    "fallback_enabled": True,
    "health_window_seconds": 300,
}


async def _json_setting(db: AsyncSession, key: str, default: dict) -> dict:
    row = await db.get(AppSetting, key)
    if not row or not row.value:
        return dict(default)
    try:
        value = json.loads(row.value)
        return {**default, **value} if isinstance(value, dict) else dict(default)
    except Exception:
        return dict(default)


class RoutingIn(BaseModel):
    enabled: bool = True
    strategy: str = Field(default="latency_load", pattern="^(latency_load|round_robin|country_first)$")
    max_load_percent: int = Field(default=85, ge=10, le=100)
    preferred_countries: list[str] = Field(default_factory=list, max_length=30)
    fallback_enabled: bool = True
    health_window_seconds: int = Field(default=300, ge=30, le=3600)


@router.get("/api/admin/v3/control-center")
async def control_center(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    now = datetime.utcnow()
    active = int(await db.scalar(select(func.count()).select_from(Subscription).where(Subscription.expires_at > now)) or 0)
    users = int(await db.scalar(select(func.count()).select_from(User)) or 0)
    devices = int(await db.scalar(select(func.count()).select_from(UserDevice).where(UserDevice.status == "active")) or 0)
    pending_payments = int(await db.scalar(select(func.count()).select_from(Payment).where(Payment.status.in_(["pending", "processing", "creation_unknown"]))) or 0)
    failed_payments = int(await db.scalar(select(func.count()).select_from(Payment).where(Payment.status == "failed")) or 0)
    automation = int(await db.scalar(select(func.count()).select_from(AutomationRule).where(AutomationRule.enabled.is_(True))) or 0)
    campaigns = int(await db.scalar(select(func.count()).select_from(Campaign).where(Campaign.status.in_(["scheduled", "running"]))) or 0)
    revenue = await db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status.in_(["paid", "fulfilled"])))
    recent = (await db.execute(select(Payment).order_by(desc(Payment.id)).limit(8))).scalars().all()
    return {
        "kpis": {
            "users": users, "active_subscriptions": active, "devices": devices,
            "pending_payments": pending_payments, "failed_payments": failed_payments,
            "automation_rules": automation, "campaigns": campaigns,
            "revenue": str(revenue or Decimal("0")),
        },
        "recent_payments": [{"id": p.id, "user_id": p.user_id, "amount": str(p.amount), "currency": p.currency, "status": p.status, "created_at": p.created_at} for p in recent],
        "routing": await _json_setting(db, "smart_routing", ROUTING_DEFAULTS),
        "checked_at": now,
    }


@router.get("/api/admin/v3/devices")
async def admin_devices(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    rows = (await db.execute(select(UserDevice, User).join(User, User.id == UserDevice.user_id).order_by(desc(UserDevice.last_seen_at)).limit(500))).all()
    return [{
        "id": d.id, "user_id": d.user_id, "username": u.username, "email": u.email,
        "name": d.name, "platform": d.platform, "status": d.status,
        "last_ip": d.last_ip, "last_seen_at": d.last_seen_at, "created_at": d.created_at,
    } for d, u in rows]


@router.get("/api/admin/v3/automation")
async def admin_automation(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    rules = (await db.execute(select(AutomationRule).order_by(AutomationRule.priority, AutomationRule.id))).scalars().all()
    campaigns = (await db.execute(select(Campaign).order_by(desc(Campaign.id)).limit(50))).scalars().all()
    return {
        "rules": [{"id": r.id, "name": r.name, "event": r.event, "conditions": r.conditions, "actions": r.actions, "enabled": r.enabled, "priority": r.priority, "run_count": r.run_count, "last_run_at": r.last_run_at} for r in rules],
        "campaigns": [{"id": c.id, "name": c.name, "kind": c.kind, "status": c.status, "audience": c.audience, "content": c.content, "sent_count": c.sent_count, "failed_count": c.failed_count, "starts_at": c.starts_at, "ends_at": c.ends_at} for c in campaigns],
    }


@router.post("/api/admin/v3/automation/{rule_id}/toggle")
async def toggle_automation(rule_id: int, payload: dict, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_users"))):
    rule = await db.get(AutomationRule, rule_id)
    if not rule:
        raise HTTPException(404, "Правило не найдено")
    if payload.get("enabled"):
        from .automation import validate_rule
        rule.conditions, rule.actions = validate_rule(rule.event, rule.conditions or {}, rule.actions or {})
        if rule.actions.get("wallet_bonus") and getattr(admin, "role", "") != "admin":
            raise HTTPException(403, "Правило с бонусом на баланс включает администратор")
    rule.enabled = bool(payload.get("enabled"))
    rule.updated_at = datetime.utcnow()
    from .main import audit
    await audit(db, "automation.rule.toggled", admin.email, str(rule.id), {"enabled": rule.enabled})
    await db.commit()
    return {"ok": True, "enabled": rule.enabled}


@router.get("/api/admin/v3/routing")
async def get_routing(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    return await _json_setting(db, "smart_routing", ROUTING_DEFAULTS)


@router.put("/api/admin/v3/routing")
async def put_routing(payload: RoutingIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_users"))):
    row = await db.get(AppSetting, "smart_routing")
    value = json.dumps(payload.model_dump(), ensure_ascii=False)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key="smart_routing", value=value))
    await db.commit()
    return payload.model_dump()


@router.get("/api/me/routing/recommendation")
async def routing_recommendation(request: Request, db: AsyncSession = Depends(get_db)):
    # Authentication is deliberately resolved through the canonical helper.
    from .main import user_from_token
    user = await user_from_token(request, db)
    config = await _json_setting(db, "smart_routing", ROUTING_DEFAULTS)
    if not config["enabled"]:
        return {"enabled": False, "recommendation": None, "nodes": []}
    try:
        remote = await RemnawaveClient().list_nodes(start=0, size=100)
    except Exception:
        return {"enabled": True, "recommendation": None, "nodes": [], "degraded": True}
    from .tariff_api import _iter_nodes
    raw = _iter_nodes(remote)
    preferred = {str(x).upper() for x in config.get("preferred_countries", [])}
    nodes: list[dict[str, Any]] = []
    for node in raw:
        if not isinstance(node, dict):
            continue
        status = str(node.get("status") or node.get("state") or "unknown").lower()
        country = str(node.get("country") or node.get("countryCode") or "").upper()
        if status in {"offline", "disabled", "down", "unavailable"}:
            continue
        load = node.get("load") or node.get("loadPercent") or node.get("cpu") or 0
        try:
            load_num = float(str(load).replace("%", ""))
        except Exception:
            load_num = 0
        if load_num > config["max_load_percent"]:
            continue
        score = load_num
        if preferred and country not in preferred:
            score += 25
        nodes.append({"id": node.get("uuid") or node.get("id"), "name": node.get("name") or node.get("remark") or "VPN node", "country": country, "load": load_num, "status": status, "score": round(score, 2)})
    nodes.sort(key=lambda x: x["score"])
    return {"enabled": True, "user_id": user.id, "recommendation": nodes[0] if nodes else None, "nodes": nodes[:20], "strategy": config["strategy"]}

# ---------------------------------------------------------------------------
# Support Pro integration
# ---------------------------------------------------------------------------
import base64 as _b64
import hashlib as _hashlib
import hmac as _hmac
import time as _time
import uuid as _uuid


def _support_token(payload: dict) -> str:
    secret = settings.support_pro_sso_secret
    if not secret:
        raise HTTPException(503, "SUPPORT_PRO_SSO_SECRET is not configured")
    raw = _b64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()).decode().rstrip('=')
    sig = _hmac.new(secret.encode(), raw.encode(), _hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


@router.get('/api/admin/support-pro/status')
async def support_pro_status(admin=Depends(require_permission('support.read'))):
    url = settings.support_pro_url.rstrip('/')
    if not url:
        return {"configured": False, "online": False, "url": ""}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=settings.support_pro_timeout_seconds, follow_redirects=False) as client:
            response = await client.get(f"{url}/health")
        return {"configured": True, "online": response.status_code < 500, "status_code": response.status_code, "url": url}
    except Exception as exc:
        return {"configured": True, "online": False, "url": url, "error": str(exc)[:240]}


@router.post('/api/admin/support-pro/sso')
async def support_pro_sso(request: Request, admin=Depends(require_permission('support.read'))):
    url = settings.support_pro_url.rstrip('/')
    if not url or not settings.support_pro_sso_secret:
        raise HTTPException(503, "Support Pro SSO is not configured")
    payload = {
        "sub": str(admin.id),
        "login": admin.email,
        "role": {"admin": "admin", "operator": "operator", "viewer": "viewer"}.get(admin.role, "viewer"),
        "iat": int(_time.time()),
        "exp": int(_time.time()) + 60,
        "jti": str(_uuid.uuid4()),
    }
    token = _support_token(payload)
    return {"url": f"{url}/sso", "method": "POST", "token": token}
