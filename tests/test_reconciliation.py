"""v28.37 modules carried over from the comparison snapshots (docs/ru/SNAPSHOT_RECONCILIATION.md):
moderation, required channels, panel guard, error log, activity, smart cart, grace access, gift batches, ad conversions,
referral contests, e-mail templates, guest purchase, daily plans, auto-replies, connection quality, churn, upsell,
P&L, reseller orders, mobile admin cards."""
import json
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app import main as shop
from app.models import Payment, Plan, Subscription, User
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test")
NOW = datetime(2026, 10, 28, 12, 0)


def req(headers=(), path="/x"):
    return Request({"type": "http", "method": "POST", "path": path, "headers": list(headers), "client": ("10.0.0.9", 1), "query_string": b""})


@pytest.fixture
def env(database, monkeypatch):  # noqa: F811
    from app import db as dbmod
    async def quiet(*a, **k):
        return None
    sent = []

    async def notify(chat, text):
        sent.append((chat, text))
    monkeypatch.setattr(shop, "audit", quiet)
    monkeypatch.setattr(shop, "notify_user_telegram", notify)
    monkeypatch.setattr(dbmod, "SessionLocal", lambda: AsyncSession(database.bind, expire_on_commit=False))
    return SimpleNamespace(db=database, sent=sent)


# ------------------------------------------------------------------ moderation

@pytest.mark.asyncio
async def test_moderation_blacklist_disposable_invites_and_ban(env):
    from app import moderation as m
    db = env.db
    assert m.disposable("a@mailinator.com") and m.disposable("x@sub.yopmail.com") and not m.disposable("me@gmail.com")
    with pytest.raises(HTTPException):
        await m.registration_check(db, email="spam@tempmail.com")
    await m.put_blacklist(m.ListIn(telegram_ids=[555000], domains=["evil.test"]), db, ADMIN)
    for kwargs in ({"telegram_id": 555000}, {"email": "x@mail.evil.test"}):
        with pytest.raises(HTTPException):
            await m.registration_check(db, **kwargs)
    await m.registration_check(db, telegram_id=777000)  # allowed
    await m.put_moderation(m.ConfigIn(block_disposable=True, invite_only=True), db, ADMIN)
    with pytest.raises(HTTPException):
        await m.registration_check(db, telegram_id=777001)
    invite = await m.create_invite(m.InviteIn(note="друзья", max_uses=1, days=7), db, ADMIN)
    assert m.invite_from_start(f"ref_ABC__inv_{invite['code']}") == invite["code"]
    await m.registration_check(db, telegram_id=777002, invite=invite["code"])
    with pytest.raises(HTTPException):
        await m.registration_check(db, telegram_id=777003, invite=invite["code"]), "one use only"
    # Bulk ban: a known customer is restricted, an unknown id joins the black list.
    owner = await db.get(User, 1)
    owner.telegram_id = 1234567
    await db.commit()
    result = await m.bulk_ban(m.BanIn(text="1234567\n9876543, junk"), db, ADMIN)
    assert result == {"ids": 2, "customers": 1, "blacklisted": 1}
    assert (await db.get(User, 1)).restricted_at is not None
    assert (await m.bulk_ban(m.BanIn(text="1234567", unban=True), db, ADMIN))["customers"] == 1
    view = await m.get_moderation(db, ADMIN)
    assert view["blacklist"]["telegram_ids"] == 2 and view["invites"][0]["uses"] == 1


@pytest.mark.asyncio
async def test_blocked_scan_and_cleanup(env):
    from app import moderation as m
    db = env.db
    db.add(User(id=10, telegram_id=1010101, referral_code="BLK1", created_at=NOW - timedelta(days=200)))
    db.add(User(id=11, telegram_id=1111111, referral_code="BLK2"))
    owner = await db.get(User, 1)
    owner.telegram_id = 2020202
    await db.commit()

    def handler(request):
        chat = int(json.loads(request.content)["chat_id"])
        if chat == 1010101:
            return httpx.Response(403, json={"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"})
        return httpx.Response(200, json={"ok": True, "result": True})
    shop.settings.bot_token = shop.settings.bot_token or "1:test"
    from app import db as dbmod
    result = await m.scan_blocked(dbmod.SessionLocal, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), pause=0)
    assert result["blocked"] == [1010101]
    assert await m.cleanup_candidates(db) == [10]
    assert (await m.blocked_cleanup(db, ADMIN))["closed"] == 1
    assert (await db.get(User, 10)).deleted_at is not None


