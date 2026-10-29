"""v28.49 payment antifraud: card testing, new account with a big amount, many accounts from one address, chargebacks,
the blocklist; refusals are recorded and the operator is told."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app import main as shop
from app import payment_fraud as pf
from app.payment_platform_api import _risk_score  # the real score: the database fixture stubs shop._risk_score
from app.models import FraudSignal, Payment, PaymentChargeback, User
from test_subscription_commerce import database  # noqa: F401


class Sets:
    def __init__(self):
        self.data, self.flags = {}, set()

    async def sadd(self, key, value):
        self.data.setdefault(key, set()).add(value)

    async def expire(self, key, ttl):
        return True

    async def scard(self, key):
        return len(self.data.get(key, set()))

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.flags:
            return False
        self.flags.add(key)
        return True


def req(ip="203.0.113.5"):
    return Request({"type": "http", "method": "POST", "path": "/api/payments/create", "headers": [], "query_string": b"", "client": (ip, 1)})


@pytest.fixture
def env(database, monkeypatch):  # noqa: F811
    redis = Sets()
    monkeypatch.setattr(shop, "redis_client", redis)
    monkeypatch.setattr(shop, "_client_ip", lambda request: request.client.host)
    sent = []

    async def send(text):
        sent.append(text)
        return True
    monkeypatch.setattr("app.ops_alerts.send", send)
    return database, sent


async def _failed(db, n):
    for i in range(n):
        db.add(Payment(user_id=1, plan_id=1, provider="yookassa", order_id=f"f-{i}", amount=Decimal("100"), original_amount=Decimal("100"),
                       discount_amount=Decimal("0"), currency="RUB", status="failed", fulfillment_status="pending", idempotency_key=f"f-{i}",
                       purpose="subscription", bonus_days=0))
    await db.commit()


@pytest.mark.asyncio
async def test_card_testing_and_chargebacks_add_up_to_a_refusal(env):
    db, sent = env
    user = await db.get(User, 1)
    user.created_at = datetime.utcnow() - timedelta(days=30)
    await db.commit()
    score, decision, signals = await _risk_score(db, user, Decimal("100"), req())
    assert decision == "allow" and "failed_24h" not in signals
    await _failed(db, 5)
    score, decision, signals = await _risk_score(db, user, Decimal("100"), req())
    assert signals["failed_24h"] == 5 and score >= 35
    db.add(PaymentChargeback(payment_id=(await db.scalar(select(Payment.id).limit(1))), provider="yookassa", external_id="cb-1",
                             amount=Decimal("100"), currency="RUB"))
    await db.commit()
    score, decision, signals = await _risk_score(db, user, Decimal("100"), req())
    assert decision == "block" and signals["chargebacks"] == 1
    refused = (await db.execute(select(FraudSignal).where(FraudSignal.kind == "payment_blocked"))).scalars().all()
    assert refused and refused[-1].user_id == 1 and refused[-1].ip == "203.0.113.5"
    assert any("отклонён" in t for t in sent)
    before = len(sent)
    await _risk_score(db, user, Decimal("100"), req())
    assert len(sent) == before, "one card an hour per customer"


@pytest.mark.asyncio
async def test_new_account_big_amount_and_accounts_from_one_address(env):
    db, _ = env
    user = await db.get(User, 1)
    user.created_at = datetime.utcnow() - timedelta(minutes=20)
    await db.commit()
    _, _, signals = await _risk_score(db, user, Decimal("5000"), req())
    assert signals["new_account"]["amount"] == "5000"
    _, _, small = await _risk_score(db, user, Decimal("100"), req())
    assert "new_account" not in small
    for uid in (2, 3, 4):
        await pf._ip_accounts("198.51.100.9", uid)
    _, _, many = await _risk_score(db, user, Decimal("100"), req("198.51.100.9"))
    assert many["accounts_per_ip"] == 4


@pytest.mark.asyncio
async def test_blocklist_refuses_at_once_and_rules_can_be_switched_off(env):
    db, _ = env
    user = await db.get(User, 1)
    user.telegram_id = 777
    await db.commit()
    from app.node_health import _save
    await _save(db, pf.CONFIG_KEY, {**pf.DEFAULT, "block_telegram_ids": [777]})
    await db.commit()
    score, decision, signals = await _risk_score(db, user, Decimal("10"), req())
    assert (score, decision, signals.get("blocklist")) == (100, "block", True)
    await _save(db, pf.CONFIG_KEY, {**pf.DEFAULT, "enabled": False, "block_telegram_ids": [777]})
    await db.commit()
    assert (await _risk_score(db, user, Decimal("10"), req()))[1] == "allow"
    with pytest.raises(ValueError):
        pf.RulesIn(accounts_per_ip=1)


@pytest.mark.asyncio
async def test_weekly_standby_drill_ends_with_a_report(database):  # noqa: F811
    from app.hot_standby import drill_report
    sent = []

    async def sender(text):
        sent.append(text)
    ok = await drill_report(database, {"at": "2026-10-29T03:00", "ok": True, "users": 120, "payments": 340, "migration": "0083_corporate_seats"}, 2.0, sender)
    assert "пройдены" in ok and "клиентов 120" in ok and "2 с" in ok and "нет проверенных копий" in ok
    bad = await drill_report(database, {"at": "2026-11-05T03:00", "ok": False, "error": "no space left on device"}, None, sender)
    assert "не прошли" in bad and "no space left" in bad and len(sent) == 2


def test_live_load_profile_is_read_only():
    text = open("tests/load/live.js", encoding="utf-8").read()
    assert "http.post" not in text and "register" not in text and "/api/public/status-page" in text
    flow = open(".github/workflows/load-live.yml", encoding="utf-8").read()
    assert "workflow_dispatch" in flow and "schedule" not in flow, "a real server is loaded only by hand"
