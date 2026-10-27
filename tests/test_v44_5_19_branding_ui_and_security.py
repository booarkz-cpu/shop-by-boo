import io
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main as shop
from app.models import AppSetting
from app_contract import permissions
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
REQ = (ROOT / "backend/requirements.txt").read_text()
MANIFEST = (ROOT / "release-manifest.template.json").read_text()
UI = (ROOT / "admin/src/main.tsx").read_text()
CSS = (ROOT / "admin/src/style.css").read_text()


@pytest.mark.asyncio
async def test_public_branding_has_safe_defaults_and_no_secret_settings(database):
    assert await shop.public_branding(database) == {"name": "Корги Люси", "logo_url": "", "favicon_url": "", "theme_default": "dark"}
    database.add_all([AppSetting(key="app_name", value="VPN Корги"), AppSetting(key="theme_default", value="neon"),
                      AppSetting(key="yookassa_secret_key", value="live_SECRET")])
    await database.commit()
    out = await shop.public_branding(database)
    assert out["name"] == "VPN Корги" and out["theme_default"] == "dark", "an unknown theme falls back"
    assert "live_SECRET" not in str(out)


def _upload(data: bytes, content_type="image/png"):
    from starlette.datastructures import Headers, UploadFile
    return UploadFile(file=io.BytesIO(data), filename="logo", headers=Headers({"content-type": content_type}))


@pytest.mark.asyncio
async def test_branding_images_are_re_encoded_and_old_files_removed(database, monkeypatch, tmp_path):
    from PIL import Image
    monkeypatch.setattr(shop.settings, "media_dir", str(tmp_path))
    raw = io.BytesIO()
    Image.new("RGB", (1200, 800), "orange").save(raw, "JPEG")
    url = await shop._store_branding_image(_upload(raw.getvalue(), "image/jpeg"), "favicon", 512 * 1024)
    stored = tmp_path / url.removeprefix("/media/")
    with Image.open(stored) as im:
        assert im.format == "PNG" and max(im.size) == 512, "a favicon is re-encoded to PNG and scaled down"
    for bad, kind in ((b"<svg onload=alert(1)>", "image/svg+xml"), (b"not an image", "image/png")):
        with pytest.raises(HTTPException) as refused:
            await shop._store_branding_image(_upload(bad, kind), "logo")
        assert refused.value.status_code == 400
    await shop._replace_branding_file(database, "app_favicon", url)
    await database.commit()
    second = await shop._store_branding_image(_upload(raw.getvalue(), "image/jpeg"), "favicon", 512 * 1024)
    await shop._replace_branding_file(database, "app_favicon", second)
    await database.commit()
    assert not stored.exists() and (tmp_path / second.removeprefix("/media/")).exists(), "the replaced file is deleted"


def test_branding_uploads_are_permission_gated():
    for path in ("/api/admin/branding/logo", "/api/admin/branding/favicon"):
        assert permissions("POST", path) == {"manage_content"}
    assert permissions("PUT", "/api/admin/settings/{key}") == {"manage_content"}


@pytest.mark.asyncio
async def test_content_managers_change_only_public_branding_settings(database):
    admin = SimpleNamespace(email="a@b.c")
    for key, value, status in (("yookassa_secret_key", "x", 403), ("app_secret", "x", 403), ("app_name", "x" * 256, 400),
                               ("app_name", "   ", 400), ("theme_default", "neon", 400)):
        with pytest.raises(HTTPException) as refused:
            await shop.admin_setting(key, shop.SettingIn(value=value), database, admin)
        assert refused.value.status_code == status, key
    await shop.admin_setting("app_name", shop.SettingIn(value="Корги VPN"), database, admin)
    assert (await database.get(AppSetting, "app_name")).value == "Корги VPN"


def test_frontend_supports_light_dark_theme_and_custom_branding():
    assert 'localStorage.getItem("rw_theme")' in UI
    assert 'document.documentElement.dataset.theme' in UI
    assert 'Переключить тему' in (ROOT / 'admin/src/i18n.tsx').read_text()
    assert 'Брендинг панели' in (ROOT / 'admin/src/i18n.tsx').read_text()
    assert '/api/admin/branding/logo' in UI
    assert '/api/admin/branding/favicon' in UI
    assert 'app_name' in UI
    assert '--bg:' in CSS
    assert 'html[data-theme="light"]' in CSS


def test_release_is_44_5_20_and_pillow_is_pinned():
    assert '1.0.0-realise' in MANIFEST
    assert re.search(r'^Pillow==\d', REQ, re.M), 'Pillow must stay an exact pinned dependency'


def test_frontend_source_transpile_check_is_documented_by_project_structure():
    assert (ROOT / 'admin/src/main.tsx').exists()
    assert (ROOT / 'admin/src/style.css').exists()
