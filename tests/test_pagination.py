"""v28.59.0 (stage 5, PERF-03/PERF-04): growing administrative lists are paged the same way.

``limit``/``offset`` query parameters, the old response shape, the total in ``X-Total-Count``; payment
analytics sums in the database and can be limited to a period."""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import Response

from app import enterprise_api, main as shop, payment_platform_api
from app.models import Campaign, CorporateAccount, PaymentProviderMetric
from app.pagination import MAX_LIMIT, Page, page_params
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="root@example.test", role="admin")


@pytest.mark.asyncio
async def test_lists_return_a_page_and_the_total(database):
    db = database
    for i in range(7):
        db.add(CorporateAccount(owner_user_id=1, name=f"Company {i}", plan_id=1))
        db.add(Campaign(name=f"Campaign {i}", kind="broadcast", status="draft", audience={}, content={}))
    await db.commit()
    response = Response()
    page = await payment_platform_api.list_corporate(response, Page(limit=3, offset=2), db, ADMIN)
    assert [x["name"] for x in page] == ["Company 4", "Company 3", "Company 2"]  # newest first
    assert response.headers["X-Total-Count"] == "7"
    response = Response()
    campaigns = await enterprise_api.enterprise_campaigns(response, Page(limit=5), db, ADMIN)
    assert len(campaigns) == 5 and response.headers["X-Total-Count"] == "7"


def test_page_limits_are_bounded():
    assert page_params(limit=10, offset=0) == Page(10, 0)
    route = next(r for r in shop.app.routes if getattr(r, "path", "") == "/api/admin/enterprise/campaigns")
    names = {p.name: p for p in route.dependant.dependencies[0].query_params}
    assert names["limit"].field_info.metadata  # ge/le constraints are declared
    assert MAX_LIMIT == 1000


@pytest.mark.asyncio
async def test_payment_analytics_sums_in_the_database_and_takes_a_period(database):
    db = database
    today = datetime.utcnow().date()
    for back, gross in ((1, "100.00"), (10, "50.00"), (400, "1000.00")):
        db.add(PaymentProviderMetric(provider="yookassa", day=(today - timedelta(days=back)).isoformat(), attempts=2, succeeded=1,
                                     failed=1, refunded=0, gross_amount=Decimal(gross), fees_amount=Decimal("0"), net_amount=Decimal(gross)))
    await db.commit()
    everything = await payment_platform_api.payment_analytics(None, db, ADMIN)
    assert everything["total_gross"] == "1150.00" and everything["succeeded"] == 3 and len(everything["providers"]) == 3
    month = await payment_platform_api.payment_analytics(30, db, ADMIN)
    assert month["total_gross"] == "150.00" and month["failed"] == 2 and len(month["providers"]) == 2
