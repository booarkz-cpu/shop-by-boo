"""v28.45: the gateway package and its table, the probe that takes a broken gateway out of the queue and brings it back,
the report of notifications that never came, and «best gateway first»."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import gateway_ops as ops
from app import payments_extra as px
from app.config import settings
from app.gateways import GATEWAYS, common
from app.models import Payment, PaymentProviderEvent, PaymentProviderHealth
from app.payment_methods import CAPABILITIES
from app.payment_policy import PAYMENT_AGENTS, PROVIDER_CAPABILITIES
from test_subscription_commerce import database  # noqa: F401


def test_table_agrees_with_the_queue_methods_settings_and_routes():
    routes = {r.path for r in px.router.routes}
    for name, g in GATEWAYS.items():
        assert name in PAYMENT_AGENTS and CAPABILITIES[name] == set(g.methods)
        assert PROVIDER_CAPABILITIES[name] == {"cards": True, "recurring": g.recurring, "refunds": g.refunds}
        assert all(hasattr(settings, k) for k in g.keys), name
        assert g.webhook in routes, name
        assert hasattr(g.cls, "probe") and px.__dict__[g.cls.__name__] is g.cls, "the old module still exports every class"


class Answer:
    def __init__(self, code=200, boom=None):
        self.code, self.boom, self.calls = code, boom, []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.boom:
            raise self.boom
        return type("R", (), {"status_code": self.code})()


def _client(monkeypatch, api):
    @asynccontextmanager
    async def client(timeout):
        yield api
    monkeypatch.setattr(common, "_public_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("code,boom,expected", [(200, None, ""), (404, None, ""), (401, None, "ключи не приняты (HTTP 401)"),
                                                (503, None, "касса отвечает ошибкой (HTTP 503)"), (200, OSError("x"), "нет связи: OSError")])
async def test_probe_tells_keys_from_outages(monkeypatch, code, boom, expected):
    _client(monkeypatch, Answer(code, boom))
    assert await common.probe_http("GET", "https://gw.test/x") == expected


@pytest.mark.asyncio
async def test_every_gateway_probes_its_own_api(monkeypatch):
    api = Answer(404)
    _client(monkeypatch, api)
    for k in {k for g in GATEWAYS.values() for k in g.keys}:
        monkeypatch.setattr(settings, k, "x")
    for name in ("cloudpayments", "pal24", "mulenpay", "wata", "aurapay", "anore", "cashera", "paritypay", "lava"):
        assert await GATEWAYS[name].cls().probe() == "", name
    hosts = {c[1].split("/")[2] for c in api.calls}
    assert {"api.cloudpayments.ru", "pal24.pro", "mulenpay.ru", "api.wata.pro", "app.aurapay.tech", "api.anore.cc", "api.cashera.cash",
            "api.paritypay.net", "api.lava.ru"} <= hosts
    monkeypatch.setattr(settings, "antilopay_private_key", "not a key")
    assert await GATEWAYS["antilopay"].cls().probe() == "закрытый ключ не читается"


@pytest.mark.asyncio
async def test_probe_takes_a_broken_gateway_out_and_brings_it_back(database, monkeypatch):  # noqa: F811
    db = database
    for k in GATEWAYS["pal24"].keys:
        monkeypatch.setattr(settings, k, "x")
    answers = ["ключи не приняты (HTTP 401)", "ключи не приняты (HTTP 401)", ""]

    async def probe(self):
        return answers.pop(0)
    monkeypatch.setattr(GATEWAYS["pal24"].cls, "probe", probe)
    alerts = []

    async def alert(text):
        alerts.append(text)
    now = datetime(2026, 10, 29, 12, 0)
    state = await ops.probe_all(db, now, alert)
    assert state["pal24"]["fails"] == 1 and not alerts, "one failure is not enough"
    state = await ops.probe_all(db, now + timedelta(hours=6), alert)
    row = (await db.execute(select(PaymentProviderHealth).where(PaymentProviderHealth.provider == "pal24"))).scalar_one()
    assert state["pal24"]["taken_out"] and row.circuit_open_until == now + timedelta(hours=12) and row.last_error.startswith("probe:")
    assert "выведена из очереди" in alerts[-1]
    state = await ops.probe_all(db, now + timedelta(hours=12), alert)
    await db.refresh(row)
    assert state["pal24"]["ok"] and not state["pal24"]["taken_out"] and row.circuit_open_until is None
    assert "снова в очереди" in alerts[-1]


async def _pay(db, pid, provider, status, created, order):
    db.add(Payment(id=pid, user_id=1, plan_id=1, provider=provider, order_id=order, amount=Decimal("100"), original_amount=Decimal("100"),
                   discount_amount=Decimal("0"), currency="RUB", status=status, fulfillment_status="pending", idempotency_key=order,
                   purpose="subscription", bonus_days=0, created_at=created))


@pytest.mark.asyncio
async def test_notifications_that_never_came_and_the_alert(database):  # noqa: F811
    db = database
    now = datetime(2026, 10, 29, 12, 0)
    for i in range(6):
        await _pay(db, 100 + i, "lava", "paid", now - timedelta(hours=3), f"o-{i}")
    db.add(PaymentProviderEvent(provider="lava", event_id="e-0", payment_id=100, status="processed", received_at=now - timedelta(hours=2)))
    await _pay(db, 120, "lava", "pending", now - timedelta(hours=2), "o-stuck")
    await _pay(db, 121, "lava", "pending", now - timedelta(minutes=5), "o-fresh")
    await db.commit()
    report = await ops.notifications_report(db, 1, now, 30)
    lava = next(p for p in report["providers"] if p["provider"] == "lava")
    assert lava == {"provider": "lava", "paid": 6, "without_notification": 5, "stuck_pending": 1, "missing_share": 83.3}
    alerts = []

    async def alert(text):
        alerts.append(text)
    assert await ops.check_notifications(db, now, alert) == ["lava"] and "не приходят уведомления" in alerts[0]
    assert await ops.check_notifications(db, now + timedelta(hours=1), alert) == [], "once a day per gateway"


@pytest.mark.asyncio
async def test_best_converting_gateway_goes_first(database, monkeypatch):  # noqa: F811
    db = database
    for i, p in enumerate(("yookassa", "lava", "pal24"), 1):
        db.add(PaymentProviderHealth(provider=p, priority=i * 10, enabled=True))
    await db.commit()

    async def report(session, days, now=None):
        return {"providers": [{"provider": "pal24", "orders": 40, "conversion": 80.0}, {"provider": "yookassa", "orders": 100, "conversion": 60.0},
                              {"provider": "lava", "orders": 3, "conversion": 100.0}]}
    monkeypatch.setattr("app.provider_report.build_report", report)
    dry = await ops.auto_priority(db, dry_run=True)
    assert dry["after"] == ["pal24", "yookassa", "lava"] and dry["changed"] and not dry["applied"], "lava has too few orders to rank"
    done = await ops.auto_priority(db)
    rows = (await db.execute(select(PaymentProviderHealth).order_by(PaymentProviderHealth.priority))).scalars().all()
    assert done["applied"] and [r.provider for r in rows] == ["pal24", "yookassa", "lava"]
    assert (await ops.auto_priority(db))["changed"] is False
