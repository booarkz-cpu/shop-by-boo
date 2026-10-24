"""GET /api/app-config, admin overrides, offer consent and Telegram Stars top-ups."""
import hashlib
import hmac
import json
import time
import urllib.parse
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app import app_config, main, telegram_stars
from app.config import settings
from app.models import AppSetting, AuditLog, Payment, Promotion, User, UserConsent
from test_subscription_commerce import database

ADMIN = SimpleNamespace(email="root@example.test", role="admin")


class Req:
    def __init__(self, headers=None):
        self.headers = headers or {}


def init_data(user, token="123:TEST"):
    fields = {"auth_date": str(int(time.time())), "user": json.dumps(user), "query_id": "q"}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


@pytest.fixture(autouse=True)
def no_providers(monkeypatch):
    async def public_config(db):
        return {"app_name": "Corgi VPN", "payment_providers": ["yookassa", "platega"], "trial_days": 3}
    monkeypatch.setattr(main, "public_config", public_config)
    monkeypatch.setattr(settings, "bot_username", "corgi_bot")


@pytest.mark.asyncio
async def test_default_config_describes_every_screen(database, monkeypatch):
    monkeypatch.setattr(settings, "bot_token", "123:TEST")
    database.add(Promotion(name="Осень", kind="percent", value=Decimal("20"), plan_ids=None, enabled=True, description="Скидка на все тарифы"))
    await database.commit()
    viewer = Req({"X-Telegram-Init-Data": init_data({"id": 77, "first_name": "Артём", "language_code": "ru"})})
    cfg = await app_config.build_config(database, viewer)
    assert cfg["viewer"] == {"first_name": "Артём", "username": "", "language": "ru"}
    assert cfg["theme"]["vars"]["--cfg-accent"] == "#39ff88"
    assert cfg["texts"]["wallet_title"] == "Пополнение баланса"
    kinds = {n["kind"]: n for n in cfg["navigation"]}
    assert kinds["overview"]["icon"] == "home" and kinds["overview"]["banner"] == "/api/bot/banners/default/home.jpg"
    assert kinds["info"]["banner"].endswith("/info.jpg")
    assert cfg["banners"]["wallet"].endswith("/topup.jpg")
    promo = next(p for p in cfg["promos"] if p["id"].startswith("promotion-"))
    assert promo["discount"] == "-20%" and promo["link"] == "#plans"
    methods = [m["id"] for m in cfg["wallet"]["methods"]]
    assert methods[:2] == ["yookassa", "platega"] and all(m["available"] for m in cfg["wallet"]["methods"])
    assert cfg["wallet"]["stars"]["enabled"] is False
    assert cfg["referral"]["link_template"] == "https://t.me/corgi_bot?start=ref_{code}"
    assert cfg["support"]["buttons"][0]["link"].startswith("https://t.me/corgi_bot")
    assert cfg["consent"]["enabled"] is False and len(cfg["version"]) == 16
    # A forged initData gives no viewer.
    assert (await app_config.build_config(database, Req({"X-Telegram-Init-Data": "user=%7B%7D&hash=00"})))["viewer"] is None


def test_overrides_are_validated():
    for bad in ({"theme": {"accent": "red"}}, {"texts": {"unknown_key": "x"}}, {"wallet": {"amounts": [10]}},
                {"support": {"buttons": [{"title": "x", "link": "javascript:alert(1)"}]}},
                {"servers": {"categories": [{"id": "eu", "title": "Европа", "countries": ["Germany"]}]}},
                {"wallet": {"methods": [{"id": "x", "title": "X", "provider": "paypal"}]}}, {"extra": 1}):
        with pytest.raises(ValidationError):
            app_config.Overrides.model_validate(bad)
    ok = app_config.Overrides.model_validate({"servers": {"categories": [{"id": "eu", "title": "Европа", "countries": ["de", "NL"], "icon": "flag"}]},
                                             "wallet": {"amounts": [500, 100, 500]}})
    assert ok.servers.categories[0].countries == ["DE", "NL"] and ok.wallet.amounts == [100, 500]


