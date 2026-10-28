"""Payment method routing: СБП / card / crypto each has its own gateway chain; YooKassa opens on the chosen method;
the public config lists only methods with a working gateway; mobile admin panels drive the same API."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main as shop
from app import mobile_panels
from app import payment_methods as pm
from app.models import Payment
from test_payment_failover_chain import STATE, shop_env  # noqa: F401
from test_behaviour_payments_v2 import checkout
from test_cryptobot import api  # noqa: F401
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test")
HINTS = []
counter = {"n": 0}


async def buy(db, method):
    counter["n"] += 1
    key = f"method-{counter['n']}"
    body = {"plan_id": 1, **({"method": method} if method else {})}
    code = 200
    try:
        await shop.create_payment(body, checkout([(b"idempotency-key", key.encode())]), db)
    except HTTPException as exc:
        code = exc.status_code
    row = await db.scalar(select(Payment).where(Payment.idempotency_key == key))
    if row:  # settle it, or the next checkout is «the same open order»
        row.status = "failed"
        await db.commit()
    return (row.provider if row else None), code


@pytest.mark.asyncio
async def test_each_method_has_its_own_chain(shop_env, monkeypatch):  # noqa: F811
    db = shop_env

    class Yoo:
        async def create(self, amount, order_id, description, return_url, method=""):
            HINTS.append(method)
            if "yookassa" in STATE["down"]:
                raise RuntimeError("yookassa down")
            return {"id": f"y-{order_id}", "url": "https://pay.yookassa.test/x"}
    monkeypatch.setattr(shop, "YooKassaProvider", Yoo)
    # Routing off: the method is ignored, the common queue decides.
    assert await buy(db, "crypto") == ("yookassa", 200) and HINTS[-1] == ""
    routes = {"sbp": ["platega", "yookassa"], "card": ["yookassa", "rollypay"], "crypto": ["cryptobot"]}
    await pm.put_routing(pm.RoutingIn(enabled=True, routes=routes), db, ADMIN)
    with pytest.raises(HTTPException):
        await pm.put_routing(pm.RoutingIn(enabled=True, routes={"crypto": ["yookassa"]}), db, ADMIN)
    assert await buy(db, "sbp") == ("platega", 200)
    assert await buy(db, "card") == ("yookassa", 200) and HINTS[-1] == "bank_card", "YooKassa opens on the card form"
    assert (await buy(db, "crypto"))[0] == "cryptobot"
    STATE["down"].add("yookassa")
    for _ in range(3):
        await buy(db, "card")  # three failures cool YooKassa down
    assert (await buy(db, "card"))[0] == "rollypay", "the next gateway of the card chain takes over"
    assert (await buy(db, "sbp"))[0] == "platega"
    with pytest.raises(HTTPException):
        pm.order_for(await pm.load(db), "paypal", ["yookassa"])
    # Public config: only methods with a working gateway.
    config = await pm.load(db)
    assert [m["key"] for m in await pm.available_methods(db, ["cryptobot"])] == ["crypto"]
    assert config["routes"]["sbp"][:2] == ["platega", "yookassa"] and "rollypay" in config["routes"]["sbp"], "unlisted capable gateways follow"


@pytest.mark.asyncio
async def test_mobile_panels_describe_modules(shop_env):  # noqa: F811
    db = shop_env
    out = await mobile_panels.mobile_panels(db, ADMIN)
    ids = [p["id"] for p in out["panels"]]
    assert ids[:4] == ["payment_methods", "hot_standby", "node_autoscale", "block_monitor"]
    methods = out["panels"][0]
    assert all(a["path"].startswith("/api/admin/") for p in out["panels"] for a in p["actions"])
    toggle = methods["actions"][0]
    assert toggle["method"] == "PUT" and toggle["body"]["enabled"] is True
    await pm.put_routing(pm.RoutingIn(**toggle["body"]), db, ADMIN)
    assert (await pm.load(db))["enabled"] is True
    up = next(a for a in methods["actions"] if a["label"].startswith("СБП:"))
    assert up["body"]["routes"]["sbp"][0] != (await pm.load(db))["routes"]["sbp"][0]
    auto = next(p for p in out["panels"] if p["id"] == "node_autoscale")
    assert any(a["confirm"] for a in auto["actions"]), "switching to auto mode asks first"
