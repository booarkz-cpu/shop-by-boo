"""«Не работает VPN» in the apps: the app checks what it can see, the shop adds what it knows, support gets a diagnosis.

The app sends its own checks (DNS of the API, the API itself, the subscription download, a TCP connection to every
server of the subscription) together with the customer's words. The shop adds the subscription state, the device limit,
the nodes as Remnawave sees them and the last payment, decides the most likely cause and opens a support ticket with
the whole report — the customer immediately sees what to do, the operator starts with the diagnosis instead of asking.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db

router = APIRouter()


class CheckIn(BaseModel):
    name: str = Field(max_length=60)
    target: str = Field("", max_length=200)
    ok: bool
    ms: int | None = Field(None, ge=0, le=120000)
    detail: str = Field("", max_length=300)


class DiagnosticsIn(BaseModel):
    message: str = Field("", max_length=2000)
    platform: str = Field("", max_length=20)
    app_version: str = Field("", max_length=20)
    os_version: str = Field("", max_length=40)
    network: str = Field("", max_length=20)
    vpn_state: str = Field("", max_length=20)
    checks: list[CheckIn] = Field(default_factory=list, max_length=40)


def verdict(facts: dict, checks: list[CheckIn]) -> tuple[str, list[str]]:
    """The most likely cause first; hints are what the customer can do right now."""
    servers = [c for c in checks if c.name == "server"]
    if facts["subscription"] is None:
        return "no_subscription", ["Подписки нет: оформите её в разделе «Тарифы»."]
    if facts["subscription"]["expired"]:
        return "expired", ["Подписка закончилась: продлите её в разделе «Тарифы» — VPN включится сразу после оплаты."]
    if facts["device_limit"] and facts["devices"] > facts["device_limit"]:
        return "device_limit", [f"Подключено {facts['devices']} устройств при лимите {facts['device_limit']}: "
                                "удалите лишнее в разделе «Устройства» или выберите тариф с большим лимитом."]
    if facts["nodes_online"] == 0 and facts["nodes_total"]:
        return "servers_down", ["Серверы сейчас недоступны у всех — мы уже чиним. Попробуйте через несколько минут."]
    if any(c.name == "api" and not c.ok for c in checks) or any(c.name == "subscription" and not c.ok for c in checks):
        return "shop_unreachable", ["Приложение не достучалось до магазина: переключите Wi-Fi ↔ мобильный интернет; "
                                    "приложение само попробует резервный адрес."]
    if servers and not any(c.ok for c in servers):
        return "servers_blocked", ["Ваша сеть не пускает к серверам: включите режим «Авто» или выберите другую локацию; "
                                   "если не помогло — переключите сеть. Мы проверим блокировку в вашем регионе."]
    if servers and any(not c.ok for c in servers):
        return "some_servers", ["Часть серверов не отвечает из вашей сети: выберите «Авто» — приложение возьмёт рабочий сервер."]
    return "unknown", ["Серверы и подписка в порядке. Поддержка уже получила отчёт и ответит здесь, в обращениях."]


async def server_facts(db: AsyncSession, user_id: int) -> dict:
    from .models import Payment, Subscription, UserDevice
    from .node_health import node_snapshot
    now = datetime.utcnow()
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user_id, Subscription.is_primary.is_(True)))
    devices = await db.scalar(select(func.count()).select_from(UserDevice).where(UserDevice.user_id == user_id, UserDevice.revoked_at.is_(None))) or 0
    last = await db.scalar(select(Payment).where(Payment.user_id == user_id).order_by(Payment.id.desc()).limit(1))
    snap = await node_snapshot()
    nodes = [n for n in snap.get("nodes", []) if n.get("status") != "disabled"]
    return {
        "subscription": None if not sub else {"status": sub.lifecycle_status, "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
                                              "expired": bool(sub.expires_at and sub.expires_at <= now)},
        "device_limit": sub.device_limit_snapshot if sub else None, "devices": int(devices),
        "nodes_total": len(nodes), "nodes_online": sum(1 for n in nodes if n.get("status") == "online"),
        "last_payment": None if not last else {"id": last.id, "status": last.status, "fulfillment": last.fulfillment_status,
                                               "created_at": last.created_at.isoformat() if last.created_at else None},
    }


def render(payload: DiagnosticsIn, facts: dict, cause: str, hints: list[str]) -> str:
    lines = [payload.message.strip() or "(клиент ничего не написал)", "", f"Вероятная причина: {cause}"]
    lines += [f"Подсказка клиенту: {h}" for h in hints]
    lines += ["", f"Приложение: {payload.platform} {payload.app_version} · ОС {payload.os_version} · сеть {payload.network or '?'} · VPN {payload.vpn_state or '?'}"]
    sub = facts["subscription"]
    lines.append("Подписка: нет" if not sub else f"Подписка: {sub['status']}, до {sub['expires_at'] or '—'}")
    lines.append(f"Устройства: {facts['devices']} из {facts['device_limit'] or '∞'} · ноды в сети: {facts['nodes_online']}/{facts['nodes_total']}")
    if facts["last_payment"]:
        p = facts["last_payment"]
        lines.append(f"Последний платёж №{p['id']}: {p['status']} / {p['fulfillment']}")
    lines += ["", "Проверки приложения:"]
    for c in payload.checks:
        lines.append(f"{'✓' if c.ok else '✗'} {c.name} {c.target} {str(c.ms) + ' мс' if c.ms is not None else ''} {c.detail}".rstrip())
    return "\n".join(lines)[:10000]


@router.post("/api/me/diagnostics")
async def my_diagnostics(payload: DiagnosticsIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    from .models import SupportTicket
    user = await user_from_token(request, db)
    facts = await server_facts(db, user.id)
    cause, hints = verdict(facts, payload.checks)
    ticket = SupportTicket(user_id=user.id, subject="Не работает VPN — отчёт диагностики", message=render(payload, facts, cause, hints))
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return {"ticket_id": ticket.id, "cause": cause, "hints": hints}
