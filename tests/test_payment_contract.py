"""v28.73 (stage 14): one contract for every gateway of the registry — a notification is only a hint.

For each gateway in ``app.gateways.GATEWAYS`` the shared settlement (``gateways.common._settle``) must:
refuse an order of another gateway and a different amount (403), never fulfil when the gateway itself does not confirm
the payment (503), fulfil a confirmed one exactly once, answer a repeated notification as a duplicate, and ignore an
unknown order. Refused notifications land in the payment journal; accepted ones are listed there with their order.
PostgreSQL only: the event claim uses ``INSERT … ON CONFLICT … RETURNING`` with ``NOW()``.
"""
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app import main as shop
from app import payment_journal as pj
from app.gateways import GATEWAYS
from app.gateways.common import _settle
from app.models import Payment, PaymentProviderEvent
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@example.com", role="owner")


class Gateway:
    def __init__(self, confirmed=True):
        self.confirmed = confirmed
        self.asked = []

    async def verify_succeeded(self, pid, amount, currency, order_id):
        self.asked.append((pid, amount, currency, order_id))
        return self.confirmed


@pytest.fixture
def fulfil(database, monkeypatch):  # noqa: F811
    if database.bind.dialect.name != "postgresql":
        pytest.skip("event claim is PostgreSQL SQL")
    done = []

    async def confirm(payment_id, db):
        done.append(payment_id)
    monkeypatch.setattr(shop, "_confirm_and_fulfill_payment", confirm)
    monkeypatch.setattr(shop, "engine", database.bind)
    return done


async def _order(db, provider, n):
    p = Payment(user_id=1, subscription_id=1, plan_id=1, provider=provider, order_id=f"{provider}-order-{n}", amount=Decimal("199.00"),
                original_amount=Decimal("199.00"), discount_amount=Decimal("0"), currency="RUB", status="pending",
                fulfillment_status="pending", idempotency_key=f"{provider}-{n}", purpose="subscription", bonus_days=0)
    db.add(p)
    await db.commit()
    return p


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(GATEWAYS))
async def test_every_gateway_settles_only_confirmed_matching_orders_once(name, database, fulfil):  # noqa: F811
    db = database
    order = await _order(db, name, 1)
    oid, pk = order.order_id, order.id  # rollbacks below expire the loaded row
    other = sorted(set(GATEWAYS) - {name})[0]
    try:  # the order of this gateway named in another gateway's notification: unknown there, or refused
        assert await _settle(db, other, Gateway(), oid, "e-0", "199.00") == "unknown"
    except HTTPException as exc:
        assert exc.status_code == 403
    await db.rollback()
    assert fulfil == []
    with pytest.raises(HTTPException) as exc:
        await _settle(db, name, Gateway(), oid, "e-1", "1.00")
    assert exc.value.status_code == 403
    await db.rollback()
    with pytest.raises(HTTPException) as exc:
        await _settle(db, name, Gateway(confirmed=False), oid, "e-2", "199.00")
    assert exc.value.status_code == 503 and fulfil == []
    await db.rollback()
    gw = Gateway()
    assert await _settle(db, name, gw, oid, "e-3", "199.00") == "paid"
    assert fulfil == [pk] and gw.asked[0][1] == Decimal("199.00") and gw.asked[0][2] == "RUB" and gw.asked[0][3] == oid
    assert await _settle(db, name, Gateway(), oid, "e-3", "199.00") == "duplicate"
    assert fulfil == [pk]  # a repeated notification is not a second fulfilment
    assert await _settle(db, name, Gateway(), "no-such-order", "e-4", "199.00") == "unknown"
    events = (await db.execute(PaymentProviderEvent.__table__.select().where(PaymentProviderEvent.provider == name))).all()
    assert [e.status for e in events] == ["processed"]


@pytest.mark.asyncio
async def test_a_failed_fulfilment_is_left_for_a_retry(database, fulfil, monkeypatch):  # noqa: F811
    db = database
    order = await _order(db, "lava", 2)
    oid = order.order_id

    async def broken(payment_id, session):
        raise RuntimeError("panel down")
    monkeypatch.setattr(shop, "_confirm_and_fulfill_payment", broken)
    with pytest.raises(RuntimeError):
        await _settle(db, "lava", Gateway(), oid, "e-9", "199.00")
    await db.rollback()
    row = (await db.execute(PaymentProviderEvent.__table__.select().where(PaymentProviderEvent.event_id == "e-9"))).first()
    assert row.status == "retry" and "panel down" in row.last_error
    monkeypatch.setattr(shop, "_confirm_and_fulfill_payment", lambda payment_id, session: _ok())
    assert await _settle(db, "lava", Gateway(), oid, "e-9", "199.00") == "paid"  # the gateway's retry is taken again


async def _ok():
    return None


@pytest.mark.asyncio
async def test_journal_lists_accepted_and_refused_notifications(database, fulfil, monkeypatch):  # noqa: F811
    db = database
    monkeypatch.setattr(shop, "redis_client", None)
    pj._local.clear()
    order = await _order(db, "wata", 3)
    oid = order.order_id
    await _settle(db, "wata", Gateway(), oid, "w-1", "199.00")
    app = FastAPI()

    @app.post("/api/webhooks/{name}")
    async def hook(name: str):
        raise HTTPException(403, "Invalid signature")
    pj.install(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://shop") as c:
        assert (await c.post("/api/webhooks/lava", content=b"{}")).status_code == 403
        assert (await c.post("/api/webhooks/remnawave", content=b"{}")).status_code == 403  # the panel is not a gateway
    data = await pj.payment_events("", 7, 100, db, ADMIN)
    assert data["accepted"][0]["order_id"] == oid and data["accepted"][0]["status"] == "processed"
    assert [r["provider"] for r in data["refused"]] == ["lava"] and data["refused"][0]["reason"].startswith("подпись")
    assert data["summary"]["processed"] == 1 and data["summary"]["refused"] == 1
    only = await pj.payment_events("lava", 7, 100, db, ADMIN)
    assert only["accepted"] == [] and len(only["refused"]) == 1


def test_gateway_of_paths():
    assert pj.gateway_of("/api/webhooks/lava") == "lava"
    assert pj.gateway_of("/api/webhooks/freekassa/") == "freekassa"
    assert pj.gateway_of("/api/webhooks/remnawave") is None
    assert pj.gateway_of("/api/payments/create") is None