@pytest.mark.asyncio
async def test_admin_saves_resets_and_broken_values_fall_back(database, monkeypatch):
    monkeypatch.setattr(settings, "bot_token", "123:TEST")
    payload = app_config.Overrides.model_validate({
        "theme": {"accent": "#00ff99"}, "texts": {"greeting": "Хей, {name}!"},
        "wallet": {"methods": [{"id": "sbp", "title": "СБП", "icon": "sbp", "provider": "yookassa", "yookassa_method": "sbp"}],
                   "stars": {"enabled": True, "rate": "1.8", "min_stars": 10}},
        "support": {"buttons": [{"title": "Чат", "icon": "send", "link": "https://t.me/support_corgi"}]},
        "consent": {"enabled": True, "version": "2026-10"}})
    saved = (await app_config.admin_app_config_save(payload, database, ADMIN))["config"]
    assert saved["theme"]["vars"]["--cfg-accent"] == "#00ff99" and saved["texts"]["greeting"] == "Хей, {name}!"
    assert [m["id"] for m in saved["wallet"]["methods"]] == ["sbp", "stars"] and saved["wallet"]["stars"]["rate"] == "1.8"
    assert saved["support"]["buttons"] == [{"title": "Чат", "icon": "send", "link": "https://t.me/support_corgi"}]
    admin_view = await app_config.admin_app_config(database, ADMIN)
    assert admin_view["overrides"]["consent"]["version"] == "2026-10" and "home" in admin_view["icons"]
    row = await database.get(AppSetting, "app_config")
    row.value = "{broken"
    await database.commit()
    assert (await app_config.load_overrides(database)).consent.enabled is False
    await app_config.admin_app_config_reset(database, ADMIN)
    assert (await app_config.build_config(database))["theme"]["vars"]["--cfg-accent"] == "#39ff88"


@pytest.mark.asyncio
async def test_consent_blocks_payment_until_accepted(database, monkeypatch):
    await app_config.admin_app_config_save(app_config.Overrides.model_validate({"consent": {"enabled": True, "version": "v1"}}), database, ADMIN)
    user = await database.get(User, 1)

    async def who(request, db):
        return user
    monkeypatch.setattr(main, "user_from_token", who)
    with pytest.raises(HTTPException) as blocked:
        await app_config.require_consent(database, user)
    assert blocked.value.status_code == 409 and blocked.value.detail["code"] == "consent_required"
    assert (await app_config.my_consent(Req(), database))["accepted"] is False
    with pytest.raises(HTTPException):
        await app_config.accept_consent(app_config.ConsentIn(version="old"), Req(), database)
    await app_config.accept_consent(app_config.ConsentIn(version="v1"), Req(), database)
    await app_config.accept_consent(app_config.ConsentIn(version="v1"), Req(), database)  # idempotent
    await app_config.require_consent(database, user)
    assert (await database.scalar(select(UserConsent).where(UserConsent.user_id == 1))).version == "v1"
    assert len((await database.execute(select(UserConsent))).scalars().all()) == 1
    # A new offer version asks again.
    await app_config.admin_app_config_save(app_config.Overrides.model_validate({"consent": {"enabled": True, "version": "v2"}}), database, ADMIN)
    with pytest.raises(HTTPException):
        await app_config.require_consent(database, user)
    assert "customer.consent.accepted" in {a for (a,) in (await database.execute(select(AuditLog.action))).all()}


