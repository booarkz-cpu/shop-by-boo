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


def test_certificates_of_the_shop_domains(monkeypatch):
    """v28.146.0 (REQ-INFRA-0027, 0038): a certificate that Caddy did not renew is reported before it expires."""
    monkeypatch.setattr(settings, "api_domain", "api.shop.example")
    monkeypatch.setattr(settings, "admin_domain", "localhost")
    monkeypatch.setattr(settings, "public_base_url", "https://shop.example")
    monkeypatch.setattr(settings, "mini_app_url", "https://203.0.113.5/app")
    assert ops_alerts.shop_hosts()[:2] == ["api.shop.example", "shop.example"] and "localhost" not in ops_alerts.shop_hosts()
    found = {p.key: p for p in ops_alerts.certificate_problems({"a.example": 60, "b.example": 10, "c.example": 2, "d.example": -1, "e.example": None})}
    assert set(found) == {"cert:b.example", "cert:c.example", "cert:d.example"}
    assert found["cert:b.example"].severity == "medium" and "Осталось дней: 10" in found["cert:b.example"].detail
    assert found["cert:c.example"].severity == "critical" and found["cert:d.example"].title == "Сертификат d.example истёк"


@pytest.mark.asyncio
async def test_certificates_are_asked_at_most_every_six_hours(monkeypatch):
    asked = []

    def read(host):
        asked.append(host)
        return 5

    monkeypatch.setattr(ops_alerts, "shop_hosts", lambda: ["shop.example"])
    monkeypatch.setattr(ops_alerts, "_CERT_CACHE", {"at": None, "days": {}})
    now = datetime(2026, 11, 14, 12, 0)
    first = await ops_alerts.certificate_check(now, read)
    await ops_alerts.certificate_check(now + timedelta(hours=5), read)
    await ops_alerts.certificate_check(now + timedelta(hours=6), read)
    assert [p.key for p in first] == ["cert:shop.example"] and asked == ["shop.example", "shop.example"]


def test_json_logs_carry_the_request_id(capsys):
    import json
    import logging

    from app import log_format
    from app.main import _REQUEST_ID

    assert log_format.install("text") is False
    handler = logging.StreamHandler()
    handler.setFormatter(log_format.JsonFormatter())
    log = logging.getLogger("test.json")
    log.addHandler(handler)
    log.propagate = False
    token = _REQUEST_ID.set("req-12345678")
    try:
        log.warning("оплата %s", 7)
    finally:
        _REQUEST_ID.reset(token)
        log.removeHandler(handler)
    line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert line["message"] == "оплата 7" and line["request_id"] == "req-12345678" and line["level"] == "WARNING"


def test_a_drifting_server_clock_is_reported():
    """v28.147.0 (REQ-INFRA-0028): a minute of drift breaks webhook signatures and sign-in codes quietly."""
    from email.utils import format_datetime
    from datetime import timezone as tz

    assert ops_alerts.clock_problems(None) == [] and ops_alerts.clock_problems(12.0) == []
    ahead = ops_alerts.clock_problems(95.0)[0]
    assert ahead.key == "clock" and "спешат на 95 с" in ahead.detail and ahead.severity == "medium"
    assert ops_alerts.clock_problems(-400)[0].severity == "critical" and "отстают" in ops_alerts.clock_problems(-400)[0].detail
    behind = format_datetime((datetime.utcnow() - timedelta(minutes=10)).replace(tzinfo=tz.utc), usegmt=True)
    assert 590 <= ops_alerts.clock_drift(lambda: behind) <= 610
    assert ops_alerts.clock_drift(lambda: "not a date") is None


@pytest.mark.asyncio
async def test_hourly_backups_by_default_and_the_installers_password(database, monkeypatch):
    """v28.148.0 (owner's decision of 2026-11-14): an installation backs up every hour from the start. The password the
    installer generated (BACKUP_PASSWORD) becomes the panel's once; without any password nothing fails every minute —
    one alert says what to do."""
    from app import backups_api
    from app.backups_api import setting_value

    assert backups_api.DEFAULT_SCHEDULE == "1h" and backups_api.DEFAULT_RETENTION == "48"
    assert backups_api.BackupConfigIn().schedule == "1h" and backups_api.BackupConfigIn().retention == 48
    monkeypatch.setattr(settings, "backup_password_env", "")
    assert await backups_api.backup_blocked(database) == "password"
    found = {p.key: p for p in await ops_alerts.recovery_point_problems(database, datetime.utcnow())}
    assert list(found) == ["rpo:password"] and "задайте пароль" in found["rpo:password"].detail
    monkeypatch.setattr(settings, "backup_password_env", "installer-made-0123456789")
    assert await backups_api.seed_backup_password(database) is True
    assert await setting_value(database, "backup_password", "") and await backups_api.backup_blocked(database) is None
    assert await backups_api.seed_backup_password(database) is False          # the panel's password is never replaced
    keys = [p.key for p in await ops_alerts.recovery_point_problems(database, datetime.utcnow())]
    assert keys == ["rpo:late"]                                                 # hourly, but no copy yet
