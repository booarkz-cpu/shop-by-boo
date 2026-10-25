"""v28.25.0: Stars subscriptions, partner renewals and gifts, plugin catalog, Remnawave
webhooks, win-back automation, trial guard, family plans, retention and status page."""
import hashlib
import hmac
import json
from base64 import b64encode
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi import HTTPException
from sqlalchemy import func, select
from starlette.requests import Request

from app import app_config, automation, growth, main, partners, plugins, remnawave_events, telegram_stars
from app.config import settings
from app.models import (AutomationExecution, AutomationRule, CancellationFeedback, FamilyGroup, FamilyMember, GiftCode,
                        Notification, PartnerCommission, Payment, Plan, PluginPublisher, PromoCode, RemnawaveEvent, Reseller,
                        StarsSubscription, Subscription, TrialGrant, User)
from test_subscription_commerce import database

ADMIN = SimpleNamespace(email="root@example.test", role="admin")


def req(headers=None, query=b""):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": raw, "query_string": query, "client": ("203.0.113.7", 1)})


async def save(db, data):
    await app_config.admin_app_config_save(app_config.Overrides.model_validate(data), db, ADMIN)


# ---------------------------------------------------------------- Stars subscriptions

@pytest.mark.asyncio
async def test_stars_subscription_first_charge_renewals_and_cancel(database, monkeypatch):
    monkeypatch.setattr(settings, "bot_token", "123:TEST")
    await save(database, {"wallet": {"stars": {"enabled": True, "rate": "2", "subscriptions": True}}})
    user = await database.get(User, 1)
    user.telegram_id = 777
    await database.commit()
    calls, confirmed = [], []

    async def bot_api(method, payload):
        calls.append((method, payload))
        return {"ok": True, "result": "https://t.me/$sub-link"}

    async def allowed(db):
        return True

    async def confirm(payment_id, db):
        confirmed.append(payment_id)
        return {"ok": True}
    monkeypatch.setattr(telegram_stars, "bot_api", bot_api)
    monkeypatch.setattr(main, "production_payments_allowed", allowed)
    monkeypatch.setattr(main, "_confirm_and_fulfill_payment", confirm)

    with pytest.raises(HTTPException) as wrong:
        bad = Plan(name="Год", price=900, duration_days=365, enabled=True)
        database.add(bad); await database.commit()
        await telegram_stars.create_stars_subscription(telegram_stars.SubscriptionIn(plan_id=bad.id), req(), database)
    assert wrong.value.status_code == 409

    out = await telegram_stars.create_stars_subscription(telegram_stars.SubscriptionIn(plan_id=1, subscription_id=1), req(), database)
    assert out["stars"] == 50 and out["period_days"] == 30  # 100 RUB / 2 RUB per Star
    method, payload = calls[-1]
    assert method == "createInvoiceLink" and payload["subscription_period"] == 2592000 and payload["currency"] == "XTR"
    order = out["order_id"]
    assert await telegram_stars.check_pre_checkout(database, order_id=order, currency="XTR", total=50, telegram_id=777) is None

    await telegram_stars.record_successful_payment(database, order_id=order, currency="XTR", total=50, telegram_id=777, charge_id="ch-1",
                                                   period_end=datetime.utcnow() + timedelta(days=30))
    row = await database.scalar(select(StarsSubscription).where(StarsSubscription.order_id == order))
    first = await database.scalar(select(Payment).where(Payment.order_id == order))
    assert row.status == "active" and row.first_charge_id == "ch-1" and first.provider_payment_id == "777:ch-1"
    # Renewal: a new payment fulfilled once, even if Telegram repeats the update.
    await telegram_stars.record_successful_payment(database, order_id=order, currency="XTR", total=50, telegram_id=777, charge_id="ch-2")
    await telegram_stars.record_successful_payment(database, order_id=order, currency="XTR", total=50, telegram_id=777, charge_id="ch-2")
    renewals = (await database.execute(select(Payment).where(Payment.order_id.like(order + ":r%")))).scalars().all()
    assert [p.order_id for p in renewals] == [order + ":r1"] and renewals[0].subscription_id == 1 and renewals[0].duration_days_snapshot == 30
    assert confirmed == [first.id, renewals[0].id, renewals[0].id]
    with pytest.raises(telegram_stars.StarsError):
        await telegram_stars.record_successful_payment(database, order_id=order, currency="XTR", total=49, telegram_id=777, charge_id="ch-3")

    listed = await telegram_stars.my_stars_subscriptions(req(), database)
    assert listed[0]["renewals"] == 1 and listed[0]["status"] == "active"
    done = await telegram_stars.cancel_stars_subscription(row.id, req(), database)
    assert done["status"] == "canceled" and calls[-1] == ("editUserStarSubscription", {"user_id": 777, "telegram_payment_charge_id": "ch-1", "is_canceled": True})


