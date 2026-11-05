"""Stage 18 (docs/ru/new/ADMIN_VERIFICATION.md): changing admin routes of «Ноды» (platform modules, agents, API keys,
webhooks, mail, DKIM, device blacklist, torrent threshold), «Пользователи», «Remnawave», «Мониторинг», «Обновления»
and «Интеграции». Every security-relevant platform change leaves an audit record (v28.78.0)."""
import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select

from app import admin_api, admin_customer_operations, client_versions, geoip, notifications_status_api, operations_api
from app import ops_alerts, platform_api, remnawave_shop_api, ripe_atlas, rw_autoupdate, torrent_detection, v6_api
from app import vpn_sessions, webhook_tee
from app import main as shop
from app.models import (AgentAction, AppSetting, AuditLog, Deployment, DeviceBlacklist, NodeAgent, OutboundWebhook,
                        PayoutTransaction, PlatformPlugin, ShopApiKey, WithdrawalRequest)
from app.security import decrypt_secret, encrypt_secret
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(id=1, email="owner@corgi.test", role="admin")


async def actions(db, prefix):
    return list((await db.execute(select(AuditLog.action).where(AuditLog.action.like(prefix + "%")).order_by(AuditLog.id))).scalars())


@pytest.mark.asyncio
async def test_platform_modules_agents_keys_and_webhooks_are_audited(database, monkeypatch):
    db = database
    checked = shop.validate_public_url

    def offline(url, allow_empty=False):  # no DNS in CI: a public name passes, literal private addresses are still refused
        return None if "hooks.example.com" in url else checked(url, allow_empty=allow_empty)
    monkeypatch.setattr(shop, "validate_public_url", offline)
    with pytest.raises(HTTPException) as err:
        await platform_api.toggle_plugin("nope", {"enabled": False}, db, ADMIN)
    assert err.value.status_code == 404
    db.add(PlatformPlugin(key="agent", enabled=True))
    await db.commit()
    assert (await platform_api.toggle_plugin("agent", {"enabled": False}, db, ADMIN))["enabled"] is False
    with pytest.raises(HTTPException) as err:  # a disabled module refuses its actions
        await platform_api.create_agent({"name": "nl-1"}, db, ADMIN)
    assert err.value.status_code == 503
    await platform_api.toggle_plugin("agent", {"enabled": True}, db, ADMIN)
    with pytest.raises(HTTPException):
        await platform_api.create_agent({"name": "  "}, db, ADMIN)
    agent = await platform_api.create_agent({"name": "nl-1"}, db, ADMIN)
    stored = await db.get(NodeAgent, agent["id"])
    assert len(agent["token"]) > 30 and stored.token_hash != agent["token"], "only the hash is kept"

    key = await platform_api.create_api_key(platform_api.ApiKeyIn(name="crm", scopes="read"), db, ADMIN)
    row = await db.get(ShopApiKey, key["id"])
    assert key["token"].startswith("rw_") and row.prefix == key["prefix"] and row.secret_hash != key["token"]
    assert await platform_api.disable_api_key(key["id"], db, ADMIN) == {"ok": True}
    await db.refresh(row)
    assert row.enabled is False
    with pytest.raises(HTTPException) as err:
        await platform_api.disable_api_key(999, db, ADMIN)
    assert err.value.status_code == 404

    with pytest.raises(HTTPException):  # no webhooks into the private network
        await platform_api.create_webhook(platform_api.WebhookIn(url="http://127.0.0.1:8080/hook"), db, ADMIN)
    hook = await platform_api.create_webhook(platform_api.WebhookIn(url="https://hooks.example.com/corgi", events="abuse.scored"), db, ADMIN)
    saved = await db.get(OutboundWebhook, hook["id"])
    assert decrypt_secret(saved.secret_encrypted) == hook["secret"]

    await platform_api.add_blacklist(platform_api.BlacklistIn(hwid="HWID-12345678", action="alert"), db, ADMIN)
    await platform_api.add_blacklist(platform_api.BlacklistIn(hwid="HWID-12345678", action="block", note="sharing"), db, ADMIN)
    [device] = (await db.execute(select(DeviceBlacklist))).scalars().all()
    assert device.action == "block" and device.note == "sharing", "the same device is updated, not duplicated"

    assert await torrent_detection.admin_torrents_threshold(torrent_detection.ThresholdIn(min_events=25), db, ADMIN) == {"min_events": 25}
    assert (await db.get(AppSetting, torrent_detection.THRESHOLD_KEY)).value == "25"
    with pytest.raises(ValueError):
        torrent_detection.ThresholdIn(min_events=0)
    assert await actions(db, "platform.") == [
        "platform.plugin.toggled", "platform.plugin.toggled", "platform.agent.created", "platform.api_key.created",
        "platform.api_key.disabled", "platform.webhook.created", "platform.blacklist.added", "platform.blacklist.added",
        "platform.torrents.threshold"]


