from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main as shop
from app.models import FinancialLedger
from app_contract import columns, missing_routes, permissions, revision, tables
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_current_release_identity_and_migration_head():
    manifest = (ROOT / "release-manifest.template.json").read_text()
    assert '"version": "3.0.0-realise"' in manifest
    assert '"version": "2.13.0"' in manifest
    assert '"version": "2.12.0"' in manifest
    assert '"version": "2.11.0"' in manifest
    assert '"version": "2.10.0"' in manifest
    assert '"version": "2.9.0"' in manifest
    assert '"version": "2.8.0"' in manifest
    assert '"version": "2.7.0"' in manifest
    assert '"version": "2.6.0"' in manifest
    assert '"version": "2.5.0"' in manifest
    assert '"version": "2.4.0"' in manifest
    assert '"version": "2.3.0"' in manifest


def test_release_tooling_uses_current_artifact():
    verify = (ROOT / "scripts/verify-release.sh").read_text()
    assert "${ARTIFACT%.zip}_manifest.json" in verify
    assert "remnawave_vpn_shop_v40_production.zip" not in verify


@pytest.mark.asyncio
async def test_financial_ledger_records_an_operation_once(database):
    first = await shop.record_financial_event(database, operation_key="payment:9:paid", user_id=1, payment_id=9, kind="payment",
                                              direction="credit", amount=Decimal("100"), currency="RUB")
    again = await shop.record_financial_event(database, operation_key="payment:9:paid", user_id=1, payment_id=9, kind="payment",
                                              direction="credit", amount=Decimal("999"), currency="RUB")
    await database.commit()
    rows = (await database.execute(select(FinancialLedger).where(FinancialLedger.operation_key == "payment:9:paid"))).scalars().all()
    assert len(rows) == 1 and rows[0].amount == Decimal("100") and again.id == first.id, "a replay never changes the entry"
    for bad in ({"amount": Decimal("0"), "direction": "credit"}, {"amount": Decimal("1"), "direction": "sideways"}):
        with pytest.raises(ValueError):
            await shop.record_financial_event(database, operation_key="x", user_id=1, payment_id=None, kind="k", currency="RUB", **bad)


@pytest.mark.asyncio
async def test_every_response_carries_a_request_id():
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=shop.app), base_url="http://localhost") as client:
        echoed = await client.get("/health/live", headers={"X-Request-ID": "trace-42"})
        fresh = await client.get("/health/live")
    assert echoed.status_code == 200 and echoed.headers["X-Request-ID"] == "trace-42"
    assert len(fresh.headers["X-Request-ID"]) >= 32, "a request without one gets a new id"
    assert not missing_routes("GET /health/live", "GET /health/ready")


def test_v220_platform_schema_and_routes():
    assert {"notifications", "status_components", "deployments", "financial_ledger"} <= set(tables())
    assert {"first_purchase_only", "max_uses_per_user", "referral_only"} <= columns("promo_codes")
    assert not missing_routes("GET /api/public/status", "POST /api/admin/deployments/{deployment_id}/promote")
    assert permissions("POST", "/api/admin/deployments/{deployment_id}/promote") == {"ops.releases"}
    assert revision("0034_v2_2_0_platform_features") is not None


@pytest.mark.asyncio
async def test_a_deployment_with_errors_cannot_get_more_traffic(database):
    admin = SimpleNamespace(email="a@b.c")
    created = await shop.deployment_create(shop.DeploymentIn(version="28.35.0", traffic_percent=10), database, admin)
    with pytest.raises(HTTPException) as refused:
        await shop.deployment_promote(created["id"], shop.DeploymentPromoteIn(traffic_percent=50, error_rate_percent=Decimal("5")), database, admin)
    assert refused.value.status_code == 409
    back = await shop.deployment_promote(created["id"], shop.DeploymentPromoteIn(traffic_percent=0, error_rate_percent=Decimal("7")), database, admin)
    assert back["status"] == "planned", "traffic can always be lowered"
    done = await shop.deployment_promote(created["id"], shop.DeploymentPromoteIn(traffic_percent=100), database, admin)
    assert done["status"] == "completed"
    with pytest.raises(HTTPException):
        await shop.deployment_promote(created["id"], shop.DeploymentPromoteIn(traffic_percent=50), database, admin)