@pytest.mark.asyncio
async def test_stars_subscriptions_need_the_switch(database, monkeypatch):
    monkeypatch.setattr(settings, "bot_token", "123:TEST")
    await save(database, {"wallet": {"stars": {"enabled": True}}})
    with pytest.raises(HTTPException) as off:
        await telegram_stars.create_stars_subscription(telegram_stars.SubscriptionIn(plan_id=1), req(), database)
    assert off.value.status_code == 503


# ---------------------------------------------------------------- partners

@pytest.mark.asyncio
async def test_partner_earns_on_renewals_and_wallet_gifts(database):
    partner = Reseller(name="Partner", slug="pp", api_key_hash="h", owner_user_id=2, commission_percent=Decimal("10"), enabled=True)
    database.add(partner)
    await database.flush()
    database.add(Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="first", amount=100, currency="RUB",
                         status="paid", fulfillment_status="completed", reseller_id=partner.id, reseller_slug_snapshot="pp",
                         reseller_percent_snapshot=Decimal("10"), paid_at=datetime.utcnow()))
    await database.commit()
    terms = await partners.renewal_terms(database, 1)
    assert terms == {"reseller_id": partner.id, "reseller_slug_snapshot": "pp", "reseller_percent_snapshot": Decimal("10.00")} or terms["reseller_id"] == partner.id
    partner.enabled = False
    await database.commit()
    assert await partners.renewal_terms(database, 1) == {}
    partner.enabled = True
    gift = GiftCode(code="GIFT_X", plan_id=1, duration_days=30, max_uses=1, purchaser_user_id=1, purchase_amount=Decimal("200"))
    database.add(gift)
    await database.flush()
    row = await partners.credit_gift(database, gift, {"reseller_id": partner.id, "reseller_percent_snapshot": Decimal("10")})
    assert row.amount == Decimal("20.00") and row.payment_id is None
    assert await partners.credit_gift(database, gift, {"reseller_id": partner.id, "reseller_percent_snapshot": Decimal("10")}) is None
    await database.commit()
    assert (await database.get(Reseller, partner.id)).balance == Decimal("20.00")


# ---------------------------------------------------------------- plugin catalog

def signed_catalog(key, plugins_list):
    pub = b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    body = {"catalog": 1, "name": "Acme", "plugins": plugins_list}
    sig = b64encode(key.sign(plugins.catalog_digest(body))).decode()
    return {**body, "public_key": pub, "signature": sig}, pub