class FakeSmtp:
    sent: list = []
    refuse = False

    def __init__(self, host, port, timeout):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        FakeSmtp.sent.append(("login", user, password))

    def send_message(self, message):
        if FakeSmtp.refuse:
            raise OSError("550 relay denied")
        FakeSmtp.sent.append(("to", message["To"]))


@pytest.mark.asyncio
async def test_mail_settings_test_letter_and_dkim(database, monkeypatch):
    db = database
    monkeypatch.setattr(platform_api.smtplib, "SMTP", FakeSmtp)
    FakeSmtp.sent = []
    with pytest.raises(HTTPException) as err:
        await platform_api.test_mail(db, ADMIN)
    assert err.value.status_code == 400
    await platform_api.save_mail(platform_api.MailIn(host="smtp.example.com", username="shop", password="smtp-secret", sender="shop@example.com"), db, ADMIN)
    cfg = json.loads((await db.get(AppSetting, "smtp_settings")).value)
    assert cfg["password"] != "smtp-secret" and decrypt_secret(cfg["password"]) == "smtp-secret"
    await platform_api.save_mail(platform_api.MailIn(host="smtp2.example.com", username="shop", sender="shop@example.com"), db, ADMIN)
    cfg = json.loads((await db.get(AppSetting, "smtp_settings")).value)
    assert cfg["host"] == "smtp2.example.com" and decrypt_secret(cfg["password"]) == "smtp-secret", "an empty password keeps the saved one"
    assert await platform_api.test_mail(db, ADMIN) == {"ok": True, "to": "owner@corgi.test"}
    assert FakeSmtp.sent == [("login", "shop", "smtp-secret"), ("to", "owner@corgi.test")], "the letter goes only to the admin who pressed"
    FakeSmtp.refuse = True
    try:
        with pytest.raises(HTTPException) as err:
            await platform_api.test_mail(db, ADMIN)
        assert err.value.status_code == 502 and "550" not in err.value.detail
    finally:
        FakeSmtp.refuse = False

    with pytest.raises(HTTPException):
        await platform_api.create_dkim({"domain": "localhost"}, db, ADMIN)
    out = await platform_api.create_dkim({"selector": "corgi", "domain": "example.com"}, db, ADMIN)
    assert out["txt"].startswith('corgi._domainkey.example.com IN TXT "v=DKIM1; k=rsa; p=')
    stored = json.loads((await db.get(AppSetting, "dkim_private")).value)
    assert "PRIVATE KEY" in decrypt_secret(stored["private"]) and "PRIVATE KEY" not in (await db.get(AppSetting, "dkim_private")).value
    assert await actions(db, "platform.") == ["platform.mail.saved", "platform.mail.saved", "platform.dkim.created"]


@pytest.mark.asyncio
async def test_orchestrator_and_provision_intents(database):
    db = database
    db.add_all([NodeAgent(name="silent", token_hash="h1"), NodeAgent(name="fresh", token_hash="h2", last_seen_at=datetime.utcnow(), xray_ok=True)])
    await db.commit()
    out = await v6_api.orchestrate(db, ADMIN)
    assert out["actions"] == [{"agent": "silent", "action": "drain", "status": "pending_approval"}], "approval is on by default"
    assert (await v6_api.orchestrate(db, ADMIN))["actions"] == [], "the pending drain is not queued twice"
    assert len((await db.execute(select(AgentAction))).scalars().all()) == 1
    intent = await v6_api.provision(v6_api.ProvisionIn(region="nl", name="nl-2"), db, ADMIN)
    assert intent["status"] == "planned" and intent["dry_run"] is True
    real = await v6_api.provision(v6_api.ProvisionIn(region="de", name="de-1", dry_run=False), db, ADMIN)
    assert real["status"] == "pending_provider_credentials", "no node is ordered without provider credentials"
    assert await actions(db, "event:node.provision") == ["event:node.provision.requested"] * 2


class FakeRw:
    extended: list = []

    async def list_users(self, start, size):
        return {"users": [{"id": 17}]}

    async def list_nodes(self, start, size):
        return {"nodes": []}

    async def get_user(self, user_id):
        return {"expireAt": "2026-12-01T00:00:00Z"} if user_id != "no-date" else {}

    async def extend_idempotent(self, user_id, days, before, after):
        FakeRw.extended.append((user_id, days, before, after))
        return {"already_applied": False, "expires_at": after.isoformat()}

    async def _request(self, method, path, json=None):
        FakeRw.extended.append((method, path, json))