# ------------------------------------------------------------------ channels, guard, errors, activity

@pytest.mark.asyncio
async def test_channel_gate_scopes(env, monkeypatch):
    from app import channel_gate as cg
    channels = [{"chat": "@corginews", "title": "Новости", "url": "https://t.me/news", "scope": "buy"},
                {"chat": "@corgimain", "title": "Главный", "url": "https://t.me/all", "scope": "all"}]
    members = {("@corgimain", 5)}

    async def is_member(tid, chat, client=None):
        return (chat, tid) in members
    monkeypatch.setattr(cg, "is_member", is_member)
    assert [c["chat"] for c in await cg.missing(5, "trial", channels)] == []
    assert [c["chat"] for c in await cg.missing(5, "buy", channels)] == ["@corginews"]
    assert len(await cg.missing(None, "buy", channels)) == 2
    await cg.put_gate(cg.GateIn(channels=[cg.ChannelIn(**c) for c in channels]), env.db, ADMIN)
    assert len(await cg.load(env.db)) >= 2


@pytest.mark.asyncio
async def test_panel_guard_turns_maintenance_on_and_off(env):
    from app import panel_guard as pg
    from app.backups_api import set_setting, setting_value
    db = env.db
    alerts = []

    async def sender(text):
        alerts.append(text)
    await pg.put_guard(pg.GuardIn(enabled=True, fail_after=2, recover_after=1), db, ADMIN)
    await pg.tick(db, False, NOW, sender)
    assert await setting_value(db, "maintenance_mode", "0") == "0"
    await pg.tick(db, False, NOW, sender)
    assert await setting_value(db, "maintenance_mode", "0") == "1" and "техработы" in alerts[-1]
    await pg.tick(db, True, NOW, sender)
    assert await setting_value(db, "maintenance_mode", "0") == "0"
    # Maintenance switched on by hand is never lifted by the guard.
    await set_setting(db, "maintenance_mode", "1")
    await db.commit()
    for ok in (False, False, True, True):
        await pg.tick(db, ok, NOW, sender)
    assert await setting_value(db, "maintenance_mode", "0") == "1"


@pytest.mark.asyncio
async def test_error_log_groups_and_redacts(env):
    from app import error_log as el
    db = env.db
    item = {"level": "ERROR", "logger": "vpnshop.pay", "message": el.redact("token=abcdef123456 failed for order 42"), "traceback": "",
            "process": "api", "at": NOW}
    assert "abcdef" not in item["message"]
    await el.store(db, [item, {**item, "message": el.redact("token=zzzzzz999 failed for order 43"), "at": NOW + timedelta(minutes=1)}])
    data = await el.list_errors(False, db, ADMIN)
    assert data["open"] == 1 and data["items"][0]["count"] == 2
    await el.resolve_all(db, ADMIN)
    assert (await el.list_errors(False, db, ADMIN))["open"] == 0


@pytest.mark.asyncio
async def test_activity_timeline_merges_sources(env):
    from app import activity_log as al
    db = env.db
    al.record(db, 1, "bot", "start")
    db.add(Payment(user_id=1, plan_id=1, provider="yookassa", order_id="tl-1", amount=Decimal("100"), currency="RUB", status="paid",
                   fulfillment_status="completed", purpose="subscription", paid_at=datetime.utcnow()))
    await db.commit()
    await al.my_activity(al.ActivityIn(surface="android", action="connect"), req(), db)
    with pytest.raises(HTTPException):
        await al.my_activity(al.ActivityIn(surface="android", action="hack"), req(), db)
    actions = [e["action"] for e in (await al.user_activity(1, db, ADMIN))["items"]]
    assert {"start", "connect", "payment.created", "payment.paid"} <= set(actions)


