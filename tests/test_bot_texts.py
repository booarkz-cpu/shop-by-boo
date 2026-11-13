"""v28.72.0 (stage 13): every text of the Telegram bot on three languages, editable in the admin panel."""
import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import bot, bot_texts, telegram_bot
from app.models import AppSetting
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test", role="admin")
APP = Path(__file__).resolve().parents[1] / "backend" / "app"
CYRILLIC = re.compile("[А-Яа-яЁёІіЇїЄєҐґ]")
# Texts for the owner's admin panel (not for customers) stay Russian like the rest of the panel.
ALLOWED = {"BOT_TOKEN не задан"}


def _literals(path: Path):
    tree = ast.parse(path.read_text())
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.lineno, node.value


@pytest.mark.parametrize("name", ["bot.py", "bot_workspace.py"])
def test_the_bot_has_no_text_outside_the_registry(name):
    stray = [(line, text[:60]) for line, text in _literals(APP / name) if CYRILLIC.search(text) and text not in ALLOWED]
    assert stray == [], f"{name}: move these texts to bot_texts.DEFAULTS (ru/en/uk): {stray}"


def test_every_text_has_three_languages_with_the_same_placeholders():
    for key, (group, ru, en, uk) in bot_texts.DEFAULTS.items():
        assert group and ru.strip() and en.strip() and uk.strip(), key
        marks = [set(bot_texts.PLACEHOLDER.findall(x)) for x in (ru, en, uk)]
        assert marks[0] == marks[1] == marks[2], f"{key}: placeholders differ between languages"
        assert not CYRILLIC.search(en), f"{key}: the English text is not English"
        for text in (ru, en, uk):
            bot_texts.check_override(key, text)  # the defaults pass the owner's own rules


def test_override_rules_and_language():
    assert bot_texts.check_override("welcome", "  Привет из <b>{name}</b>!  ") == "Привет из <b>{name}</b>!"
    for bad in ("Привет {user}", "<script>alert(1)</script>{name}", "", "x" * 3501):
        with pytest.raises(ValueError):
            bot_texts.check_override("welcome", bad)
    with pytest.raises(ValueError):
        bot_texts.check_override("no_such_text", "x")
    message = lambda code: SimpleNamespace(from_user=SimpleNamespace(language_code=code))  # noqa: E731
    assert [bot._lang(message(c)) for c in ("uk", "en-US", "de", "ru")] == ["uk", "en", "ru", "ru"]
    assert bot._tr("en", "open") == "🛒 Open shop" and bot._tr("uk", "scope") == " для вибраних тарифів"


@pytest.mark.asyncio
async def test_owner_edits_texts_and_the_bot_uses_them(database):
    db = database
    listed = await telegram_bot.get_texts(db, ADMIN)
    assert len(listed["texts"]) == len(bot_texts.DEFAULTS) and listed["languages"] == ["ru", "en", "uk"]
    welcome = next(x for x in listed["texts"] if x["key"] == "welcome")
    assert welcome["placeholders"] == ["name"] and welcome["default"]["uk"].startswith("Ласкаво") and welcome["custom"] == {}

    out = await telegram_bot.put_texts(telegram_bot.TextsIn(lang="en", texts={"welcome": "Hi from <b>{name}</b>!", "plans_empty": "Soon!"}), db, ADMIN)
    assert out["custom"] == 2
    assert bot_texts.t("en", "welcome", name="Lucy") == "Hi from <b>Lucy</b>!"
    assert bot_texts.t("ru", "welcome", name="Люси").startswith("Добро пожаловать в Люси — свободный интернет"), "other languages keep their texts"
    stored = json.loads((await db.get(AppSetting, bot_texts.SETTING)).value)
    assert stored["en"] == {"welcome": "Hi from <b>{name}</b>!", "plans_empty": "Soon!"}

    with pytest.raises(HTTPException) as err:
        await telegram_bot.put_texts(telegram_bot.TextsIn(lang="en", texts={"welcome": "Hi {user}"}), db, ADMIN)
    assert err.value.status_code == 422 and "{user}" in err.value.detail
    await telegram_bot.put_texts(telegram_bot.TextsIn(lang="en", texts={"welcome": "", "plans_empty": bot_texts.default("en", "plans_empty")}), db, ADMIN)
    assert bot_texts.t("en", "welcome", name="Lucy") == bot_texts.default("en", "welcome").format(name="Lucy"), "an empty field or the default text resets it"
    assert (await telegram_bot.get_texts(db, ADMIN))["texts"][0]["custom"] == {}


@pytest.mark.asyncio
async def test_bot_answers_in_the_customers_language(database, monkeypatch):
    """/buy for an English and a Ukrainian Telegram user — the plans list in their language."""
    sent = []

    async def section(message, kind, text, markup=None, **kw):
        sent.append(text)
    monkeypatch.setattr(bot, "send_section", section)

    async def config():
        plan = SimpleNamespace(name="Lucy Mini", price=199, duration_days=30)
        return {}, [], [], [], [], [plan]
    monkeypatch.setattr(bot, "get_bot_config", config)
    for code in ("en", "uk"):
        message = SimpleNamespace(from_user=SimpleNamespace(id=1, language_code=code), chat=SimpleNamespace(type="private"), text="/buy")
        await bot.buy(message)
    assert sent[0].startswith("🛒 <b>Plans</b>") and "30 days" in sent[0]
    assert sent[1].startswith("🛒 <b>Тарифи</b>") and "30 дн." in sent[1]
