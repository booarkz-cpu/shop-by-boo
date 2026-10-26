"""v28.29.0: FAQ, rules, privacy policy and public offer edited by administrators and shown in
the Mini App, the personal cabinet and the bot."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app import app_config, bot, info_pages, main
from app.config import settings
from app.menu_tree import telegram_keyboard
from app.models import AuditLog, BotMenuItem
from app.security import PERMISSIONS, require_permission
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="root@example.test", role="admin")


class Req:
    def __init__(self, headers=None):
        self.headers = headers or {}


def page(**ru):
    return info_pages.PageIn(ru=info_pages.Translation(**ru))


@pytest.fixture(autouse=True)
def no_providers(monkeypatch):
    async def public_config(db):
        return {"app_name": "Корги Люси", "payment_providers": ["yookassa"], "trial_days": 3}
    monkeypatch.setattr(main, "public_config", public_config)
    monkeypatch.setattr(settings, "bot_username", "corgi_bot")


def test_only_administrators_may_change_documents():
    assert "legal.write" in PERMISSIONS["admin"]
    assert "legal.write" not in PERMISSIONS["operator"] and "legal.write" not in PERMISSIONS["viewer"]


@pytest.mark.asyncio
async def test_operator_is_refused_by_the_permission_check():
    check = require_permission("legal.write")
    with pytest.raises(HTTPException) as refused:
        await check(admin=SimpleNamespace(role="operator"))
    assert refused.value.status_code == 403


@pytest.mark.asyncio
async def test_save_versions_audits_and_publishes_in_every_language(database):
    db = database
    saved = await info_pages.admin_save("rules", page(body="## Общее\n- Один аккаунт на человека\nНе нарушайте **закон**."), db, ADMIN)
    assert saved["version"] == 1 and saved["updated_by"] == "root@example.test"
    again = await info_pages.admin_save("rules", page(title="Правила сервиса", body="Новый текст"), db, ADMIN)
    assert again["version"] == 2
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "info_page.saved"))).scalars().all()
    assert [a.target for a in audit] == ["rules", "rules"]
    ru = await info_pages.public_page("rules", Req(), "ru", db)
    assert ru["title"] == "Правила сервиса" and ru["body"] == "Новый текст" and ru["version"] == 2
    en = await info_pages.public_page("rules", Req(), "en", db)  # no English text: Russian is shown
    assert en["lang"] == "ru" and en["body"] == "Новый текст"
    listed = await info_pages.public_list(Req({"accept-language": "uk-UA"}), None, db)
    assert [p["kind"] for p in listed] == ["rules"]


@pytest.mark.asyncio
async def test_translations_disabled_and_empty_documents(database):
    db = database
    body = info_pages.PageIn(ru=info_pages.Translation(body="Оферта"), en=info_pages.Translation(title="Offer", body="Offer text"))
    await info_pages.admin_save("offer", body, db, ADMIN)
    assert (await info_pages.public_page("offer", Req(), "en", db))["title"] == "Offer"
    assert (await info_pages.public_page("offer", Req(), "uk", db))["title"] == "Публичная оферта"
    await info_pages.admin_save("offer", info_pages.PageIn(enabled=False, ru=info_pages.Translation(body="Оферта")), db, ADMIN)
    with pytest.raises(HTTPException) as hidden:
        await info_pages.public_page("offer", Req(), "ru", db)
    assert hidden.value.status_code == 404
    with pytest.raises(HTTPException) as empty:
        await info_pages.admin_save("privacy", page(body="   "), db, ADMIN)
    assert empty.value.status_code == 400
    with pytest.raises(ValidationError):
        info_pages.Translation(body="x" * (info_pages.MAX_BODY + 1))


@pytest.mark.asyncio
async def test_documents_appear_in_the_mini_app_and_cabinet_config(database):
    db = database
    await info_pages.admin_save("faq", page(items=[{"question": "Как подключиться?", "answer": "Откройте «Подключение»."}]), db, ADMIN)
    await info_pages.admin_save("privacy", page(body="Мы храним только email."), db, ADMIN)
    cfg = await app_config.build_config(db, Req())
    docs = [p for p in cfg["info"]["pages"] if p.get("source") == "info"]
    assert [(p["kind"], p["title"]) for p in docs] == [("faq", "Частые вопросы"), ("privacy", "Политика конфиденциальности")]
    assert cfg["banner_keys"]["faq"] == "faq" and cfg["banner_keys"]["offer"] == "offer"
    assert any(p["slug"] == "info" for p in cfg["navigation"]) or cfg["info"]["pages"]


def test_telegram_text_is_escaped_and_formatted():
    html = info_pages.telegram_html({"title": "Правила <beta>", "body": "## Раздел\n- пункт & ещё\n**важно** <script>",
                                     "items": [{"question": "Вопрос?", "answer": "Ответ"}]})
    assert html.startswith("<b>Правила &lt;beta&gt;</b>")
    assert "<b>Раздел</b>" in html and "• пункт &amp; ещё" in html and "<b>важно</b> &lt;script&gt;" in html
    assert "<b>❓ Вопрос?</b>\nОтвет" in html


def test_long_documents_are_split_for_telegram():
    text = "\n\n".join(f"Абзац {i} " + "слово " * 120 for i in range(20))
    parts = info_pages.split_message(text)
    assert len(parts) > 1 and all(len(p) <= 3900 for p in parts)
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")


def test_bot_menu_has_a_document_button_type():
    rows = [BotMenuItem(id=1, title="Правила", action="rules", item_type="info", enabled=True, sort_order=0, style="default", icon=""),
            BotMenuItem(id=2, title="Плохо", action="secret", item_type="info", enabled=True, sort_order=1, style="default", icon="")]
    markup = telegram_keyboard(rows, [])
    assert [[b.callback_data for b in row] for row in markup.inline_keyboard] == [["info:rules"]]


class Message:
    def __init__(self):
        self.sent = []
        self.photo = None
        self.text = None

    async def answer(self, text, **kw):
        self.sent.append(("text", text, kw.get("reply_markup")))
        return self


@pytest.mark.asyncio
async def test_bot_shows_the_document_with_its_banner(database, monkeypatch):
    db = database
    await info_pages.admin_save("rules", page(body="Правило " * 1500), db, ADMIN)
    monkeypatch.setattr(bot, "engine", db.bind)
    sections = []

    async def send_section(message, key, text, markup=None, **kw):
        sections.append((key, text, kw.get("fallback")))
    monkeypatch.setattr(bot, "send_section", send_section)
    msg = Message()
    await bot.show_info(msg, "rules", "ru")
    assert sections[0][0] == "rules" and sections[0][2] == "info" and sections[0][1].startswith("<b>Правила</b>")
    assert msg.sent and msg.sent[-1][2] is not None  # the back button rides on the last part
    msg2 = Message()
    await bot.show_info(msg2, "offer", "ru")  # not published
    assert msg2.sent[0][1] == bot.INFO_EMPTY["ru"]


@pytest.mark.asyncio
async def test_document_banner_is_the_same_everywhere_and_follows_the_editor(database):
    """v28.31.0: the banner of a document comes with the document to the cabinet, Mini App and apps."""
    from app import bot_banners
    from app.models import AppSetting
    db = database
    await info_pages.admin_save("privacy", page(body="Мы храним только email."), db, ADMIN)
    assert (await info_pages.public_page("privacy", Req(), "ru", db))["banner"] == "/api/bot/banners/default/privacy.jpg"
    listed = await info_pages.public_list(Req(), "ru", db)
    assert listed[0]["banner"] == "/api/bot/banners/default/privacy.jpg"
    # An upload in the document editor (the same endpoint as «Баннеры бота») replaces it everywhere.
    db.add(AppSetting(key=bot_banners.PREFIX + "privacy", value="/media/bot-banner-privacy-1.jpg"))
    await db.commit()
    assert (await info_pages.public_page("privacy", Req(), "en", db))["banner"] == "/media/bot-banner-privacy-1.jpg"
    admin = await info_pages.admin_list(db, ADMIN)
    row = next(p for p in admin["pages"] if p["kind"] == "privacy")
    assert row["banner"]["custom"] is True and row["banner"]["default_url"].endswith("/privacy.jpg")
    assert admin["can_edit_banners"] is True
    # Hidden banner: the document is shown without a picture.
    db.add(AppSetting(key=bot_banners.OFF_PREFIX + "privacy", value="1"))
    await db.commit()
    assert (await info_pages.public_page("privacy", Req(), "ru", db))["banner"] == ""