@pytest.mark.asyncio
async def test_plugin_catalog_is_signed_and_installs_the_exact_package(database, monkeypatch):
    key = Ed25519PrivateKey.generate()
    package = b"zip-bytes"
    index, pub = signed_catalog(key, [{"id": "acme-crm", "name": "CRM", "version": "1.2.0", "package_url": "https://cdn.example/acme.zip",
                                       "sha256": hashlib.sha256(package).hexdigest(), "description": "CRM"}])
    database.add(PluginPublisher(name="Acme", public_key=pub, fingerprint=plugins.fingerprint(pub)))
    await database.commit()
    publishers = (await database.scalars(select(PluginPublisher))).all()
    assert plugins.verify_catalog(index, list(publishers)).name == "Acme"
    tampered = {**index, "plugins": [{**index["plugins"][0], "sha256": "0" * 64}]}
    with pytest.raises(plugins.PackageError):
        plugins.verify_catalog(tampered, list(publishers))

    async def fetch(url, limit):
        return json.dumps(index).encode() if url.endswith(".json") else package
    ingested = []

    async def ingest(db, data, admin):
        ingested.append(data)
        return {"id": "acme-crm"}

    def ok_url(url, allow_empty=False):
        return url
    monkeypatch.setattr(plugins, "_fetch", fetch)
    monkeypatch.setattr(plugins, "ingest", ingest)
    monkeypatch.setattr(main, "validate_public_url", ok_url)
    await plugins.save_catalogs(plugins.CatalogsIn(urls=["https://plugins.example/catalog.json"]), database, ADMIN)
    listed = await plugins.catalog(database, ADMIN)
    assert listed["sources"][0]["ok"] and listed["plugins"][0]["id"] == "acme-crm"
    await plugins.catalog_install(plugins.CatalogInstallIn(catalog="https://plugins.example/catalog.json", id="acme-crm", version="1.2.0"), database, ADMIN)
    assert ingested == [package]
    package = b"other"
    with pytest.raises(HTTPException) as mismatch:
        await plugins.catalog_install(plugins.CatalogInstallIn(catalog="https://plugins.example/catalog.json", id="acme-crm", version="1.2.0"), database, ADMIN)
    assert mismatch.value.status_code == 422
    with pytest.raises(HTTPException):
        await plugins.save_catalogs(plugins.CatalogsIn(urls=["http://plain.example/c.json"]), database, ADMIN)


# ---------------------------------------------------------------- Remnawave webhooks

def signed(body: dict, secret="rwsecret"):
    raw = json.dumps(body).encode()
    return raw, hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class WebhookRequest:
    def __init__(self, raw, sig):
        self._raw, self.headers = raw, {"X-Remnawave-Signature": sig}

    async def body(self):
        return self._raw


@pytest.mark.asyncio
async def test_remnawave_webhook_is_verified_deduplicated_and_notifies(database, monkeypatch):
    monkeypatch.setattr(settings, "remnawave_webhook_secret", "rwsecret")
    user = await database.get(User, 1)
    user.telegram_id = 4242
    await database.commit()
    sent = []

    async def sender(chat, text, button="", section=""):
        sent.append((chat, text, button, section))
        return True
    monkeypatch.setattr(remnawave_events, "send_telegram", sender)
    body = {"scope": "user", "event": "user.bandwidth_usage_threshold_reached", "timestamp": "2026-10-25T10:00:00Z",
            "data": {"id": "remote-1", "trafficLimitBytes": 100, "userTraffic": {"usedTrafficBytes": 85}}}
    raw, sig = signed(body)
    with pytest.raises(HTTPException) as bad:
        await remnawave_events.remnawave_webhook(WebhookRequest(raw, "0" * 64), database)
    assert bad.value.status_code == 403
    # notify() captured the sender at import time: patch the default used by the webhook too.
    monkeypatch.setattr(remnawave_events.notify, "__defaults__", (sender,))
    out = await remnawave_events.remnawave_webhook(WebhookRequest(raw, sig), database)
    assert out["notified"] is True and sent[0][0] == 4242 and "85%" in sent[0][1] and sent[0][2] == "Докупить трафик"
    assert (await remnawave_events.remnawave_webhook(WebhookRequest(raw, sig), database))["duplicate"] is True
    event = await database.scalar(select(RemnawaveEvent))
    assert event.user_id == 1 and event.subscription_id == 1
    note = await database.scalar(select(Notification).where(Notification.kind == "remnawave_traffic_threshold"))
    assert note and "85%" in note.body
    # Switched off: stored, not sent.
    await save(database, {"remnawave_notify": {"first_connected": False}})
    raw2, sig2 = signed({"scope": "user", "event": "user.first_connected", "data": {"username": "user_1"}})
    assert (await remnawave_events.remnawave_webhook(WebhookRequest(raw2, sig2), database))["notified"] is False
    # Unsigned when no secret configured.
    monkeypatch.setattr(settings, "remnawave_webhook_secret", "")
    with pytest.raises(HTTPException):
        await remnawave_events.remnawave_webhook(WebhookRequest(raw2, sig2), database)


