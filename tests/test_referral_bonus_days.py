"""«Приведи друга — получи +10 дней»: a friend's first payment queues one bonus job; the worker extends the
referrer's subscription on the panel once, or gives a gift code when the referrer has no subscription."""
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import worker
from app import bonus_days
from app import main as shop
from app.models import AppSetting, GiftCode, Job, Payment, Subscription
from test_integration_billing_vpn import panel, premium  # noqa: F401
from test_subscription_commerce import database  # noqa: F401


@pytest.fixture
def quiet(monkeypatch, database):
    monkeypatch.setattr(shop, "redis_client", object())
    monkeypatch.setattr(shop, "engine", database.bind)

    async def nothing(*a, **k):
        return None
    monkeypatch.setattr(shop, "notify_user_telegram", nothing)


async def friend_pays(database, panel, order):  # noqa: F811
    p, _, _ = await premium(database, panel, order)
    p.referrer_id_snapshot = 2  # customer 1 was invited by customer 2
    await database.commit()
    await shop.fulfill(p.id, database)
    return p


@pytest.mark.asyncio
async def test_a_friends_first_payment_adds_ten_days_to_the_referrers_subscription(database, panel, quiet):  # noqa: F811
    remote = str(uuid.uuid4())
    ends = datetime.utcnow() + timedelta(days=5)
    panel.users[remote] = {"uuid": remote, "id": remote, "username": "user_2", "status": "ACTIVE", "expireAt": ends.isoformat(),
                           "subscriptionUrl": "https://sub.corgi.test/two"}
    database.add(Subscription(id=7, user_id=2, plan_id=1, expires_at=ends, remnawave_uuid=remote, lifecycle_status="active", is_primary=True))
    await database.commit()
    await friend_pays(database, panel, "friend-1")
    jobs = (await database.execute(select(Job).where(Job.kind == "bonus_days"))).scalars().all()
    assert len(jobs) == 1 and jobs[0].payload["days"] == 10
    extends_before = panel.count("POST", "/actions/extend")
    while await worker.run_next_job("w"):
        pass
    assert panel.count("POST", "/actions/extend") == extends_before + 1
    sub = await database.get(Subscription, 7, populate_existing=True)
    assert timedelta(days=14, hours=23) < sub.expires_at - datetime.utcnow() <= timedelta(days=15, minutes=1)
    job = await database.get(Job, jobs[0].id, populate_existing=True)
    assert job.status == "completed"
    job.status, job.attempts = "queued", 0  # even a replayed job adds nothing
    await database.commit()
    while await worker.run_next_job("w"):
        pass
    assert panel.count("POST", "/actions/extend") == extends_before + 1


@pytest.mark.asyncio
async def test_a_referrer_without_a_subscription_gets_a_gift_code(database, panel, quiet):  # noqa: F811
    await friend_pays(database, panel, "friend-2")
    while await worker.run_next_job("w"):
        pass
    gift = await database.scalar(select(GiftCode).where(GiftCode.code.like("REF-%")))
    assert gift is not None and gift.duration_days == 10 and gift.max_uses == 1


@pytest.mark.asyncio
async def test_only_the_first_payment_counts_and_the_owner_can_change_the_days(database, panel, quiet):  # noqa: F811
    await bonus_days.set_bonus(bonus_days.BonusIn(enabled=True, days=7, first_payment_only=True), database, SimpleNamespace(email="a@b.c"))
    await friend_pays(database, panel, "friend-3")
    second = Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="friend-4", provider_payment_id="yk-friend-4",
                     amount=100, currency="RUB", status="paid", fulfillment_status="pending", purpose="subscription",
                     duration_days_snapshot=30, idempotency_key="idem-friend-4", referrer_id_snapshot=2, paid_at=datetime.utcnow())
    database.add(second)
    await database.commit()
    await shop.fulfill(second.id, database)
    jobs = (await database.execute(select(Job).where(Job.kind == "bonus_days"))).scalars().all()
    assert [j.payload["days"] for j in jobs] == [7], "one bonus per invited friend"
    await bonus_days.set_bonus(bonus_days.BonusIn(enabled=False), database, SimpleNamespace(email="a@b.c"))
    assert (await bonus_days.get_bonus(database, SimpleNamespace(email="a@b.c")))["enabled"] is False
    assert await database.get(AppSetting, bonus_days.CONFIG_KEY)
