"""BACKLOG A1 (C1): what the public plan list, the auto-renew status and the subscription file give away — checked by
calling the routes, not by reading their source (replaces the source checks of test_v310.py)."""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import admin_api, customer_api
from app import main as shop
from app.models import AutoRenewMethod, Plan, Subscription
from test_subscription_commerce import database  # noqa: F401


def req():
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"accept-language", b"ru")],
                    "client": ("203.0.113.5", 1), "query_string": b""})


@pytest.mark.asyncio
async def test_public_plans_hide_the_panel_profile_and_the_admin_list_shows_it(database):
    plan = await database.get(Plan, 1)
    plan.remnawave_profile_id = "squad-secret-uuid"
    database.add(Plan(id=3, name="Hidden", price=50, duration_days=30, traffic_limit_gb=10, device_limit=1, enabled=False,
                      remnawave_profile_id="other-squad"))
    await database.commit()
    public = await shop.plans(database, req())
    assert [p["id"] for p in public] == [1, 2]  # a disabled plan is not offered
    assert all("remnawave_profile_id" not in p for p in public)
    assert "squad-secret-uuid" not in repr(public)
    admin = await admin_api.admin_list_plans(database, admin=None)
    assert {p["id"]: p["remnawave_profile_id"] for p in admin}[1] == "squad-secret-uuid"
    assert {p["id"] for p in admin} == {1, 2, 3}


@pytest.mark.asyncio
async def test_auto_renew_status_never_shows_the_providers_error_text(database):
    database.add(AutoRenewMethod(user_id=1, provider="yookassa", enabled=True, external_token_encrypted="enc",
                                 last_error="card 4111 declined by issuer, token pm_secret_123"))
    await database.commit()
    status = await customer_api.auto_renew_status(req(), database)
    assert status["last_error"] == "Автопродление не выполнено"
    assert "pm_secret" not in repr(status) and "4111" not in repr(status)
    assert status["configured"] is True


@pytest.mark.asyncio
async def test_subscription_file_is_private_and_refuses_header_injection(database):
    sub = await database.get(Subscription, 1)
    sub.is_primary = True
    sub.subscription_url = "https://sub.example.test/s/abc"
    await database.commit()
    response = await customer_api.subscription_file(req(), database)
    assert response.body == b"https://sub.example.test/s/abc\n"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"] == 'attachment; filename="remnawave-subscription.txt"'
    for bad in ("https://sub.example.test/s/abc\r\nSet-Cookie: x=1", "https://sub.example.test/\x00", ""):
        sub.subscription_url = bad
        await database.commit()
        with pytest.raises(HTTPException) as err:
            await customer_api.subscription_file(req(), database)
        assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_subscription_file_of_a_user_without_a_primary_subscription_is_404(database):
    sub = await database.get(Subscription, 1)
    sub.is_primary = False
    sub.expires_at = datetime.utcnow() + timedelta(days=1)
    await database.commit()
    with pytest.raises(HTTPException) as err:
        await customer_api.subscription_file(req(), database)
    assert err.value.status_code == 404


# ---- Staging E2E settings (replaces the source checks of test_v311.py) ----
from app import staging_e2e_api  # noqa: E402

SECRETS = ("remnawave_token", "user_bearer_token", "yookassa_shop_id", "yookassa_secret_key", "platega_merchant_id",
           "platega_secret", "rollypay_api_key", "rollypay_signing_secret")


def staging(**over):
    data = {"public_base_url": "https://shop.example.test", "remnawave_url": "https://panel.example.test", "plan_id": 1,
            "providers": ["yookassa"], "platega_enabled": False, "rollypay_enabled": False, "staging_confirmed": True,
            **{k: f"sandbox-{k}-0123456789" for k in SECRETS}}
    data.update(over)
    return staging_e2e_api.StagingE2EConfigIn(**data)


@pytest.fixture
def staging_env(monkeypatch):
    async def noop(*args, **kwargs):
        return None
    monkeypatch.setattr(shop, "validate_public_url", lambda *a, **k: None)
    monkeypatch.setattr(shop, "_advisory_lock", noop)
    monkeypatch.setattr(shop, "audit", noop)


@pytest.mark.asyncio
async def test_blank_staging_secrets_keep_the_saved_ones(database, staging_env):
    admin = type("A", (), {"email": "owner@example.test"})()
    await staging_e2e_api.update_staging_e2e_config(staging(), database, admin)
    blank = staging(**{k: "" for k in SECRETS})
    await staging_e2e_api.update_staging_e2e_config(blank, database, admin)
    saved = await staging_e2e_api._staging_config(database)
    assert all(saved[k] == f"sandbox-{k}-0123456789" for k in SECRETS)
    shown = await staging_e2e_api.staging_e2e_config(database, admin)
    assert not any("sandbox-" in str(v) for v in shown["config"].values())
    assert shown["config"]["remnawave_token_configured"] is True


@pytest.mark.asyncio
async def test_staging_refuses_unconfirmed_production_or_tokenless_settings(database, staging_env, monkeypatch):
    admin = type("A", (), {"email": "owner@example.test"})()
    with pytest.raises(HTTPException) as err:
        await staging_e2e_api.update_staging_e2e_config(staging(staging_confirmed=False), database, admin)
    assert "sandbox" in err.value.detail
    with pytest.raises(HTTPException) as err:
        await staging_e2e_api.update_staging_e2e_config(staging(remnawave_token=""), database, admin)
    assert err.value.detail == "Укажите токен Remnawave для staging"
    monkeypatch.setattr(shop.settings, "yookassa_secret_key", "sandbox-yookassa_secret_key-0123456789")
    with pytest.raises(HTTPException) as err:
        await staging_e2e_api.update_staging_e2e_config(staging(), database, admin)
    assert "production-платёжные credentials" in err.value.detail
    assert await staging_e2e_api._staging_config(database) is None


def test_staging_output_hides_secrets_but_not_public_ids():
    config = {"yookassa_secret_key": "live-secret-abcdef", "yookassa_shop_id": "shop-123456789", "runner_token": "runner-token-xyz",
              "platega_merchant_id": "merchant-123456789", "remnawave_token": "short"}
    out = staging_e2e_api._redact_staging_output("k=live-secret-abcdef id=shop-123456789 r=runner-token-xyz m=merchant-123456789 t=short", config)
    assert out == "k=[скрыто] id=shop-123456789 r=[скрыто] m=merchant-123456789 t=short"