# ------------------------------------------------------------------ money

@pytest.mark.asyncio
async def test_smart_cart_buys_after_topup(env, monkeypatch):
    from app import customer_api, smart_cart
    db = env.db
    owner = await db.get(User, 1)
    owner.wallet_balance = Decimal("40")
    await db.commit()
    bought = []

    async def spend(session, user, payload, key):
        bought.append((user.id, payload, key))
        user.wallet_balance -= Decimal("100")
        return {"ok": True, "payment_id": 99}
    monkeypatch.setattr(customer_api, "spend_from_wallet", spend)
    out = await smart_cart.put_cart({"plan_id": 1, "evil": 1}, req(), db)
    assert out == {"bought": False, "topup": "60.00", "amount": "100.00"}
    assert (await smart_cart.get_cart(req(), db))["cart"]["payload"] == {"plan_id": 1}
    assert await smart_cart.buy_cart(db, 1) is None  # still not enough
    owner = await db.get(User, 1)
    owner.wallet_balance = Decimal("120")
    await db.commit()
    assert (await smart_cart.buy_cart(db, 1))["payment_id"] == 99
    assert bought[0][2].startswith("cart-1-") and (await smart_cart.get_cart(req(), db))["cart"] is None
    assert any("корзин" in text for _, text in env.sent)


@pytest.mark.asyncio
async def test_grace_access_once_per_cooldown(env):
    from app import grace_access as ga
    db = env.db
    sub = await db.get(Subscription, 1)
    sub.expires_at = NOW + timedelta(minutes=5)
    await db.commit()
    patched = []

    class Panel:
        async def patch_user(self, uuid, body):
            patched.append(body)
    await ga.put_grace(ga.GraceIn(enabled=True, hours=12, cooldown_days=30, reset_traffic_on_payment=True), db, ADMIN)
    assert await ga.reset_traffic_on_payment(db)
    granted = await ga.tick(db, NOW, Panel(), lambda *a: _none())
    assert granted == [1] and patched[0]["expireAt"].startswith("2026-10-29T00:05")
    sub = await db.get(Subscription, 1)
    assert sub.lifecycle_status == "grace" and sub.grace_until == NOW + timedelta(minutes=5, hours=12)
    sub.lifecycle_status, sub.grace_until, sub.expires_at = "active", None, NOW + timedelta(days=10, minutes=5)
    await db.commit()
    assert await ga.tick(db, NOW + timedelta(days=10), Panel(), lambda *a: _none()) == [], "cooldown"


async def _none():
    return None


@pytest.mark.asyncio
async def test_gift_batches_and_csv(env):
    from app import gift_batches as gb
    db = env.db
    out = await gb.create_batch(gb.BatchIn(plan_id=1, count=5, tag="FEST", valid_days=10), db, ADMIN)
    assert out["count"] == 5 and all(c.startswith("GIFT_FEST_") for c in out["codes"])
    listed = (await gb.list_batches(db, ADMIN))["batches"]
    assert listed[0]["tag"] == "FEST" and listed[0]["count"] == 5
    csv = (await gb.export_batch("FEST", db, ADMIN)).body.decode()
    assert len(csv.strip().splitlines()) == 6 and "bot_link" in csv
    assert (await gb.disable_batch("FEST", db, ADMIN))["disabled"] == 5


