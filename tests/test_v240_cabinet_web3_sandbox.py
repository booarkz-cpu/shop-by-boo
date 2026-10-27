from main_source import main_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v240_cabinet_auth_menu_and_sandbox_are_wired():
    main = main_source()
    cabinet_api = (ROOT / "backend/app/cabinet_api.py").read_text()
    models = (ROOT / "backend/app/models.py").read_text()
    payments = (ROOT / "backend/app/payments.py").read_text()
    cfg = (ROOT / "backend/app/config.py").read_text()
    migration = (ROOT / "backend/alembic/versions/0036_v2_4_0_cabinet.py").read_text()
    assert "from .cabinet_api import router as cabinet_router" in main
    assert "app.include_router(cabinet_router)" in main
    assert 'class SandboxProvider' in payments
    assert 'alias="PAYMENTS_SANDBOX"' in cfg
    assert 'alias="CABINET_URL"' in cfg
    assert 'alias="VK_CLIENT_ID"' in cfg
    assert 'alias="CABINET_DOMAIN"' in cfg
    assert "class CabinetMenuItem" in models
    assert "email_password_hash" in models
    assert "vk_id" in models
    assert 'revision = "0036_v2_4_0_cabinet"' in migration
    assert 'down_revision = "0035_v2_3_0_wallet_gifts"' in migration
    assert '@router.post("/api/auth/register")' in cabinet_api
    assert '@router.post("/api/auth/login")' in cabinet_api
    assert '@router.get("/api/auth/vk")' in cabinet_api
    assert '@router.get("/api/public/cabinet-menu")' in cabinet_api
    assert '@router.post("/api/payments/sandbox/complete")' in cabinet_api
    assert '@router.get("/api/admin/cabinet/menu")' in cabinet_api
    assert '/api/auth/login' in main and '/api/auth/register' in main


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