@pytest.mark.asyncio
async def test_remnawave_connection_mapping_extend_and_drop(database, monkeypatch):
    db = database
    monkeypatch.setattr(remnawave_shop_api.settings, "remnawave_url", "")
    with pytest.raises(HTTPException) as err:
        await remnawave_shop_api.remnawave_shop_test(ADMIN)
    assert err.value.status_code == 503
    monkeypatch.setattr(remnawave_shop_api.settings, "remnawave_url", "https://panel.example.com")
    monkeypatch.setattr(remnawave_shop_api.settings, "remnawave_token", "token")
    monkeypatch.setattr(remnawave_shop_api, "RemnawaveClient", FakeRw)
    out = await remnawave_shop_api.remnawave_shop_test(ADMIN)
    assert out["ok"] and out["api_generation"] == "3.x" and out["sample_user_id_type"] == "int"

    mapping = await remnawave_shop_api.validate_plan_mapping(ADMIN, db)
    assert mapping["ok"] is False and mapping["missing_profile_mapping"] == [1, 2]

    FakeRw.extended = []
    monkeypatch.setattr(shop, "RemnawaveClient", FakeRw)
    with pytest.raises(HTTPException):
        await admin_api.rw_extend("17", {"days": 0}, db, ADMIN)
    with pytest.raises(HTTPException) as err:
        await admin_api.rw_extend("17;drop", {"days": 30}, db, ADMIN)
    assert err.value.status_code == 400
    with pytest.raises(HTTPException) as err:
        await admin_api.rw_extend("no-date", {"days": 30}, db, ADMIN)
    assert err.value.status_code == 409
    done = await admin_api.rw_extend("17", {"days": 30}, db, ADMIN)
    assert done["ok"] and FakeRw.extended[-1][:2] == ("17", 30)
    assert FakeRw.extended[-1][3] - FakeRw.extended[-1][2] == timedelta(days=30)

    from app import remnawave
    monkeypatch.setattr(remnawave, "RemnawaveClient", FakeRw)
    assert await vpn_sessions.drop_connections(1, db, ADMIN) == {"ok": True, "dropped": True}
    assert FakeRw.extended[-1] == ("POST", "/api/connections/drop",
                                   {"dropBy": {"by": "userUuids", "userUuids": ["remote-1"]}, "targetNodes": {"target": "allNodes"}})
    with pytest.raises(HTTPException) as err:  # a customer without a panel subscription
        await vpn_sessions.drop_connections(2, db, ADMIN)
    assert err.value.status_code == 404
    assert await actions(db, "remnawave.user.extend") == ["remnawave.user.extend"]
    assert await actions(db, "user.connections.dropped") == ["user.connections.dropped"]


@pytest.mark.asyncio
async def test_updates_monitoring_and_integrations(database, monkeypatch):
    db = database

    async def upstream():
        return {"panel": "2.3.1", "node": "2.3.0"}

    async def overview(db_, with_panel=True):
        return {"releases": (await rw_autoupdate._load(db_, rw_autoupdate.STATE_KEY, {}))["releases"]}
    monkeypatch.setattr(rw_autoupdate, "fetch_upstream", upstream)
    monkeypatch.setattr(rw_autoupdate, "overview", overview)
    assert (await rw_autoupdate.check_releases(db, ADMIN))["releases"] == {"panel": "2.3.1", "node": "2.3.0"}

    db.add_all([Deployment(version="28.78.0", status="canary", traffic_percent=10), Deployment(version="28.77.1", status="completed")])
    await db.commit()
    canary, done = (await db.execute(select(Deployment).order_by(Deployment.id))).scalars().all()
    assert (await notifications_status_api.deployment_rollback(canary.id, {"reason": "errors 5%"}, db, ADMIN))["status"] == "rolled_back"
    await db.refresh(canary)
    assert canary.traffic_percent == 0 and canary.rollback_reason == "errors 5%"
    with pytest.raises(HTTPException) as err:
        await notifications_status_api.deployment_rollback(done.id, None, db, ADMIN)
    assert err.value.status_code == 409

    monkeypatch.setattr(ops_alerts, "recipients", lambda: {"telegram": [], "email": []})
    with pytest.raises(HTTPException) as err:
        await ops_alerts.summary_send_now(db, ADMIN)
    assert err.value.status_code == 409
    sent = []

    async def send(text):
        sent.append(text)
        return True

    async def summary(db_):
        return {"week": 1}
    monkeypatch.setattr(ops_alerts, "recipients", lambda: {"telegram": ["1"], "email": []})
    monkeypatch.setattr(ops_alerts, "send", send)
    monkeypatch.setattr(ops_alerts, "weekly_summary", summary)
    monkeypatch.setattr(ops_alerts, "summary_text", lambda data: f"Неделя {data['week']}")
    assert await ops_alerts.summary_send_now(db, ADMIN) == {"ok": True} and sent == ["Неделя 1"]

    async def tee_config(db_):
        return {"targets": [{"name": "crm", "url": "https://crm.example.com/hook", "secret": encrypt_secret("s3cret")},
                            {"name": "off", "url": "https://off.example.com/hook", "enabled": False}]}
    posted = []

    async def tee_send(url, raw, secret, headers):
        posted.append((url, json.loads(raw)["event"], secret))
        return True
    monkeypatch.setattr(webhook_tee, "_config", tee_config)
    monkeypatch.setattr(webhook_tee, "_send", tee_send)
    assert (await webhook_tee.test_tee(db, ADMIN))["results"] == [{"name": "crm", "ok": True}, {"name": "off", "ok": None}]
    assert posted == [("https://crm.example.com/hook", "shop.test", "s3cret")], "signed with the target's secret"

    with pytest.raises(HTTPException) as err:
        await geoip.update_geoip(db, ADMIN)
    assert err.value.status_code == 409
    with pytest.raises(HTTPException) as err:
        await ripe_atlas.run_ripe(db, ADMIN)
    assert err.value.status_code == 409

    from app.node_health import _save

    await _save(db, ripe_atlas.CONFIG_KEY, {**ripe_atlas.DEFAULT, "api_key": "atlas-key"})
    await db.commit()

    async def start(db_, cfg):
        assert cfg["api_key"] == "atlas-key"
        return {"items": [1, 2, 3]}
    monkeypatch.setattr(ripe_atlas, "start", start)
    assert await ripe_atlas.run_ripe(db, ADMIN) == {"ok": True, "targets": 3}

    async def refuse(db_, cfg):
        raise ValueError("RIPE Atlas: not enough credits")
    monkeypatch.setattr(ripe_atlas, "start", refuse)
    with pytest.raises(HTTPException) as err:
        await ripe_atlas.run_ripe(db, ADMIN)
    assert err.value.status_code == 502


