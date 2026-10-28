"""Bot section banners: defaults, admin overrides, Telegram delivery and fallbacks."""
from pathlib import Path
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app import bot_banners
from app.config import settings
from app.models import AppSetting, AuditLog, BotMenuItem
from test_subscription_commerce import database

ADMIN = SimpleNamespace(email="root@example.test", role="admin")


def image_upload(size=(900, 450), fmt="PNG", mode="RGBA", name="banner.png", content_type="image/png"):
    buf = BytesIO()
    Image.new(mode, size, (200, 120, 40, 255) if mode == "RGBA" else (200, 120, 40)).save(buf, fmt)
    buf.seek(0)
    return UploadFile(file=buf, filename=name, headers=Headers({"content-type": content_type}))


def test_every_section_ships_a_readable_default_banner():
    for key in bot_banners.SECTIONS:
        path = bot_banners.default_path(key)
        assert path is not None, key
        with Image.open(path) as im:
            # Bot and Mini App banners are 2:1; the dark app banners (app-*) are 2.5:1.
            assert im.format == "JPEG" and im.size == ((1280, 512) if key.startswith("app-") else (1280, 640)), key
        assert path.stat().st_size < 200_000


def test_resolution_order_custom_legacy_default_hidden(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    (tmp_path / "bot-banner-buy-x.jpg").write_bytes(b"jpeg")
    assert bot_banners.resolve("buy", {})[0] == "default"
    assert bot_banners.resolve("buy", {"bot_banner:buy": "/media/bot-banner-buy-x.jpg"})[:2] == ("custom", tmp_path / "bot-banner-buy-x.jpg")
    assert bot_banners.resolve("start", {"bot_start_image": "/media/old.jpg"}) == ("custom", None, "/media/old.jpg")
    assert bot_banners.resolve("buy", {"bot_banner_off:buy": "1"})[0] == "hidden"
    assert bot_banners.resolve("buy", {"bot_banners_enabled": "0"})[0] == "hidden"
    assert bot_banners.resolve("menu-7", {})[0] == "none"
    assert not bot_banners.valid_key("../etc") and not bot_banners.valid_key("menu-0") and bot_banners.valid_key("menu-12")


def test_uploads_are_reencoded_and_bounded():
    data = bot_banners.normalize_image(image_upload().file.read())
    with Image.open(BytesIO(data)) as im:
        assert im.format == "JPEG" and im.mode == "RGB"
    big = BytesIO(); Image.new("RGB", (4000, 2000)).save(big, "PNG")
    with Image.open(BytesIO(bot_banners.normalize_image(big.getvalue()))) as im:
        assert max(im.size) == bot_banners.MAX_SIDE
    with pytest.raises(HTTPException):
        bot_banners.normalize_image(b"<svg onload=alert(1)>")
    strip = BytesIO(); Image.new("RGB", (4200, 100)).save(strip, "PNG")
    with pytest.raises(HTTPException):
        bot_banners.normalize_image(strip.getvalue())


class FakeMessage:
    def __init__(self, photo=False, text="old", fail_photo=False):
        self.calls = []
        self.photo = [SimpleNamespace(file_id="old")] if photo else None
        self.text = None if photo else text
        self.fail_photo = fail_photo

    async def answer_photo(self, **kwargs):
        self.calls.append(("photo", kwargs))
        if self.fail_photo:
            raise RuntimeError("Bad Request: wrong file")
        return SimpleNamespace(photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="FILE-ID")])

    async def answer(self, text, **kwargs):
        self.calls.append(("text", text, kwargs))
        return SimpleNamespace(photo=None)

    async def edit_media(self, **kwargs):
        self.calls.append(("edit_media", kwargs))
        return SimpleNamespace(photo=[SimpleNamespace(file_id="EDITED")])

    async def edit_text(self, text, **kwargs):
        self.calls.append(("edit_text", text, kwargs))
        return True


