"""Stage 19, C1: a payment notification that arrives after a refund never revives the payment (YooKassa, Platega,
RollyPay). Replaces test_v44_5_18_deep_regressions.test_all_webhooks_ignore_late_success_for_refunded_payments, which
looked for a comment and a status set in the source."""
import json
from decimal import Decimal

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app import main as shop
from app.models import Payment
from test_subscription_commerce import database  # noqa: F401


def request(path: str, body: dict, headers: dict | None = None, ip="10.1.2.3"):
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    hdrs = [(b"content-type", b"application/json")] + [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "POST", "path": path, "headers": hdrs, "client": (ip, 443), "query_string": b""}, receive)


CASES = [
    ("yookassa", "yookassa_webhook", "/api/webhooks/yookassa",
     lambda pid, order: {"id": "evt-" + pid, "event": "payment.succeeded", "object": {"id": pid, "metadata": {"order_id": order}}}),
    ("platega", "platega_webhook", "/api/webhooks/platega",
     lambda pid, order: {"id": pid, "status": "CONFIRMED", "payload": order}),
    ("rollypay", "rollypay_webhook", "/api/webhooks/rollypay",
     lambda pid, order: {"payment_id": pid, "status": "paid", "order_id": order, "event_id": "evt-" + pid}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider, handler, path, body", CASES)
@pytest.mark.parametrize("status", ["refunded", "refunded_pending_revoke"])
async def test_late_success_after_a_refund_is_ignored(database, monkeypatch, provider, handler, path, body, status):
    pid, order = f"{provider}-pay", f"{provider}-order"
    database.add(Payment(user_id=1, subscription_id=1, plan_id=1, provider=provider, order_id=order, provider_payment_id=pid,
                         amount=Decimal("100"), currency="RUB", status=status, idempotency_key=f"{provider}-idem"))
    await database.commit()
    monkeypatch.setattr(shop, "engine", database.bind)
    monkeypatch.setattr(shop.settings, "yookassa_webhook_ip_allowlist", "10.0.0.0/8")
    # The gateway itself says «paid» (verified), and the notification is authentic.

    async def verified(self, *a, **k):
        return True
    for cls in (shop.YooKassaProvider, shop.PlategaProvider, shop.RollyPayProvider):
        monkeypatch.setattr(cls, "verify_succeeded", verified)
    monkeypatch.setattr(shop.PlategaProvider, "verify_webhook", lambda self, headers, raw: json.loads(raw))
    monkeypatch.setattr(shop, "verify_rollypay", lambda raw, stamp, signature: True)
    # Claiming the event is PostgreSQL SQL with its own test (test_behaviour_payments_v2): here it always succeeds.
    events = []

    async def claim(db, prov, event_id, payment_id):
        events.append((prov, event_id)); return True

    async def finish(db, prov, event_id, ok=True, error=None):
        events.append((prov, "finished", ok))
    monkeypatch.setattr(shop, "register_provider_event", claim)
    monkeypatch.setattr(shop, "finish_provider_event", finish)
    fulfilled = []

    async def provision(*a, **k):
        fulfilled.append(a)
    for name in ("provision_payment", "_provision_after_payment", "fulfill_payment"):
        if hasattr(shop, name):
            monkeypatch.setattr(shop, name, provision)

    answer = await getattr(shop, handler)(request(path, body(pid, order)), database)
    assert answer.get("ignored") is True and answer.get("reason") == "payment_already_refunded", answer
    row = (await database.execute(select(Payment).where(Payment.order_id == order))).scalar_one()
    await database.refresh(row)
    assert row.status == status, "a refunded payment is never moved back to paid"
    assert fulfilled == [], "no access is given for a refunded payment"
    assert (provider, "finished", True) in events, "the event is closed as handled, not retried"