@pytest.mark.asyncio
async def test_trial_on_a_device_that_already_had_a_trial_is_revoked(database, monkeypatch):
    monkeypatch.setattr(settings, "remnawave_webhook_secret", "rwsecret")
    disabled = []

    class Panel:
        async def disable_user(self, uid):
            disabled.append(uid)
    import app.remnawave as rw_module
    monkeypatch.setattr(rw_module, "RemnawaveClient", Panel)
    now = datetime.utcnow()
    trial_sub = Subscription(user_id=2, plan_id=1, expires_at=now + timedelta(days=3), lifecycle_status="active", remnawave_uuid="remote-2")
    database.add(trial_sub)
    await database.flush()
    database.add_all([TrialGrant(user_id=1, plan_id=1, days=3, expires_at=now - timedelta(days=10), status="completed"),
                      TrialGrant(user_id=2, plan_id=1, days=3, subscription_id=trial_sub.id, expires_at=now + timedelta(days=3), status="completed")])
    await database.commit()
    # The first account already used the device.
    raw0, sig0 = signed({"scope": "user_hwid_devices", "event": "user_hwid_devices.added", "data": {"user": {"id": "remote-1"}, "hwidUserDevice": {"hwid": "HW-1"}}})
    assert (await remnawave_events.remnawave_webhook(WebhookRequest(raw0, sig0), database))["trial_revoked"] is False
    raw, sig = signed({"scope": "user_hwid_devices", "event": "user_hwid_devices.added", "data": {"user": {"id": "remote-2"}, "hwidUserDevice": {"hwid": "HW-1"}}})
    assert (await remnawave_events.remnawave_webhook(WebhookRequest(raw, sig), database))["trial_revoked"] is True
    grant = await database.scalar(select(TrialGrant).where(TrialGrant.user_id == 2))
    sub = await database.get(Subscription, trial_sub.id, populate_existing=True)
    assert grant.status == "revoked" and sub.lifecycle_status == "expired" and disabled == ["remote-2"]


@pytest.mark.asyncio
async def test_trial_guard_limits_per_network_and_can_require_telegram(database):
    user = await database.get(User, 2)
    await save(database, {"trial": {"max_per_ip_per_day": 1, "require_telegram": True}})
    with pytest.raises(HTTPException) as tg:
        await remnawave_events.trial_guard(database, user, "198.51.100.1")
    assert tg.value.status_code == 409
    user.telegram_id = 99
    ip_hash = await remnawave_events.trial_guard(database, user, "198.51.100.1")
    assert len(ip_hash) == 64 and "198.51" not in ip_hash
    database.add(TrialGrant(user_id=1, plan_id=1, days=3, ip_hash=ip_hash))
    await database.commit()
    with pytest.raises(HTTPException) as limited:
        await remnawave_events.trial_guard(database, user, "198.51.100.1")
    assert limited.value.status_code == 429
    assert await remnawave_events.trial_guard(database, user, "198.51.100.2")


# ---------------------------------------------------------------- automation