@pytest.mark.asyncio
async def test_section_is_sent_as_photo_with_caption_and_buttons(monkeypatch):
    async def banner(key, fallback=None):
        return ("FILE", "cache-" + key)
    monkeypatch.setattr(bot_banners, "banner_for", banner)
    msg = FakeMessage()
    await bot_banners.send_section(msg, "buy", "<b>Тарифы</b>", "MARKUP")
    kind, kwargs = msg.calls[0]
    assert kind == "photo" and kwargs["caption"] == "<b>Тарифы</b>" and kwargs["reply_markup"] == "MARKUP" and kwargs["parse_mode"] == "HTML"
    assert bot_banners._file_ids["cache-buy"] == "FILE-ID"

    long = FakeMessage()
    await bot_banners.send_section(long, "buy", "x" * 1500, "MARKUP")
    assert [c[0] for c in long.calls] == ["photo", "text"] and "caption" not in long.calls[0][1]
    assert long.calls[1][2]["reply_markup"] == "MARKUP"


@pytest.mark.asyncio
async def test_navigation_edits_the_banner_message_in_place(monkeypatch):
    async def banner(key, fallback=None):
        return ("FILE", "c")
    monkeypatch.setattr(bot_banners, "banner_for", banner)
    msg = FakeMessage(photo=True)
    await bot_banners.send_section(msg, "menu-3", "Папка", "MARKUP", fallback="menu", edit=True)
    assert msg.calls[0][0] == "edit_media" and msg.calls[0][1]["reply_markup"] == "MARKUP"
    assert msg.calls[0][1]["media"].caption == "Папка"


@pytest.mark.asyncio
async def test_banner_failures_and_hidden_banners_fall_back_to_text(monkeypatch):
    async def banner(key, fallback=None):
        return ("FILE", "broken")
    monkeypatch.setattr(bot_banners, "banner_for", banner)
    msg = FakeMessage(fail_photo=True)
    await bot_banners.send_section(msg, "buy", "Тарифы", "MARKUP")
    assert [c[0] for c in msg.calls] == ["photo", "text"]

    async def none(key, fallback=None):
        return None
    monkeypatch.setattr(bot_banners, "banner_for", none)
    plain = FakeMessage(text="Меню")
    await bot_banners.send_section(plain, "menu", "Меню 2", "MARKUP", edit=True)
    assert plain.calls[0][0] == "edit_text"


