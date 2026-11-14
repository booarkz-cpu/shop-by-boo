"""Operator alerts: what is reported, once per problem, repeated every REPEAT, resolved notes; launch readiness."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import ops_alerts
from app.config import settings
from app.models import AppSetting, BackupJob, MonitoringCheck, Payment, PaymentProviderHealth, Plan, WorkerState
from test_subscription_commerce import database

ADMIN = SimpleNamespace(email="root@example.test", role="admin")


class Panel:
    def __init__(self, ok=True):
        self.ok = ok

    async def list_nodes(self, start=0, size=1):
        if not self.ok:
            raise RuntimeError("connection refused")
        return {}


async def seed_problems(db, now):
    db.add_all([
        Payment(user_id=1, plan_id=1, provider="yookassa", order_id="failed-1", amount=199, currency="RUB", status="paid",
                fulfillment_status="failed", fulfillment_error="Remnawave 500", paid_at=now - timedelta(hours=1)),
        Payment(user_id=1, plan_id=1, provider="yookassa", order_id="stuck-1", amount=199, currency="RUB", status="paid",
                fulfillment_status="pending", paid_at=now - timedelta(minutes=40)),
        Payment(user_id=1, plan_id=1, provider="yookassa", order_id="fresh-1", amount=199, currency="RUB", status="paid",
                fulfillment_status="pending", paid_at=now - timedelta(minutes=2)),
        PaymentProviderHealth(provider="platega", enabled=True, failure_count=3, circuit_open_until=now + timedelta(minutes=4)),
        WorkerState(worker_id="worker-1", role="worker", status="online", last_seen_at=now - timedelta(minutes=10)),
        WorkerState(worker_id="worker-2", role="worker", status="online", last_seen_at=now - timedelta(seconds=20)),
        MonitoringCheck(name="Сайт", url="https://example.com", enabled=True, failure_streak=3, last_status="down", last_error="timeout"),
        BackupJob(status="failed", error="disk full", created_at=now - timedelta(hours=2)),
    ])
    await db.commit()


@pytest.mark.asyncio
async def test_problems_an_operator_must_act_on_are_collected(database, monkeypatch):
    monkeypatch.setattr(settings, "remnawave_url", "https://panel.example")
    monkeypatch.setattr(settings, "remnawave_token", "t")
    now = datetime.utcnow()
    await seed_problems(database, now)
    found = {p.key.split(":")[0]: p for p in await ops_alerts.collect(database, now, remnawave=Panel(ok=False))}
    # v28.145.0: «rpo» — backups are off in the seed while the owner's target is one hour of data at most.
    assert set(found) == {"fulfillment", "stuck", "provider", "worker", "monitor", "backup", "remnawave", "rpo"}
    assert found["fulfillment"].severity == "critical" and "Remnawave 500" in found["fulfillment"].detail
    assert "40 мин" in found["stuck"].detail and found["worker"].key == "worker:worker-1"
    assert not any(p.key.startswith("remnawave") for p in await ops_alerts.collect(database, now, remnawave=Panel(ok=True)))


@pytest.mark.asyncio
async def test_each_problem_is_sent_once_repeated_later_and_resolved(database):
    now = datetime.utcnow()
    messages = []

    async def sender(text):
        messages.append(text)
        return True
    problems = [ops_alerts.Problem("provider:platega", "Касса platega временно отключена", "детали")]
    assert (await ops_alerts.dispatch(database, problems, now, sender))["sent"] == ["provider:platega"]
    assert (await ops_alerts.dispatch(database, problems, now + timedelta(hours=1), sender))["sent"] == []
    assert (await ops_alerts.dispatch(database, problems, now + ops_alerts.REPEAT + timedelta(minutes=1), sender))["sent"] == ["provider:platega"]
    result = await ops_alerts.dispatch(database, [], now + timedelta(hours=8), sender)
    assert result["resolved"] == ["provider:platega"] and messages[-1] == "✅ Решено: Касса platega временно отключена"
    assert len(messages) == 3 and messages[0].startswith("⚠️ Касса platega")
    assert not (await database.execute(select(AppSetting).where(AppSetting.key.like("ops_alert:%")))).scalars().all()


@pytest.mark.asyncio
async def test_a_failed_send_is_retried_on_the_next_tick(database):
    async def offline(text):
        return False
    problems = [ops_alerts.Problem("remnawave", "Remnawave недоступен", "x")]
    assert (await ops_alerts.dispatch(database, problems, datetime.utcnow(), offline))["sent"] == []
    assert not (await database.execute(select(AppSetting).where(AppSetting.key == "ops_alert:remnawave"))).scalars().first()


@pytest.mark.asyncio
async def test_alerts_go_to_the_owner_when_no_alert_chat_is_set(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", "123:TEST")
    monkeypatch.setattr(settings, "alert_telegram_chat_id", "")
    monkeypatch.setattr(settings, "admin_telegram_id", 777)
    assert ops_alerts.recipients()["telegram_chat"] == "777"
    monkeypatch.setattr(settings, "alert_telegram_chat_id", "-100500")
    assert ops_alerts.recipients()["telegram_chat"] == "-100500"


@pytest.mark.asyncio
async def test_launch_readiness_lists_what_is_missing(database, monkeypatch):
    for key, value in {"bot_token": "123:TEST", "bot_username": "lusi_bot", "mini_app_url": "https://app.example", "remnawave_url": "https://panel.example",
                       "remnawave_token": "t", "remnawave_webhook_secret": "", "yookassa_shop_id": "1", "yookassa_secret_key": "s",
                       "platega_merchant_id": "", "alert_telegram_chat_id": "", "admin_telegram_id": 0, "alert_email": ""}.items():
        monkeypatch.setattr(settings, key, value)
    out = await ops_alerts.readiness(database, ADMIN)
    checks = {c["key"]: c for c in out["checks"]}
    assert out["agents"] == ["yookassa"] and checks["payments"]["ok"] and checks["plans"]["ok"]
    assert not checks["backup"]["ok"] and "backup.sh" in checks["backup"]["hint"]
    assert not checks["remnawave_webhook"]["ok"] and checks["remnawave_webhook"]["level"] == "recommended"
    assert out["ready"] is False  # no backup yet
    database.add(BackupJob(status="completed", created_at=datetime.utcnow(), finished_at=datetime.utcnow()))
    await database.commit()
    assert (await ops_alerts.readiness(database, ADMIN))["ready"] is True
    for plan in (await database.scalars(select(Plan))).all():
        plan.enabled = False
    await database.commit()
    assert (await ops_alerts.readiness(database, ADMIN))["ready"] is False


def test_recovery_point_objective_of_one_hour():
    """v28.145.0 (owner's decision of 2026-11-14): RPO 1 h, RTO 4 h — an alert when backups cannot meet them."""
    from app.backups_api import BACKUP_INTERVALS
    now = datetime(2026, 11, 14, 12, 0)
    assert ops_alerts.RPO == timedelta(hours=1) and ops_alerts.RTO == timedelta(hours=4)
    assert BACKUP_INTERVALS["1h"] == 3600
    off = ops_alerts.recovery_point("off", None, now, 0)
    assert [k for k, *_ in off] == ["rpo:schedule"] and "«Каждый час»" in off[0][2]
    daily = ops_alerts.recovery_point("24h", now - timedelta(minutes=5), now, 86400)
    assert [k for k, *_ in daily] == ["rpo:schedule"] and "раз в 24 ч" in daily[0][2]
    assert ops_alerts.recovery_point("1h", now - timedelta(minutes=70), now, 3600) == []
    late = ops_alerts.recovery_point("1h", now - timedelta(minutes=90), now, 3600)
    assert [k for k, *_ in late] == ["rpo:late"] and "90 мин назад" in late[0][2]
    assert "ни одной" in ops_alerts.recovery_point("1h", None, now, 3600)[0][2]
