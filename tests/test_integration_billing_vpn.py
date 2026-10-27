"""Billing ↔ VPN integration: trial and Premium payment through the real worker, the real
Remnawave HTTP client and an in-memory Remnawave panel (httpx.MockTransport), including lost
answers and timeouts; the app gets back to itself after paying; the bot, the cabinet and the apps
read one and the same subscription.

Unlike the unit tests with a FakeRW object, here every panel call goes through
RemnawaveClient._request: URLs, JSON bodies, the {"response": …} envelope and HTTP errors."""
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

import worker
from app import app_login, bot
from app import main as shop
from app.models import Job, Payment, Subscription, TrialGrant, User
from app.remnawave import RemnawaveClient
from test_subscription_commerce import database  # noqa: F401


class Panel:
    """Remnawave users API in memory. ``lose`` makes the next matching call succeed on the panel
    but time out for the shop (the answer is lost); ``unreachable`` fails every call before it arrives."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.lose: set[str] = set()
        self.unreachable = False

    def transport(self):
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        route = f"{method} {path}"
        if self.unreachable:
            raise httpx.ConnectError("panel unreachable", request=request)
        answer = self.route(method, path, json.loads(request.content) if request.content else {})
        for marker in list(self.lose):
            if marker in route:
                self.lose.discard(marker)
                raise httpx.ReadTimeout("answer lost", request=request)
        return answer

    @staticmethod
    def ok(body):
        return httpx.Response(200, json={"response": body})

    def route(self, method, path, body):
        parts = path.strip("/").split("/")  # api users …
        if method == "GET" and parts[:3] == ["api", "users", "by-username"]:
            user = next((u for u in self.users.values() if u["username"] == parts[3]), None)
            return self.ok(user) if user else httpx.Response(404, json={"message": "User not found"})
        if method == "POST" and parts == ["api", "users"]:
            uid = str(uuid.uuid4())
            self.users[uid] = {"uuid": uid, "id": uid, "username": body["username"], "expireAt": body["expireAt"], "status": "ACTIVE",
                               "trafficLimitBytes": body.get("trafficLimitBytes", 0), "activeInternalSquads": body.get("activeInternalSquads", []),
                               "subscriptionUrl": f"https://sub.corgi.test/{uid[:8]}"}
            return self.ok(self.users[uid])
        if method == "PATCH" and parts == ["api", "users"]:
            user = self.users[body["id"]]
            user.update({k: v for k, v in body.items() if k != "id"})
            return self.ok(user)
        if method == "GET" and parts[:3] == ["api", "subscriptions", "by-id"] and parts[3] in self.users:
            user = self.users[parts[3]]
            return self.ok({"subscriptionUrl": user["subscriptionUrl"], "user": user})
        if len(parts) >= 3 and parts[:2] == ["api", "users"] and parts[2] in self.users:
            user = self.users[parts[2]]
            if method == "GET" and len(parts) == 3:
                return self.ok(user)
            if method == "POST" and parts[3:] == ["actions", "extend"]:
                current = datetime.fromisoformat(user["expireAt"].replace("Z", "+00:00")).replace(tzinfo=None)
                user["expireAt"] = (max(current, datetime.utcnow()) + timedelta(days=body["days"])).isoformat()
                return self.ok(user)
            if method == "POST" and parts[3:] == ["actions", "enable"]:
                user["status"] = "ACTIVE"
                return self.ok(user)
        return httpx.Response(404, json={"message": f"no route {method} {path}"})

    def count(self, method, suffix):
        return sum(1 for m, p in self.calls if m == method and p.endswith(suffix))


@pytest.fixture
def panel(monkeypatch):
    p = Panel()
    from app.config import settings

    monkeypatch.setattr(settings, "remnawave_url", "https://panel.corgi.test")
    monkeypatch.setattr(settings, "remnawave_token", "panel-token")
    monkeypatch.setattr(RemnawaveClient, "_shared_client", httpx.AsyncClient(transport=p.transport()))
    yield p
    monkeypatch.setattr(RemnawaveClient, "_shared_client", None)


@pytest.fixture
def customer(database, monkeypatch):
    """Customer 2 of the commerce fixture (no subscription yet), signed in from the Android app."""
    async def signed_in(request, session):
        return await session.get(User, 2)
    monkeypatch.setattr(shop, "user_from_token", signed_in)
    monkeypatch.setattr(shop, "engine", database.bind)
    monkeypatch.setattr(shop, "redis_client", None)
    return database


def app_request(path="/api/me/trial", ip="10.9.8.7"):
    return Request({"type": "http", "method": "POST", "path": path, "client": (ip, 1), "query_string": b"",
                    "headers": [(b"x-shop-client", b"android-user"), (b"user-agent", b"CorgiLusi-Android-User/3.1.0")]})


async def give_trial(db):
    user = await db.get(User, 2)
    user.telegram_id = 222
    await db.commit()
    return await shop.claim_trial(shop.TrialIn(plan_id=1, days=3), app_request(), db)


# ------------------------------------------------------------------------------- trial

@pytest.mark.asyncio
async def test_trial_is_issued_once_through_the_worker_and_the_panel(customer, panel):
    db = customer
    answer = await give_trial(db)
    assert answer["status"] == "queued" and answer["days"] == 3
    with pytest.raises(HTTPException) as again:
        await shop.claim_trial(shop.TrialIn(plan_id=1, days=3), app_request(), db)
    assert again.value.status_code == 409, "one trial per customer"
    assert await worker.run_next_job("test-worker") is True
    assert await worker.run_next_job("test-worker") is False, "nothing left"
    assert panel.count("POST", "/api/users") == 1 and len(panel.users) == 1
    remote = next(iter(panel.users.values()))
    sub = (await db.execute(select(Subscription).where(Subscription.user_id == 2).execution_options(populate_existing=True))).scalar_one()
    assert (sub.remnawave_uuid, sub.lifecycle_status, sub.subscription_url) == (remote["uuid"], "active", remote["subscriptionUrl"])
    assert timedelta(days=2, hours=23) < sub.expires_at - datetime.utcnow() <= timedelta(days=3)
    job = (await db.execute(select(Job).execution_options(populate_existing=True))).scalar_one()
    trial = (await db.execute(select(TrialGrant).execution_options(populate_existing=True))).scalar_one()
    assert (job.status, job.attempts, trial.status) == ("completed", 1, "completed")


@pytest.mark.asyncio
async def test_a_lost_panel_answer_is_retried_with_backoff_and_never_creates_twice(customer, panel):
    db = customer
    await give_trial(db)
    panel.lose.add("POST /api/users")  # the panel creates the user, the shop never hears back
    await worker.run_next_job("test-worker")
    job = (await db.execute(select(Job).execution_options(populate_existing=True))).scalar_one()
    assert (job.status, job.attempts) == ("queued", 1) and "answer lost" in job.error
    assert job.next_retry_at > datetime.utcnow() + timedelta(seconds=50), "backoff before the next attempt"
    assert await worker.run_next_job("test-worker") is False, "not before the backoff"
    job.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
    await db.commit()
    await worker.run_next_job("test-worker")
    assert len(panel.users) == 1 and panel.count("POST", "/api/users") == 1, "the retry finds the user by name"
    sub = (await db.execute(select(Subscription).where(Subscription.user_id == 2).execution_options(populate_existing=True))).scalar_one()
    assert sub.remnawave_uuid == next(iter(panel.users)) and sub.lifecycle_status == "active"


@pytest.mark.asyncio
async def test_an_unreachable_panel_fails_the_job_after_its_attempts(customer, panel):
    db = customer
    await give_trial(db)
    job = (await db.execute(select(Job))).scalar_one()
    job.max_attempts = 2
    await db.commit()
    panel.unreachable = True
    for _ in range(2):
        await worker.run_next_job("test-worker")
        job = (await db.execute(select(Job).execution_options(populate_existing=True))).scalar_one()
        job.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        await db.commit()
    assert job.status == "failed" and job.attempts == 2
    assert panel.users == {}


@pytest.mark.asyncio
async def test_a_deleted_customer_gets_no_trial_and_the_job_ends(customer, panel):
    db = customer
    await give_trial(db)
    (await db.get(User, 2)).deleted_at = datetime.utcnow()
    await db.commit()
    await worker.run_next_job("test-worker")
    job = (await db.execute(select(Job).execution_options(populate_existing=True))).scalar_one()
    trial = (await db.execute(select(TrialGrant).execution_options(populate_existing=True))).scalar_one()
    assert (job.status, trial.status) == ("completed", "cancelled"), "it used to stay «processing» forever"
    assert panel.calls == []


# ----------------------------------------------------------------------------- premium

async def premium(db, panel, order="premium-1"):
    remote = str(uuid.uuid4())
    panel.users[remote] = {"uuid": remote, "id": remote, "username": "corgi_1", "status": "ACTIVE",
                           "expireAt": (datetime.utcnow() + timedelta(days=15)).isoformat(), "subscriptionUrl": "https://sub.corgi.test/one"}
    sub = await db.get(Subscription, 1)
    sub.remnawave_uuid = remote
    sub.expires_at = datetime.fromisoformat(panel.users[remote]["expireAt"])
    p = Payment(user_id=1, subscription_id=1, plan_id=2, provider="yookassa", order_id=order, provider_payment_id="yk-" + order,
                amount=Decimal("200"), currency="RUB", status="paid", fulfillment_status="pending", purpose="subscription",
                duration_days_snapshot=30, traffic_limit_gb_snapshot=200, device_limit_snapshot=4, remnawave_profile_id_snapshot="squad-plus",
                idempotency_key="idem-" + order, paid_at=datetime.utcnow())
    db.add(p)
    await db.commit()
    return p, remote, sub.expires_at


@pytest.mark.asyncio
async def test_premium_payment_extends_the_panel_user_exactly_once(database, panel, monkeypatch):
    monkeypatch.setattr(shop, "redis_client", object())

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(shop, "notify_user_telegram", quiet)
    p, remote, before = await premium(database, panel)
    await shop.fulfill(p.id, database)
    assert p.fulfillment_status == "completed"
    assert panel.count("POST", "/actions/extend") == 1
    user = panel.users[remote]
    assert user["trafficLimitBytes"] == 200 * 1024 ** 3 and user["activeInternalSquads"] == ["squad-plus"], "the plan's entitlements reach the panel"
    sub = await database.get(Subscription, 1)
    assert timedelta(days=29, hours=23) < sub.expires_at - before <= timedelta(days=30, minutes=1)
    for _ in range(3):
        await shop.fulfill(p.id, database)
    assert panel.count("POST", "/actions/extend") == 1, "a completed payment never extends again"


@pytest.mark.asyncio
async def test_premium_extension_whose_answer_was_lost_is_not_applied_twice(database, panel, monkeypatch):
    monkeypatch.setattr(shop, "redis_client", object())

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(shop, "notify_user_telegram", quiet)
    p, remote, before = await premium(database, panel, "premium-lost")
    panel.lose.add("/actions/extend")
    try:
        await shop.fulfill(p.id, database)
    except Exception:
        pass  # the attempt fails like a real timeout; the payment stays retryable
    assert p.fulfillment_status != "completed"
    p.next_retry_at = None
    await database.commit()
    await shop.fulfill(p.id, database)
    expiry = datetime.fromisoformat(panel.users[remote]["expireAt"])
    assert panel.count("POST", "/actions/extend") == 1, "the retry sees the panel already extended"
    assert expiry - before <= timedelta(days=30, minutes=1), "30 days, not 60"
    assert p.fulfillment_status == "completed"


# ------------------------------------------------------------------- back to the app

def test_a_payment_made_in_the_app_returns_to_the_app(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cabinet_url", "https://cabinet.corgi.test")
    monkeypatch.setattr(settings, "api_domain", "api.corgi.test")
    order = "vpn-1-2-abcdef"
    assert shop._return_url(order) == "https://cabinet.corgi.test/?order=vpn-1-2-abcdef", "the web keeps the cabinet"
    back = shop._return_url(order, request=app_request("/api/payments/create"))
    assert back.endswith("/api/app/paid?order=vpn-1-2-abcdef") and back.startswith("https://")
    link = app_login.payment_link(order)
    assert link.startswith("corgi://payment?") and "order=vpn-1-2-abcdef" in link
    browser = Request({"type": "http", "method": "POST", "path": "/", "client": ("1.1.1.1", 1), "query_string": b"",
                       "headers": [(b"x-shop-client", b"cabinet")]})
    assert "cabinet.corgi.test" in shop._return_url(order, request=browser)


@pytest.mark.asyncio
async def test_the_return_page_forwards_only_order_ids():
    page = await app_login.paid_return("vpn-1-2-abcdef")
    assert page.status_code == 200 and b"corgi://payment?" in page.body
    assert page.headers["cache-control"] == "no-store" and "default-src 'none'" in page.headers["content-security-policy"]
    for bad in ("", "<script>", "a" * 200, "x y"):
        with pytest.raises(HTTPException):
            await app_login.paid_return(bad)


@pytest.mark.asyncio
async def test_checkout_from_the_app_gives_the_provider_the_app_return_address(database, monkeypatch):
    from test_behaviour_payments_v2 import FakeRedis
    seen = []

    class Provider:
        async def create(self, amount, order_id, description, return_url):
            seen.append(return_url)
            return {"id": "yk-app", "url": "https://yoomoney.test/pay/yk-app", "status": "pending"}

    async def yes(*a, **k):
        return True

    async def providers(db, requested):
        return ["yookassa"]

    async def risk(*args):
        return 0, "allow", {}
    monkeypatch.setattr(shop, "_risk_score", risk)
    monkeypatch.setattr(shop, "production_payments_allowed", yes)
    monkeypatch.setattr(shop, "e2e_checkout_allowed", yes)
    monkeypatch.setattr(shop, "_payment_provider_order", providers)
    monkeypatch.setattr(shop, "redis_client", FakeRedis())
    monkeypatch.setattr(shop, "YooKassaProvider", Provider)
    request = Request({"type": "http", "method": "POST", "path": "/api/payments/create", "client": ("10.0.0.1", 1), "query_string": b"",
                       "headers": [(b"idempotency-key", b"app-buy-1"), (b"x-shop-client", b"ios-user")]})
    result = await shop.create_payment({"plan_id": 2, "provider": "yookassa"}, request, database)
    assert result["url"].startswith("https://yoomoney.test/")
    assert len(seen) == 1 and "/api/app/paid?order=" in seen[0]


# ----------------------------------------------------------- one state for all channels

class Chat:
    type = "private"


class FromUser:
    id = 222
    language_code = "ru"


class Message:
    chat = Chat()
    from_user = FromUser()


@pytest.mark.asyncio
async def test_bot_cabinet_and_apps_show_the_same_subscription(customer, panel, monkeypatch):
    db = customer
    await give_trial(db)
    await worker.run_next_job("test-worker")
    sub = (await db.execute(select(Subscription).where(Subscription.user_id == 2).execution_options(populate_existing=True))).scalar_one()

    cabinet = await shop.my_subscription(app_request("/api/me/subscription"), db)
    assert (cabinet["subscription"]["subscription_url"], cabinet["subscription"]["expires_at"]) == (sub.subscription_url, sub.expires_at)

    app = json.loads((await shop.connection_info(app_request("/api/me/connection-info"), db)).body)
    assert app["subscription_url"] == sub.subscription_url and app["expires_at"] == sub.expires_at.isoformat()

    sent = []

    async def capture(message, section, text, keyboard=None):
        sent.append((section, text))
    monkeypatch.setattr(bot, "send_section", capture)
    monkeypatch.setattr(bot, "engine", db.bind)
    await bot.subscription(Message())
    assert sent and sub.subscription_url in sent[0][1], "the bot reads the same row"

    # The panel is the source of the link: a changed link reaches every channel at once.
    sub.subscription_url = "https://sub.corgi.test/rotated"
    await db.commit()
    assert (await shop.my_subscription(app_request(), db))["subscription"]["subscription_url"].endswith("/rotated")
    assert json.loads((await shop.connection_info(app_request(), db)).body)["subscription_url"].endswith("/rotated")
    sent.clear()
    await bot.subscription(Message())
    assert sent[0][1].endswith("/rotated")