@pytest.mark.asyncio
async def test_winback_presets_promo_codes_and_remnawave_events(database):
    presets = (await automation.catalog(ADMIN))["presets"]
    assert {p["id"] for p in presets} >= {"winback_expired", "trial_no_purchase", "traffic_upsell"}
    created = await automation.create_preset("winback_expired", database, ADMIN)
    rule = await database.get(AutomationRule, created["id"])
    assert rule.enabled is False and rule.actions["promo_code"] == {"percent": 20, "days": 2}
    with pytest.raises(HTTPException):
        automation.validate_rule("payment.paid", {}, {"promo_code": {"percent": 20}})  # promo needs a notification
    # A Remnawave event triggers its rule once.
    rule2 = AutomationRule(name="up", event="remnawave.traffic_threshold", conditions={"daily_limit": 10},
                           actions={"notify": {"title": "Трафик", "body": "Код {promo}", "telegram": False}, "promo_code": {"percent": 30, "days": 1}},
                           enabled=True, priority=1, created_at=datetime.utcnow() - timedelta(minutes=5))
    database.add(rule2)
    database.add(RemnawaveEvent(event_key="k1", scope="user", event="user.bandwidth_usage_threshold_reached", user_id=1, subscription_id=1))
    await database.commit()
    from sqlalchemy.ext.asyncio import AsyncSession
    factory = lambda: AsyncSession(database.bind, expire_on_commit=False)  # noqa: E731
    assert await automation.run_rule(factory, rule2.id) == 1
    assert await automation.run_rule(factory, rule2.id) == 0
    promo = await database.scalar(select(PromoCode).where(PromoCode.code.like("BACK%")))
    assert promo.usage_limit == 1 and promo.value == Decimal("30.00") and promo.ends_at > datetime.utcnow()
    note = await database.scalar(select(Notification).where(Notification.kind == "automation"))
    assert note.body == f"Код {promo.code}"


@pytest.mark.asyncio
async def test_trial_ended_event_skips_customers_who_paid(database):
    now = datetime.utcnow()
    database.add_all([TrialGrant(user_id=2, plan_id=1, days=3, expires_at=now - timedelta(days=2)),
                      TrialGrant(user_id=1, plan_id=1, days=3, expires_at=now - timedelta(days=2))])
    database.add(Payment(user_id=1, plan_id=1, provider="sandbox", order_id="paid-1", amount=10, currency="RUB", status="paid"))
    rule = AutomationRule(name="t", event="trial.ended", conditions={"days": 1}, actions={"notify": {"title": "a", "body": "b"}},
                          enabled=True, priority=1, created_at=now - timedelta(days=5))
    database.add(rule)
    await database.commit()
    rows = await automation.candidates(database, rule, now)
    assert [r[0] for r in rows] == [2]


# ---------------------------------------------------------------- family

class FakePanel:
    def __init__(self):
        self.created, self.patched, self.disabled, self.enabled = [], [], [], []

    async def create_user(self, username, expire_at, traffic, active_internal_squads=None, telegram_id=None, device_limit=None):
        self.created.append((username, expire_at, device_limit))
        return {"id": f"fam-{len(self.created)}", "subscriptionUrl": "https://sub.example/x"}

    async def patch_user(self, uid, payload):
        self.patched.append((uid, payload))

    async def disable_user(self, uid):
        self.disabled.append(uid)

    async def enable_user(self, uid):
        self.enabled.append(uid)


@pytest.mark.asyncio
async def test_family_invite_join_follow_owner_and_remove(database, monkeypatch):
    panel = FakePanel()
    monkeypatch.setattr(main, "RemnawaveClient", lambda: panel)
    monkeypatch.setattr(settings, "bot_username", "lusi_bot")
    plan = await database.get(Plan, 1)
    plan.family_seats = 1
    await database.commit()
    owner, member, extra = await database.get(User, 1), await database.get(User, 2), User(referral_code="EXTRA")
    database.add(extra)
    await database.commit()
    who = {"user": owner}

    async def current(request, db):
        return who["user"]
    monkeypatch.setattr(main, "user_from_token", current)
    invite = await growth.family_invite(1, req(), database)
    assert invite["bot"].startswith("https://t.me/lusi_bot?start=family_")
    with pytest.raises(HTTPException):
        await growth.family_join(growth.JoinIn(code=invite["code"]), req(), database)  # the owner cannot join
    who["user"] = member
    joined = await growth.family_join(growth.JoinIn(code=invite["code"]), req(), database)
    fm = await database.get(FamilyMember, joined["member_id"])
    owner_sub = await database.get(Subscription, 1)
    msub = await database.get(Subscription, fm.subscription_id, populate_existing=True)
    assert panel.created and panel.created[0][0] == f"user_2_sub_{msub.id}" and msub.expires_at == owner_sub.expires_at
    assert msub.remnawave_uuid == "fam-1" and msub.lifecycle_status == "active"
    who["user"] = extra
    with pytest.raises(HTTPException) as full:
        await growth.family_join(growth.JoinIn(code=invite["code"]), req(), database)
    assert full.value.status_code == 409
    # The owner renews: members follow on the next sync.
    owner_sub.expires_at = owner_sub.expires_at + timedelta(days=30)
    await database.commit()
    assert await growth.sync_member(database, fm.id, panel) == "updated"
    assert panel.patched[-1][0] == "fam-1"
    who["user"] = owner
    view = await growth.my_family(req(), database)
    assert view["owned"][0]["used"] == 1 and view["owned"][0]["members"][0]["synced"]
    await growth.family_remove(fm.id, req(), database)
    assert "fam-1" in panel.disabled
    assert (await database.get(Subscription, fm.subscription_id, populate_existing=True)).lifecycle_status == "expired"


