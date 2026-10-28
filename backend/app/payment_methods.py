"""Payment method routing: the customer picks «СБП», «Карта» or «Криптовалюта», each method has its own gateway chain.

Without routing (the default) checkout uses the single gateway queue. With routing on:

* the cabinet, Mini App and apps get ``payment_methods`` in the public config — only methods that have at least one
  working gateway right now (enabled, keys set, not cooling down);
* ``POST /api/payments/create`` takes ``method``; the gateways are tried in that method's order, a refusing gateway
  hands the order to the next one of the same method;
* YooKassa opens straight on the chosen method (``payment_method_data.type`` = ``sbp`` / ``bank_card``); the other
  gateways show their own page where the customer confirms the method.

Which gateway can take which method is fixed in ``CAPABILITIES``; the owner orders them per method in
«Платёжные агенты → Способы оплаты» (web and mobile admin).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()

CONFIG_KEY = "payments.method_routing"
METHODS = {"sbp": "СБП", "card": "Банковская карта", "crypto": "Криптовалюта"}
CAPABILITIES = {
    "yookassa": {"sbp", "card"}, "rollypay": {"sbp", "card"}, "platega": {"sbp", "card"},
    "freekassa": {"sbp", "card"}, "cloudpayments": {"sbp", "card"}, "lava": {"sbp", "card"}, "pal24": {"sbp", "card"}, "mulenpay": {"sbp", "card"}, "wata": {"sbp", "card"}, "antilopay": {"sbp", "card"}, "cryptobot": {"crypto"}, "sandbox": {"sbp", "card", "crypto"},
}
YOOKASSA_TYPES = {"sbp": "sbp", "card": "bank_card"}


def default_routes() -> dict[str, list[str]]:
    from .payment_policy import PAYMENT_AGENTS
    return {m: [p for p in PAYMENT_AGENTS if m in CAPABILITIES.get(p, set())] for m in METHODS}


class RoutingIn(BaseModel):
    enabled: bool
    routes: dict[str, list[str]] = Field(default_factory=dict)


async def load(db: AsyncSession) -> dict:
    from .node_health import _load
    config = await _load(db, CONFIG_KEY, {"enabled": False, "routes": {}})
    routes = default_routes()
    for method, order in (config.get("routes") or {}).items():
        if method in routes:
            known = [p for p in order if p in routes[method]]
            routes[method] = known + [p for p in routes[method] if p not in known]
    return {"enabled": bool(config.get("enabled")), "routes": routes}


def order_for(config: dict, method: str, available: list[str]) -> list[str]:
    """Gateways for ``method`` in the owner's order, limited to those that can take a payment now."""
    if method not in METHODS:
        raise HTTPException(400, "Неизвестный способ оплаты")
    allowed = set(available)
    order = [p for p in config["routes"].get(method, []) if p in allowed]
    if "sandbox" in allowed and "sandbox" not in order:
        order.append("sandbox")
    return order


async def available_methods(db: AsyncSession, available: list[str]) -> list[dict]:
    """Public config: methods the customer can choose right now (empty when routing is off)."""
    config = await load(db)
    if not config["enabled"]:
        return []
    return [{"key": m, "title": title, "providers": len(order_for(config, m, available))}
            for m, title in METHODS.items() if order_for(config, m, available)]


@router.get("/api/admin/payments/methods")
async def get_routing(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    from .payments_api import provider_configured
    config = await load(db)
    configured = provider_configured()
    return {**config, "methods": METHODS, "capabilities": {p: sorted(c) for p, c in CAPABILITIES.items() if p != "sandbox"},
            "configured": {p: bool(v) for p, v in configured.items() if p != "sandbox"}}


@router.put("/api/admin/payments/methods")
async def put_routing(payload: RoutingIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .main import audit
    from .node_health import _save
    routes = {}
    for method, order in payload.routes.items():
        if method not in METHODS:
            raise HTTPException(400, f"Неизвестный способ оплаты: {method}")
        wrong = [p for p in order if method not in CAPABILITIES.get(p, set())]
        if wrong:
            raise HTTPException(400, f"{', '.join(wrong)} не принимает «{METHODS[method]}»")
        routes[method] = list(dict.fromkeys(order))
    value = {"enabled": payload.enabled, "routes": routes}
    await _save(db, CONFIG_KEY, value)
    await audit(db, "payments.method_routing", admin.email, None, value)
    await db.commit()
    return await load(db)
