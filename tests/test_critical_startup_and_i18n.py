from pathlib import Path

import pytest

from app import main as shop
from app.models import AppSetting
from app_contract import env_names
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_settings_cover_paths_used_at_import_and_backup():
    from app.config import Settings
    fields = Settings.model_fields
    assert {"MEDIA_DIR", "BACKUPS_DIR", "PROJECT_DIR", "BACKUP_S3_PREFIX", "YANDEX_CLIENT_ID", "YANDEX_CLIENT_SECRET",
            "YANDEX_REDIRECT_URI", "VK_CLIENT_ID", "CABINET_URL", "CABINET_DOMAIN", "PAYMENTS_SANDBOX", "MAINTENANCE_MODE",
            "DEFAULT_LANGUAGE"} <= env_names()
    defaults = {f.alias: f.default for f in fields.values()}
    assert (defaults["MEDIA_DIR"], defaults["BACKUPS_DIR"], defaults["PROJECT_DIR"], defaults["MAINTENANCE_MODE"]) == (
        "/data/media", "/data/backups", "/project", False)


@pytest.mark.asyncio
async def test_invalid_content_length_gets_a_json_answer():
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=shop.app), base_url="http://localhost") as client:
        bad = await client.post("/api/payments/create", content=b"{}", headers={"content-length": "abc", "content-type": "application/json"})
    assert bad.status_code == 400 and bad.json() == {"detail": "Invalid Content-Length"}


def test_yookassa_webhook_ip_allowlist_fails_closed(monkeypatch):
    from app.payments import SignatureVerificationError, YooKassaProvider, settings
    provider = YooKassaProvider()
    monkeypatch.setattr(settings, "yookassa_webhook_ip_allowlist", "")
    with pytest.raises(SignatureVerificationError, match="not configured"):
        provider._verify_ip("185.71.76.1")
    monkeypatch.setattr(settings, "yookassa_webhook_ip_allowlist", "185.71.76.0/27")
    with pytest.raises(SignatureVerificationError, match="Missing remote address"):
        provider._verify_ip("")
    provider._verify_ip("185.71.76.1")
    with pytest.raises(SignatureVerificationError):
        provider._verify_ip("203.0.113.5")


@pytest.mark.asyncio
async def test_replacing_media_deletes_only_inside_the_media_folder(database, monkeypatch, tmp_path):
    media, outside = tmp_path / "media", tmp_path / "secret.txt"
    media.mkdir()
    outside.write_text("keep me")
    (media / "secret.txt").write_text("old logo")
    monkeypatch.setattr(shop.settings, "media_dir", str(media))
    database.add(AppSetting(key="app_logo", value="/media/../secret.txt"))
    await database.commit()
    await shop._replace_branding_file(database, "app_logo", "/media/new.png")
    assert outside.read_text() == "keep me", "a crafted path never leaves the media folder"
    assert not (media / "secret.txt").exists(), "only the file name is used"


def test_admin_enterprise_view_compiles_as_jsx_and_keeps_labels():
    admin = (ROOT / "admin/src/main.tsx").read_text()
    assert "<Корпоративный контур" not in admin
    assert "<Корпоративный d={d}" in admin
    for label in ["Корпоративный контур", "Брендинг панели", "Переключить тему", "Операции", "Аналитика", "Инциденты", "Провайдеры", "Клиенты", "Функции", "Ключи доступа", "24/7 мониторинг", "Campaign Manager", "Rules Engine", "мультиустройства", "Trial", "Личный кабинет"]:
        assert label in admin or label in (ROOT / "admin/src/i18n.tsx").read_text()
    assert '"status"' in admin and '"deployments"' in admin and '"notifications"' in admin
    assert "CabinetCMS" in admin
    style = (ROOT / "admin/src/style.css").read_text()
    assert "--accent:" in style
    assert "Inter" in style
    assert "html[data-theme=\"light\"]" in style
    assert "--surface:" in style


def test_interfaces_have_russian_and_english_catalogs():
    admin_i18n = (ROOT / "admin/src/i18n.tsx").read_text()
    from frontend_sources import cabinet_i18n, miniapp_sources
    mini_i18n = cabinet_i18n()
    mini = miniapp_sources()
    assert "export type Lang = \"ru\" | \"en\"" in admin_i18n
    assert "Sign in" in admin_i18n and "Войти" in admin_i18n
    assert "Referral program" in mini_i18n and "Реферальная программа" in mini
    assert "Автопродление" in mini
    from app import bot
    assert bot._tr("en", "welcome", name="Corgi") == "Welcome to Corgi!"
    assert bot._tr("ru", "welcome", name="Корги") == "Добро пожаловать в Корги!"
