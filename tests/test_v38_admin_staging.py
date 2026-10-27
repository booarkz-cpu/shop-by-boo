from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main as shop
from app.models import AppSetting
from app_contract import missing_routes, permissions, tables
from test_subscription_commerce import database  # noqa: F401

ROOT=Path(__file__).resolve().parents[1]


def test_admin_telegram_and_staging_routes():
    assert not missing_routes("POST /api/admin/auth/telegram", "GET /api/admin/staging-e2e/config", "PUT /api/admin/staging-e2e/config",
                              "POST /api/admin/staging-e2e/run")
    assert permissions("PUT", "/api/admin/staging-e2e/config") == {"staging_e2e.manage"}
    column = tables()["admin_users"].c.telegram_id
    assert column.nullable and (column.unique or any(set(c.name for c in con.columns) == {"telegram_id"}
                                                     for con in tables()["admin_users"].constraints))


def staging(**kw):
    base = dict(public_base_url="https://staging.corgi.example", remnawave_url="https://panel-staging.corgi.example",
                remnawave_token="rw-staging-token", plan_id=1, providers=["yookassa"], platega_enabled=False, rollypay_enabled=False,
                yookassa_shop_id="sandbox-shop", yookassa_secret_key="test_SANDBOX_KEY", staging_confirmed=True)
    base.update(kw)
    return shop.StagingE2EConfigIn(**base)


@pytest.mark.asyncio
async def test_staging_keys_are_sandbox_only_encrypted_and_never_shown(database, monkeypatch):
    monkeypatch.setattr(shop, "validate_public_url", lambda value, **kw: value)
    monkeypatch.setattr(shop.settings, "yookassa_secret_key", "live_PRODUCTION_KEY")
    admin = SimpleNamespace(email="a@b.c")
    with pytest.raises(HTTPException) as unconfirmed:
        await shop.update_staging_e2e_config(staging(staging_confirmed=False), database, admin)
    assert unconfirmed.value.status_code == 400
    with pytest.raises(HTTPException) as production:
        await shop.update_staging_e2e_config(staging(yookassa_secret_key="live_PRODUCTION_KEY"), database, admin)
    assert "production" in production.value.detail
    assert (await shop.update_staging_e2e_config(staging(), database, admin))["providers"] == ["yookassa"]
    stored = " ".join(r.value for r in (await database.execute(select(AppSetting))).scalars())
    assert "test_SANDBOX_KEY" not in stored and "rw-staging-token" not in stored, "kept encrypted"
    shown = await shop.staging_e2e_config(database, admin)
    assert shown["config"]["provider_credentials"]["yookassa"] is True and shown["config"]["remnawave_token_configured"] is True
    assert "test_SANDBOX_KEY" not in str(shown) and "rw-staging-token" not in str(shown)

def test_admin_ui_has_russian_staging_and_telegram_controls():
    ui=(ROOT/'admin/src/main.tsx').read_text()
    assert 'Telegram ID' in ui
    assert 'Войти через Telegram' in ui
    assert 'Проверка ключей песочницы (v1)' in ui
    assert '/api/admin/e2e-v2/overview' in (ROOT/'admin/src/payment-admission.tsx').read_text()
    assert '/api/admin/staging-e2e/run' in ui


def test_staging_isolation_and_runner_are_safe():
    docker=(ROOT/'backend/Dockerfile').read_text(); sh=(ROOT/'scripts/staging-e2e.sh').read_text()
    assert 'COPY scripts/staging-e2e.sh ./staging-e2e.sh' in docker
    assert '/api/internal/staging-e2e/payment' in sh and 'STAGING_RUNNER_TOKEN' in sh