@pytest.mark.asyncio
async def test_client_versions_refresh_and_import_inspect(database, monkeypatch, tmp_path):
    db = database

    async def latest(client, repo):
        return {"hiddify/hiddify-app": "2.5.7"}.get(repo, "")
    monkeypatch.setattr(client_versions, "latest_release", latest)
    out = await client_versions.refresh_clients(db, ADMIN)
    hiddify = [c for c in out["clients"] if c.get("repo") == "hiddify/hiddify-app"]
    assert out["updated"] >= (1 if hiddify else 0)
    if hiddify:
        assert hiddify[0]["latest"] == "2.5.7" and hiddify[0]["checked_at"]

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE users(id INTEGER, telegram_id INTEGER, username TEXT, balance TEXT)")
        con.execute("INSERT INTO users VALUES (7, 9001, 'New', '12.34')")
    result = await admin_customer_operations.inspect(UploadFile(file=io.BytesIO(path.read_bytes()), filename="old.db"), "users", ADMIN)
    assert result["columns"] == ["id", "telegram_id", "username", "balance"] and result["currency"] == shop.settings.default_currency
    with pytest.raises(HTTPException):
        await admin_customer_operations.inspect(UploadFile(file=io.BytesIO(b"not sqlite"), filename="x.db"), "users", ADMIN)


@pytest.mark.asyncio
async def test_referral_withdrawal_approve_then_paid(database):
    db = database
    if db.bind.dialect.name != "postgresql":
        pytest.skip("SELECT … FOR UPDATE: PostgreSQL only (runs in CI)")
    w = WithdrawalRequest(user_id=1, amount=Decimal("150.00"), destination="card ****4417")
    db.add(w)
    await db.commit()
    with pytest.raises(HTTPException) as err:  # not approved yet
        await operations_api.admin_withdrawal_paid(w.id, shop.WithdrawalActionIn(), db, ADMIN)
    assert err.value.status_code == 404
    assert await operations_api.admin_withdrawal_approve(w.id, shop.WithdrawalActionIn(note="ok"), db, ADMIN) == {"ok": True, "status": "approved"}
    with pytest.raises(HTTPException) as err:
        await operations_api.admin_withdrawal_approve(w.id, shop.WithdrawalActionIn(), db, ADMIN)
    assert err.value.status_code == 409
    assert (await operations_api.admin_withdrawal_paid(w.id, shop.WithdrawalActionIn(note="sent"), db, ADMIN))["status"] == "paid"
    payout = (await db.execute(select(PayoutTransaction).where(PayoutTransaction.withdrawal_id == w.id))).scalar_one()
    assert payout.status == "paid" and payout.paid_at and payout.amount == Decimal("150.00")
    assert await actions(db, "referral.withdrawal.") == ["referral.withdrawal.approved", "referral.withdrawal.paid"]
