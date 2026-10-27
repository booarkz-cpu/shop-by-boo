from pathlib import Path

import pytest

from app_contract import columns, env_names, missing_routes, revision, tables

ROOT = Path(__file__).resolve().parents[1]


def test_v240_cabinet_auth_menu_and_sandbox_are_served():
    assert not missing_routes("POST /api/auth/register", "POST /api/auth/login", "GET /api/auth/vk", "GET /api/public/cabinet-menu",
                              "POST /api/payments/sandbox/complete", "GET /api/admin/cabinet/menu")
    assert {"PAYMENTS_SANDBOX", "CABINET_URL", "VK_CLIENT_ID", "CABINET_DOMAIN"} <= env_names()
    assert "cabinet_menu_items" in tables() and {"email_password_hash", "vk_id"} <= columns("users")
    assert revision("0036_v2_4_0_cabinet").down_revision == "0035_v2_3_0_wallet_gifts"
    from app import main as shop
    assert {"/api/auth/login", "/api/auth/register"} <= set(shop.RATE_LIMITS), "sign-in and registration are rate limited"


@pytest.mark.asyncio
async def test_sandbox_payments_work_only_when_enabled_outside_production(monkeypatch):
    from app.config import settings
    from app.payments import PaymentError, SandboxProvider
    provider = SandboxProvider()
    monkeypatch.setattr(settings, "payments_sandbox", True)
    monkeypatch.setattr(settings, "app_env", "staging")
    created = await provider.create(100, "o-1", "test", "https://shop.example")
    assert created["id"] == "sandbox-o-1"
    assert await provider.verify_succeeded("sandbox-o-1", 100, "RUB", "o-1") is True
    assert await provider.verify_succeeded("sandbox-o-11", 100, "RUB", "o-1") is False, "only the exact order"
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(PaymentError):
        await provider.create(100, "o-2", "test", "https://shop.example")
    assert await provider.verify_succeeded("sandbox-o-1", 100, "RUB", "o-1") is False


def test_v240_frontends_and_sandbox_script_exist():
    cabinet = (ROOT / "cabinet/src/main.tsx").read_text()
    admin = (ROOT / "admin/src/main.tsx").read_text()
    style = (ROOT / "admin/src/style.css").read_text()
    compose = (ROOT / "docker-compose.yml").read_text()
    caddy = (ROOT / "deploy/Caddyfile").read_text()
    script = (ROOT / "scripts/sandbox-e2e.sh").read_text()
    assert "Личный кабинет" in cabinet
    assert "Войти через Telegram" in (ROOT / "cabinet/src/i18n.tsx").read_text()
    assert "Войти через Яндекс" in (ROOT / "cabinet/src/i18n.tsx").read_text()
    assert "Войти через VK" in (ROOT / "cabinet/src/i18n.tsx").read_text()
    assert "sandbox_payment" in cabinet
    assert "CabinetCMS" in admin
    assert "Личный кабинет" in admin
    assert "--accent:" in style
    assert "Inter" in style
    assert "@fontsource-variable/inter" in (ROOT / "admin/src/app/layout.tsx").read_text()
    assert "cabinet:" in compose
    assert "CABINET_DOMAIN" in compose
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "docker compose -f docker-compose.yml config --quiet" in ci
    assert "app: [admin, miniapp, cabinet]" in ci
    assert "{$CABINET_DOMAIN}" in caddy
    assert "reverse_proxy cabinet:80" in caddy
    assert "PAYMENTS_SANDBOX" in script
    assert "/api/payments/sandbox/complete" in script


def test_v240_docs_and_installer_cover_cabinet():
    readme = (ROOT / "docs/archive/README_BEFORE_WORKSPACE.md").read_text()
    notes = (ROOT / "docs/archive/root/RELEASE_NOTES_V2_4_0.md").read_text()
    installer = (ROOT / "deploy/install-vps.sh").read_text()
    assert "2.4.0" in readme
    assert "личный кабинет" in readme.lower() or "Личный кабинет" in readme
    assert "Sandbox" in notes or "sandbox" in notes
    assert "CABINET_DOMAIN" in installer
    assert "PAYMENTS_SANDBOX" in installer
