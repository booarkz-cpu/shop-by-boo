"""Stage 18 (docs/ru/new/ADMIN_VERIFICATION.md): every changing admin route of «Тарифы», «Промокоды», «Подарки» is
exercised — create, edit, delete — with the rules an administrator relies on."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import marketing_api, regional_pricing, subscription_commerce, tariff_api
from app import admin_api  # noqa: F401 — registers /api/admin/gifts
from app import main as shop
from app.models import Plan, PromoCode, Promotion, TariffConstructor, TrafficPackage
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test", role="admin")


@pytest.mark.asyncio
async def test_traffic_packages_create_and_edit(database):
    db = database
    with pytest.raises(HTTPException) as err:
        await subscription_commerce.create_package(subscription_commerce.PackageIn(name="10 ГБ", traffic_gb=10, price=Decimal("50"), plan_id=999), db, ADMIN)
    assert err.value.status_code == 404
    made = await subscription_commerce.create_package(subscription_commerce.PackageIn(name="10 ГБ", traffic_gb=10, price=Decimal("50"), plan_id=1), db, ADMIN)
    edited = await subscription_commerce.edit_package(made["id"], subscription_commerce.PackageIn(name="20 ГБ", traffic_gb=20, price=Decimal("90")), db, ADMIN)
    row = await db.get(TrafficPackage, made["id"])
    await db.refresh(row)
    assert (row.name, row.traffic_gb, row.price, row.plan_id) == ("20 ГБ", 20, Decimal("90.00"), None) and edited["traffic_gb"] == 20
    with pytest.raises(HTTPException) as err:
        await subscription_commerce.edit_package(99999, subscription_commerce.PackageIn(name="x", traffic_gb=1, price=Decimal("1")), db, ADMIN)
    assert err.value.status_code == 404


def _options():
    return [tariff_api.OptionIn(kind=k, label=k, value=v, price=Decimal(p)) for k, v, p in (("devices", 1, "0"), ("traffic_gb", 0, "0"), ("days", 30, "100"))]


@pytest.mark.asyncio
async def test_tariff_constructor_edit_and_delete(database):
    db = database
    made = await tariff_api.admin_constructor_create(tariff_api.ConstructorIn(name="Свой", base_price=Decimal("10"), options=_options()), db, ADMIN)
    with pytest.raises(HTTPException) as err:  # an enabled constructor needs every kind of option
        await tariff_api.admin_constructor_update(made["id"], tariff_api.ConstructorIn(name="Свой", base_price=Decimal("10"), options=_options()[:2]), db, ADMIN)
    assert err.value.status_code == 400
    out = await tariff_api.admin_constructor_update(made["id"], tariff_api.ConstructorIn(name="Свой 2", base_price=Decimal("20"), options=_options()), db, ADMIN)
    assert out["name"] == "Свой 2"
    await tariff_api.admin_constructor_delete(made["id"], db, ADMIN)
    row = await db.get(TariffConstructor, made["id"])
    await db.refresh(row)
    plan = await db.get(Plan, row.plan_id)
    assert row.enabled is False and plan.enabled is False, "deleting hides the constructor and its plan, history stays"


@pytest.mark.asyncio
async def test_regional_prices_are_saved(database):
    body = regional_pricing.PricingIn(enabled=True, regions=[regional_pricing.RegionIn(name="СНГ", countries=["kz", "by"], percent=-20)])
    out = await regional_pricing.put_regions(body, database, ADMIN)
    assert out["enabled"] is True and out["regions"][0]["countries"] == ["BY", "KZ"]
    assert (await regional_pricing.get_regions(database, ADMIN))["regions"][0]["percent"] == -20


@pytest.mark.asyncio
async def test_promotions_and_codes_create_edit_delete(database):
    db = database
    await marketing_api.create_promotion(marketing_api.PromotionIn(name="Осень", value=Decimal("15")), db, ADMIN)
    promo = (await db.execute(select(Promotion))).scalars().one()
    with pytest.raises(HTTPException) as err:  # v28.77.0: the edit used to accept a 150 % discount
        await marketing_api.update_promotion(promo.id, marketing_api.PromotionIn(name="Осень", value=Decimal("150")), db, ADMIN)
    assert err.value.status_code == 400
    await marketing_api.update_promotion(promo.id, marketing_api.PromotionIn(name="Зима", value=Decimal("20")), db, ADMIN)
    await db.refresh(promo)
    assert (promo.name, promo.value) == ("Зима", Decimal("20.00"))
    await marketing_api.delete_promotion(promo.id, db, ADMIN)
    assert (await db.execute(select(Promotion))).scalars().first() is None

    await marketing_api.create_promo_code(marketing_api.PromoCodeIn(code=" corgi10 ", value=Decimal("10")), db, ADMIN)
    with pytest.raises(HTTPException) as err:
        await marketing_api.create_promo_code(marketing_api.PromoCodeIn(code="CORGI10", value=Decimal("10")), db, ADMIN)
    assert err.value.status_code == 409
    code = (await db.execute(select(PromoCode))).scalars().one()
    assert code.code == "CORGI10"
    with pytest.raises(HTTPException):
        await marketing_api.update_promo_code(code.id, marketing_api.PromoCodeIn(code="CORGI10", kind="bonus", value=Decimal("10")), db, ADMIN)
    await marketing_api.update_promo_code(code.id, marketing_api.PromoCodeIn(code="corgi15", value=Decimal("15"), usage_limit=5), db, ADMIN)
    await db.refresh(code)
    assert (code.code, code.value, code.usage_limit) == ("CORGI15", Decimal("15.00"), 5)
    await marketing_api.delete_promo_code(code.id, db, ADMIN)
    assert (await db.execute(select(PromoCode))).scalars().first() is None


@pytest.mark.asyncio
async def test_gift_codes(database):
    from app.admin_api import admin_gift_create
    made = await admin_gift_create(shop.GiftCreateIn(code="gift-2026", plan_id=1, max_uses=3), database, ADMIN)
    assert made["code"] == "GIFT-2026"
    with pytest.raises(HTTPException) as err:
        await admin_gift_create(shop.GiftCreateIn(code="GIFT-2026", plan_id=1), database, ADMIN)
    assert err.value.status_code == 409
    with pytest.raises(HTTPException) as err:
        await admin_gift_create(shop.GiftCreateIn(code="gift-x1", plan_id=999), database, ADMIN)
    assert err.value.status_code == 400
