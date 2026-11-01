"""Unit economics: first-touch source from the bot and the cabinet, spend by month, CAC and ROMI per source."""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app import economics
from app.models import Payment, User
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test")


@pytest.mark.asyncio
async def test_report_counts_a_customer_created_in_the_same_month_on_its_first_day(database):  # noqa: F811
    """A report for one calendar month must include a customer created inside that month, even on day 1.

    The report buckets by calendar month because ad spend is entered per ``YYYY-MM``. A customer created
    «a day ago» on the 1st belongs to the previous month — that is correct — but a customer created on
    the 1st itself must be counted; before the fix the test only passed from the 3rd of the month.
    """
    first = datetime(2026, 11, 1, 9, 0, 0)
    database.add(User(email="dayone@corgi.test", referral_code="DAYONE1", acquisition_source="vk_ads", created_at=first))
    await database.commit()
    out = await economics.report(database, 1, first)
    vk = next((s for s in out["sources"] if s["source"] == "vk_ads"), None)
    assert vk is not None, "a customer created on the first day of the month is counted"
    assert vk["new_customers"] >= 1


def test_sources_are_read_from_start_links_and_cleaned():
    assert economics.source_from_start("src_VK_Ads") == "vk_ads"
    assert economics.source_from_start("ref_AB12__src_tg-channel") == "tg-channel"
    assert economics.source_from_start("ref_AB12") is None and economics.source_from_start("app_login") is None
    assert economics.clean_source("<script>") is None
    with pytest.raises(ValidationError):
        economics.SpendIn(source="bad source!", month="2026-10", amount=1)


@pytest.mark.asyncio
async def test_first_touch_wins_and_old_customers_are_not_reattributed(database):  # noqa: F811
    fresh = User(email="fresh@corgi.test", referral_code="FRESH1", created_at=datetime.utcnow())
    old = await database.get(User, 1)
    old.created_at = datetime.utcnow() - timedelta(days=30)
    database.add(fresh)
    await database.commit()
    assert await economics.remember_source(database, fresh, "vk_ads") is True
    assert await economics.remember_source(database, fresh, "yandex") is False and fresh.acquisition_source == "vk_ads"
    assert await economics.remember_source(database, old, "vk_ads") is False


@pytest.mark.asyncio
async def test_cac_and_romi_per_source(database):  # noqa: F811
    # «Now» is pinned to the middle of the current month: the report counts calendar months (ad spend is
    # entered per YYYY-MM), so a customer created «two days ago» falls into the *previous* month when the
    # test runs on the 1st–2nd and the whole report comes back empty. The window is what is under test
    # here, not the day the suite happens to run.
    now = datetime.utcnow().replace(day=15, hour=12, minute=0, second=0, microsecond=0)
    month = f"{now:%Y-%m}"
    for i in range(4):
        u = User(email=f"vk{i}@corgi.test", referral_code=f"VK{i}", acquisition_source="vk_ads", created_at=now - timedelta(days=2))
        database.add(u)
        await database.flush()
        if i < 2:
            database.add(Payment(user_id=u.id, plan_id=1, provider="yookassa", order_id=f"e{i}", idempotency_key=f"e{i}", amount=Decimal("300"),
                                 currency="RUB", status="paid", purpose="subscription", paid_at=now))
    await database.commit()
    await economics.put_spend(economics.SpendIn(source="vk_ads", month=month, amount=Decimal("400")), database, ADMIN)
    out = await economics.report(database, 1, now)
    vk = next(s for s in out["sources"] if s["source"] == "vk_ads")
    assert (vk["new_customers"], vk["paying_customers"], vk["conversion"]) == (4, 2, 50.0)
    assert (vk["revenue"], vk["spend"], vk["cac"], vk["revenue_per_payer"], vk["romi"]) == ("600.00", "400.00", "200.00", "300.00", 50.0)
    await economics.put_spend(economics.SpendIn(source="vk_ads", month=month, amount=Decimal("0")), database, ADMIN)
    assert "vk_ads" not in (await economics.report(database, 1, now))["spend"], "zero removes the month"
    assert (await database.scalar(select(User).where(User.email == "vk0@corgi.test"))).acquisition_source == "vk_ads"