@pytest.mark.asyncio
async def test_ad_conversions(env):
    from app import ad_postbacks as ap
    db = env.db
    assert ap.click_from_start("ref_X__cid_abc123") == "abc123"
    await ap.remember_click(db, 1, "abc123", "1234567890123")
    await db.commit()
    await ap.put_postbacks(ap.PostbacksIn(enabled=True, urls={"purchase": "https://tracker.test/pb?cid={click_id}&sum={amount}"},
                                          metrika_counter="123456", metrika_secret="sec"), db, ADMIN)
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url), request.content.decode()))
        return httpx.Response(200)
    sent = await ap.send_event(1, "purchase", amount="299.00", order_id="o-1", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert sent == ["postback purchase", "metrika purchase"]
    assert calls[0][1] == "https://tracker.test/pb?cid=abc123&sum=299.00"
    assert "cid=1234567890123" in calls[1][2] and "ev=299.00" in calls[1][2] and "ms=sec" in calls[1][2]
    assert (await ap.get_postbacks(db, ADMIN))["metrika_secret"] == "***"


@pytest.mark.asyncio
async def test_referral_contest_awards_once(env):
    from app import referral_contests as rc
    db = env.db
    start = datetime.utcnow() - timedelta(days=1)
    for uid, ref in ((20, 1), (21, 1), (22, 2)):
        db.add(User(id=uid, referral_code=f"R{uid}", referred_by_id=ref))
        db.add(Payment(user_id=uid, plan_id=1, provider="yookassa", order_id=f"c-{uid}", amount=Decimal("100"), currency="RUB",
                       status="paid", fulfillment_status="completed", purpose="subscription", paid_at=datetime.utcnow()))
    await db.commit()
    created = await rc.create_contest(rc.ContestIn(title="Октябрь", starts_at=start, ends_at=datetime.utcnow() + timedelta(hours=1),
                                                   prizes=[rc.PrizeIn(place=1, days=30), rc.PrizeIn(place=2, amount=Decimal("50"))]), db, ADMIN)
    mine = (await rc.my_contest(req(), db))["contest"]
    assert mine["me"] == {"place": 1, "score": 2} and mine["top"][1]["score"] == 1
    from app.models import ReferralContest
    later = datetime.utcnow() + timedelta(hours=2)
    assert await rc.finish_due(db, later) == [created["id"]]
    assert await rc.finish_due(db, later) == []
    from app.models import Job
    jobs = [j.job_key for j in (await db.execute(select(Job))).scalars()]
    fresh = await db.get(ReferralContest, created["id"])
    await db.refresh(fresh)
    assert f"bonus_days:contest:{created['id']}:1" in jobs, (jobs, fresh.results, fresh.prizes, fresh.status)
    assert (await db.get(User, 2)).wallet_balance == Decimal("50.00")


# ------------------------------------------------------------------ account and plans

@pytest.mark.asyncio
async def test_email_templates_render(env):
    from app import email_templates as et
    db = env.db
    subject, body = et.render("password_reset", "https://x/#r", "30 минут")
    assert subject == "Восстановление пароля" and "https://x/#r" in body
    with pytest.raises(HTTPException):
        await et.put_template("guest_setup", et.TemplateIn(subject="Привет", body="без ссылки"), db, ADMIN)
    await et.put_template("guest_setup", et.TemplateIn(subject="Подписка {shop}", body="Пароль: {link} ({hours})"), db, ADMIN)
    subject, body = et.render("guest_setup", "https://x/#g", "24 часа")
    assert subject.startswith("Подписка ") and body == "Пароль: https://x/#g (24 часа)"


@pytest.mark.asyncio
async def test_guest_checkout(env, monkeypatch):
    from app import guest_checkout as gc
    from starlette.responses import Response
    db = env.db

    async def session(db_, user, request):
        return "session-token"
    monkeypatch.setattr(shop, "create_user_session", session)
    with pytest.raises(HTTPException):
        await gc.guest_start(gc.GuestIn(email="new@buyer.test", consent=True), req(), Response(), db)  # off
    await gc.put_guest({"enabled": True}, db, ADMIN)
    with pytest.raises(HTTPException):
        await gc.guest_start(gc.GuestIn(email="new@buyer.test", consent=False), req(), Response(), db)
    with pytest.raises(HTTPException):
        await gc.guest_start(gc.GuestIn(email="new@yopmail.com", consent=True), req(), Response(), db)
    out = await gc.guest_start(gc.GuestIn(email="new@buyer.test", consent=True), req(), Response(), db)
    assert (await db.get(User, out["id"])).email == "new@buyer.test"
    with pytest.raises(HTTPException):
        await gc.guest_start(gc.GuestIn(email="new@buyer.test", consent=True), req(), Response(), db)


@pytest.mark.asyncio
async def test_daily_plans_renew_from_wallet(env, monkeypatch):
    from app import customer_api, daily_billing as dbl
    db = env.db
    db.add(Plan(id=5, name="Сутки", price=10, duration_days=1))
    sub = await db.get(Subscription, 1)
    sub.plan_id, sub.expires_at = 5, NOW + timedelta(minutes=30)
    owner = await db.get(User, 1)
    owner.auto_renew_enabled, owner.wallet_balance = True, Decimal("15")
    await db.commit()
    spent = []

    async def spend(session, user, payload, key):
        spent.append(key)
        return {"ok": True}
    monkeypatch.setattr(customer_api, "spend_from_wallet", spend)
    texts = []

    async def notify(chat, text):
        texts.append(text)
    assert (await dbl.tick(db, NOW, notify))["renewed"] == [], "off by default"
    await dbl.put_daily({"enabled": True}, db, ADMIN)
    assert (await dbl.tick(db, NOW, notify))["renewed"] == [1] and spent == [f"daily-1-{(NOW + timedelta(minutes=30)).date()}"]
    owner = await db.get(User, 1)
    owner.wallet_balance = Decimal("5")
    await db.commit()
    assert (await dbl.tick(db, NOW, notify))["short"] == [1]
    assert (await dbl.tick(db, NOW, notify))["short"] == [], "one reminder a day"


@pytest.mark.asyncio
async def test_autoreply_answers_only_clear_questions(env, monkeypatch):
    from app import support_ai, support_autoreply as sa
    from app.models import SupportMessage, SupportTicket
    db = env.db

    async def faq(session):
        return [{"question": "Как подключить VPN на iPhone?", "answer": "Откройте приложение, нажмите «Подключить» на iPhone."}]
    monkeypatch.setattr(support_ai, "faq", faq)
    db.add_all([SupportTicket(id=1, user_id=1, subject="iPhone", message="Как подключить vpn на iphone приложение"),
                SupportTicket(id=2, user_id=1, subject="Деньги", message="Верните деньги, списали дважды за подключение iphone"),
                SupportTicket(id=3, user_id=1, subject="Вопрос", message="Сколько стоит?")])
    await db.commit()
    assert await sa.maybe_reply(db, 1) is None, "off by default"
    await sa.put_autoreply(sa.AutoreplyIn(enabled=True, min_score=3), db, ADMIN)
    assert "Автоответ" in await sa.maybe_reply(db, 1)
    assert await sa.maybe_reply(db, 2) is None, "refunds wait for a person"
    assert await sa.maybe_reply(db, 3) is None, "unclear questions wait for a person"
    assert await db.scalar(select(SupportMessage).where(SupportMessage.ticket_id == 1))


@pytest.mark.asyncio
async def test_connection_quality_flags_carrier_blocks(env):
    from app import connection_quality as cq
    db = env.db
    for i in range(12):
        await cq.report(cq.ReportIn(platform="android", carrier="MTS", network="cellular", country="ru", results=[
            cq.ResultIn(server="de.corgi.test:443", ok=i < 3, ms=50), cq.ResultIn(server="fi.corgi.test:443", ok=True, ms=80 + i)]), req(), db)
    flagged = (await cq.admin_quality(db, ADMIN))["flagged"]
    assert [(c["carrier"], c["server"]) for c in flagged] == [("MTS", "de.corgi.test:443")]
    assert (await cq.recommended("MTS", "cellular", db))["server"] == "fi.corgi.test:443"
    assert len(await cq.problems(db)) == 1


@pytest.mark.asyncio
async def test_churn_scores_and_offers_once(env):
    from app import churn as ch
    db = env.db
    sub = await db.get(Subscription, 1)
    sub.expires_at = datetime.utcnow() + timedelta(days=2)
    db.add(Payment(user_id=1, plan_id=1, provider="yookassa", order_id="ch-1", amount=Decimal("100"), currency="RUB", status="paid",
                   fulfillment_status="completed", purpose="subscription", paid_at=datetime.utcnow() - timedelta(days=28)))
    await db.commit()
    rows = await ch.score_all(db)
    assert rows[0]["user_id"] == 1 and rows[0]["score"] >= 65 and len(rows[0]["reasons"]) >= 3
    code = (await ch.offer(1, db, ADMIN))["code"]
    assert code.startswith("STAY-")
    with pytest.raises(HTTPException):
        await ch.offer(1, db, ADMIN)


@pytest.mark.asyncio
async def test_stats_and_upsell(env):
    from app import customer_insights as ci
    db = env.db

    class Panel:
        async def get_user(self, uuid):
            return {"userTraffic": {"usedTrafficBytes": 95 * 1024 ** 3, "lifetimeUsedTrafficBytes": 500 * 1024 ** 3}, "trafficLimitBytes": 100 * 1024 ** 3}
    user = await db.get(User, 1)
    stats = await ci.stats(db, user, Panel())
    assert stats["traffic_used_gb"] == 95.0 and stats["traffic_limit_gb"] == 100.0
    offers = await ci.upsell(db, user, Panel())
    assert offers[0]["kind"] == "traffic" and offers[0]["quote"] == {"kind": "traffic_addon", "package_id": 1, "subscription_id": 1}


@pytest.mark.asyncio
async def test_pnl_and_reseller_orders(env, monkeypatch):
    from app import pnl, reseller_orders as ro
    from app.models import Reseller
    db = env.db
    month = datetime.utcnow().strftime("%Y-%m")
    db.add(Payment(user_id=1, plan_id=1, provider="yookassa", order_id="pnl-1", amount=Decimal("1000"), currency="RUB", status="paid",
                   fulfillment_status="completed", purpose="subscription", paid_at=datetime.utcnow()))
    await db.commit()
    await pnl.put_fees({"yookassa": 3.5, "bogus": 50}, db, ADMIN)
    await pnl.add_cost(pnl.CostIn(month=month, category="servers", vendor="Hetzner", node="de-1", amount=Decimal("300")), db, ADMIN)
    report = await pnl.report(db, 1)
    last = report["months"][-1]
    assert last["revenue"] == "1000.00" and last["fees"] == "35.00" and last["profit"] == "665.00"
    assert report["nodes"][0]["node"] == "de-1"
    # Reseller orders: wholesale from the balance, idempotent.
    assert ro.wholesale(Decimal("200"), Decimal("20")) == Decimal("160.00")
    reseller = Reseller(name="Partner", slug="partner", api_key_hash="h", balance=Decimal("100"), commission_percent=Decimal("20"))
    db.add(reseller)
    await db.commit()
    from app import marketplace_api

    async def who(request, session):
        return await session.get(Reseller, reseller.id)
    monkeypatch.setattr(marketplace_api, "_reseller_from_request", who)
    fulfilled = []

    async def fulfill(payment_id, session, existing_user_lock_token=None):
        fulfilled.append(payment_id)
    monkeypatch.setattr(shop, "fulfill", fulfill)
    out = await ro.create_order(ro.OrderIn(plan_id=1, customer_ref="tg:42"), req([(b"idempotency-key", b"o1")]), db)
    assert out["amount"] == "80.00" and fulfilled
    again = await ro.create_order(ro.OrderIn(plan_id=1, customer_ref="tg:42"), req([(b"idempotency-key", b"o1")]), db)
    assert again["order_id"] == out["order_id"] and len(fulfilled) == 1
    assert (await db.get(Reseller, reseller.id)).balance == Decimal("20.00")
    with pytest.raises(HTTPException):
        await ro.create_order(ro.OrderIn(plan_id=1, customer_ref="tg:43"), req([(b"idempotency-key", b"o2")]), db)


@pytest.mark.asyncio
async def test_mobile_cards_cover_new_modules(env):
    from app import mobile_panels
    out = await mobile_panels.mobile_panels(env.db, ADMIN)
    ids = [p["id"] for p in out["panels"]]
    for needed in ("moderation", "access_guard", "errors", "growth", "connection_quality", "churn", "pnl"):
        assert needed in ids
    assert not [p for p in out["panels"] if p["rows"] and p["rows"][0]["label"] == "Ошибка"], [p for p in out["panels"] if p["rows"][0]["label"] == "Ошибка"]