# ---------------------------------------------------------------- retention, status, i18n

@pytest.mark.asyncio
async def test_retention_cohorts_ltv_and_cancel_reasons(database):
    now = datetime.utcnow()
    for i, (uid, amount, days_ago) in enumerate(((1, 100, 40), (1, 100, 10), (2, 200, 20))):
        database.add(Payment(user_id=uid, plan_id=1, provider="sandbox", order_id=f"r{i}", amount=amount, currency="RUB",
                             status="paid", paid_at=now - timedelta(days=days_ago)))
    database.add(CancellationFeedback(user_id=2, reason="price", comment="дорого"))
    await database.commit()
    out = await growth.retention(12, database, ADMIN)
    assert out["customers"] == 2 and out["repeat_rate"] == 50.0 and out["ltv"] == "200.00"
    assert sum(c["customers"] for c in out["cohorts"]) == 2
    assert out["cancel_reasons"][0] == {"reason": "price", "label": "Дорого", "count": 1}


@pytest.mark.asyncio
async def test_cancel_stores_the_survey_answer(database):
    await main.subscription_lifecycle(main.SubscriptionActionIn(action="cancel", reason="speed", comment="медленно"), req(), database)
    row = await database.scalar(select(CancellationFeedback))
    assert row.reason == "speed" and row.comment == "медленно" and row.subscription_id == 1


@pytest.mark.asyncio
async def test_public_status_page_hides_addresses_and_security_incidents(database, monkeypatch):
    from app import tariff_api
    from app.models import SecurityIncidentEvent

    async def servers(scope):
        return {"ok": True, "total": 3, "online": 2, "nodes": [{"name": "a", "country": "DE", "status": "online"},
                {"name": "b", "country": "DE", "status": "offline"}, {"name": "c", "country": "NL", "status": "online"}]}
    monkeypatch.setattr(tariff_api, "remnawave_server_status", servers)
    database.add_all([SecurityIncidentEvent(severity="high", category="service", title="Сбой в Германии"),
                      SecurityIncidentEvent(severity="critical", category="auth", title="Подбор паролей")])
    await database.commit()
    from app.models import StatusComponent
    database.add(StatusComponent(slug="api", name="API", status="operational", enabled=True))
    await database.commit()
    out = await growth.public_status(database)
    assert out["components"] == [{"name": "API", "status": "operational", "message": out["components"][0]["message"]}]
    assert out["status"] == "degraded" and out["countries"][0] == {"country": "DE", "total": 2, "online": 1}
    assert [i["title"] for i in out["incidents"]] == ["Сбой в Германии"]
    assert "address" not in json.dumps(out, default=str)


@pytest.mark.asyncio
async def test_app_config_speaks_english_and_ukrainian(database):
    en = await app_config.build_config(database, req(query=b"lang=en"))
    uk = await app_config.build_config(database, req(query=b"lang=uk"))
    ru = await app_config.build_config(database, req())
    assert en["lang"] == "en" and en["texts"]["wallet_pay"] == "Top up" and uk["texts"]["wallet_pay"] == "Поповнити"
    assert ru["texts"]["wallet_pay"] == "Пополнить" and en["version"] != ru["version"]
    assert any(n["kind"] == "info" and n["title"] == "Information" for n in en["navigation"])