@pytest.mark.asyncio
async def test_admin_uploads_resets_and_hides_banners(database, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    folder = BotMenuItem(title="Инструкции", action="", item_type="folder")
    link = BotMenuItem(title="Сайт", action="https://example.com", item_type="url")
    database.add_all([folder, link, AppSetting(key="bot_start_image", value="/media/bot-start-old.jpg")])
    (tmp_path / "bot-start-old.jpg").write_bytes(b"old")
    await database.commit()

    listing = await bot_banners.list_banners(database, ADMIN)
    keys = {s["key"]: s for s in listing["sections"]}
    assert set(keys) == set(bot_banners.SECTIONS) and keys["buy"]["source"] == "default"
    assert keys["buy"]["url"] == "/api/bot/banners/default/buy.jpg"
    assert keys["start"]["source"] == "custom"  # legacy /start image is honoured
    assert [m["key"] for m in listing["menu"]] == [f"menu-{folder.id}"]

    up = await bot_banners.upload_banner("start", image_upload(), database, ADMIN)
    assert up["url"].startswith("/media/bot-banner-start-") and (tmp_path / up["url"].rsplit("/", 1)[1]).is_file()
    assert not (tmp_path / "bot-start-old.jpg").exists()
    up2 = await bot_banners.upload_banner("start", image_upload(fmt="JPEG", mode="RGB", content_type="image/jpeg"), database, ADMIN)
    assert not (tmp_path / up["url"].rsplit("/", 1)[1]).exists()  # replaced file removed

    with pytest.raises(HTTPException) as bad:
        await bot_banners.upload_banner(f"menu-{link.id}", image_upload(), database, ADMIN)
    assert bad.value.status_code == 404
    with pytest.raises(HTTPException):
        await bot_banners.upload_banner("buy", image_upload(content_type="image/svg+xml"), database, ADMIN)
    await bot_banners.upload_banner(f"menu-{folder.id}", image_upload(), database, ADMIN)

    await bot_banners.banner_visibility("buy", bot_banners.Visibility(hidden=True), database, ADMIN)
    listing = await bot_banners.list_banners(database, ADMIN)
    keys = {s["key"]: s for s in listing["sections"]}
    assert keys["buy"]["source"] == "hidden" and keys["buy"]["hidden"] and keys["buy"]["url"]
    assert listing["menu"][0]["source"] == "custom"

    await bot_banners.reset_banner("start", database, ADMIN)
    await bot_banners.reset_banner("buy", database, ADMIN)
    keys = {s["key"]: s for s in (await bot_banners.list_banners(database, ADMIN))["sections"]}
    assert keys["start"]["source"] == "default" and keys["buy"]["source"] == "default"
    assert not (tmp_path / up2["url"].rsplit("/", 1)[1]).exists()

    await bot_banners.banners_enabled(bot_banners.Enabled(enabled=False), database, ADMIN)
    assert (await bot_banners.list_banners(database, ADMIN))["enabled"] is False
    actions = {a for (a,) in (await database.execute(__import__("sqlalchemy").select(AuditLog.action))).all()}
    assert {"content.bot.banner.updated", "content.bot.banner.reset", "content.bot.banner.hidden", "content.bot.banners.disabled"} <= actions


@pytest.mark.asyncio
async def test_default_banner_route_serves_only_known_files():
    resp = await bot_banners.default_banner("support.jpg")
    assert resp.media_type == "image/jpeg"
    for name in ("../models.py", "support.png", "nope.jpg"):
        with pytest.raises(HTTPException):
            await bot_banners.default_banner(name)


@pytest.mark.asyncio
async def test_deleting_a_menu_button_removes_its_banner(database, tmp_path, monkeypatch):
    from app import main
    from sqlalchemy import select
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    folder = BotMenuItem(title="Папка", action="", item_type="folder")
    database.add(folder); await database.commit()
    up = await bot_banners.upload_banner(f"menu-{folder.id}", image_upload(), database, ADMIN)
    await main.admin_menu_delete(folder.id, database, ADMIN)
    assert not (tmp_path / up["url"].rsplit("/", 1)[1]).exists()
    assert (await database.scalar(select(AppSetting).where(AppSetting.key == f"bot_banner:menu-{folder.id}"))) is None


def test_generator_covers_every_banner_and_new_sections_have_their_own():
    import ast
    from app.app_config import SECTION_BANNERS
    source = (Path(__file__).resolve().parents[1] / "scripts/bot-banners/render.py").read_text()
    tree = ast.parse(source)
    sections = next(n.value for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SECTIONS")
    app_sections = next(n.value for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "APP_SECTIONS")
    rendered = {k.value for k in sections.keys}
    rendered_app = {k.value for k in app_sections.keys}
    # 29 bot and Mini App banners (v28.37.0: contest, stats, channels, guest) plus 16 banners of the app sections.
    assert rendered | rendered_app == set(bot_banners.SECTIONS) and len(rendered) == 29 and len(rendered_app) == 16
    assert all(k.startswith("app-") for k in rendered_app) and not any(k.startswith("app-") for k in rendered)
    # Every app section has its own sticker.
    app_stickers = [v.elts[2].value for v in app_sections.values]
    assert len(set(app_stickers)) == len(app_stickers)
    assert SECTION_BANNERS["family"] == "family" and SECTION_BANNERS["status"] == "status"
    # No picture carries the old slogan or the word VPN in its title or caption.
    for key in [*sections.values, *app_sections.values]:
        title, caption = key.elts[0].value, key.elts[1].value
        assert "VPN" not in title + caption and "Гав" not in title + caption
    assert '"privacy"' not in source.split("CATALOG = {", 1)[1].split("}", 1)[0]