@pytest.mark.asyncio
async def test_stars_invoice_checkout_and_wallet_credit(database, monkeypatch):
    monkeypatch.setattr(settings, "bot_token", "123:TEST")
    await app_config.admin_app_config_save(app_config.Overrides.model_validate({"wallet": {"stars": {"enabled": True, "rate": "1.5", "min_stars": 10}}}), database, ADMIN)
    user = await database.get(User, 1)
    user.telegram_id = 555
    await database.commit()
    calls = []

    async def bot_api(method, payload):
        calls.append((method, payload))
        return {"ok": True, "result": "https://t.me/$invoice-link"}

    async def who(request, db):
        return user

    async def allowed(db):
        return True

    async def channel(user):
        return None
    confirmed = []

    async def confirm(payment_id, db):
        confirmed.append(payment_id)
        return {"ok": True}
    monkeypatch.setattr(telegram_stars, "bot_api", bot_api)
    monkeypatch.setattr(main, "user_from_token", who)
    monkeypatch.setattr(main, "production_payments_allowed", allowed)
    monkeypatch.setattr(main, "ensure_required_channel", channel)
    monkeypatch.setattr(main, "_confirm_and_fulfill_payment", confirm)

    out = await telegram_stars.stars_invoice(telegram_stars.InvoiceIn(amount=Decimal("100")), Req({"Idempotency-Key": "k1"}), database)
    assert out["stars"] == 67 and out["url"] == "https://t.me/$invoice-link"  # 100 / 1.5 rounded up
    method, payload = calls[0]
    assert method == "createInvoiceLink" and payload["currency"] == "XTR" and payload["prices"] == [{"label": "Пополнение", "amount": 67}]
    again = await telegram_stars.stars_invoice(telegram_stars.InvoiceIn(amount=Decimal("100")), Req({"Idempotency-Key": "k1"}), database)
    assert again["order_id"] == out["order_id"] and len(calls) == 1

    order = out["order_id"]
    assert await telegram_stars.check_pre_checkout(database, order_id=order, currency="XTR", total=67, telegram_id=555) is None
    assert await telegram_stars.check_pre_checkout(database, order_id=order, currency="XTR", total=1, telegram_id=555)
    assert await telegram_stars.check_pre_checkout(database, order_id=order, currency="XTR", total=67, telegram_id=999)
    assert await telegram_stars.check_pre_checkout(database, order_id="topup-1-x", currency="XTR", total=67, telegram_id=555)
    with pytest.raises(telegram_stars.StarsError):
        await telegram_stars.record_successful_payment(database, order_id=order, currency="XTR", total=5, telegram_id=555, charge_id="ch1")
    await telegram_stars.record_successful_payment(database, order_id=order, currency="XTR", total=67, telegram_id=555, charge_id="ch1")
    payment = await database.scalar(select(Payment).where(Payment.order_id == order))
    assert payment.provider_payment_id == "555:ch1" and payment.purpose == "topup" and payment.stars_amount == 67
    assert confirmed == [payment.id]
    with pytest.raises(telegram_stars.StarsError):
        await telegram_stars.record_successful_payment(database, order_id=order, currency="XTR", total=67, telegram_id=555, charge_id="other")

    refunds = []

    async def refund_api(method, payload):
        refunds.append((method, payload))
        if len(refunds) > 1:
            raise telegram_stars.StarsError("Bad Request: CHARGE_ALREADY_REFUNDED")
        return {"ok": True, "result": True}
    monkeypatch.setattr(telegram_stars, "bot_api", refund_api)
    provider = telegram_stars.TelegramStarsProvider()
    assert (await provider.refund("555:ch1"))["status"] == "succeeded"
    assert (await provider.refund("555:ch1"))["status"] == "succeeded"
    assert refunds[0] == ("refundStarPayment", {"user_id": 555, "telegram_payment_charge_id": "ch1"})


@pytest.mark.asyncio
async def test_stars_are_off_by_default(database, monkeypatch):
    with pytest.raises(HTTPException) as off:
        await telegram_stars.stars_invoice(telegram_stars.InvoiceIn(amount=Decimal("100")), Req({"Idempotency-Key": "k"}), database)
    assert off.value.status_code == 503


@pytest.mark.asyncio
async def test_yookassa_receives_the_selected_method(monkeypatch):
    from app.payments import YooKassaProvider
    seen = {}

    async def create_payment(self, amount, currency, description, metadata):
        seen.update(metadata)
        return {"id": "p1", "confirmation": {"confirmation_url": "https://pay"}, "status": "pending"}
    monkeypatch.setattr(YooKassaProvider, "create_payment", create_payment)
    await YooKassaProvider().create(Decimal("100"), "o1", "Wallet top-up", "https://app", method="sbp")
    assert seen["payment_method_type"] == "sbp"


@pytest.mark.asyncio
async def test_public_endpoint_revalidates_with_etag(database):
    from fastapi import Response
    first = Response()
    body = await app_config.app_config(Req(), first, database)
    etag = first.headers["etag"]
    assert first.headers["cache-control"] == "private, no-cache" and body["version"] in etag
    again = await app_config.app_config(Req({"If-None-Match": etag}), Response(), database)
    assert again.status_code == 304
