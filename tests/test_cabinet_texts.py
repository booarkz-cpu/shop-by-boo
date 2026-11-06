"""BACKLOG A4 (v28.88.0): the web cabinet's texts are replaced from the admin panel, per language, without a rebuild."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app import cabinet_texts
from app.models import AppSetting, AuditLog
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
ADMIN = SimpleNamespace(email="owner@corgi.test", role="admin")
KEY = "Личный кабинет"


def test_the_list_follows_the_cabinet_source():
    """assets/cabinet_strings.json is generated from cabinet/src/i18n.tsx — a new text in the cabinet appears in the admin."""
    done = subprocess.run([sys.executable, str(ROOT / "scripts/generate-cabinet-strings.py"), "--check"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    texts = cabinet_texts.defaults()
    assert len(texts) > 150
    assert texts[KEY] == {"ru": KEY, "en": "Account", "uk": "Особистий кабінет"}
    only_en = next(k for k, v in json.loads(cabinet_texts.STRINGS_FILE.read_text()).items() if not v["uk"])
    assert texts[only_en]["uk"] == texts[only_en]["en"], "an untranslated Ukrainian text is shown in English, as in the cabinet"


@pytest.mark.asyncio
async def test_owner_texts_are_saved_per_language_and_served_to_the_cabinet(database):
    db = database
    assert await cabinet_texts.public_texts(db) == {}, "nothing stored: the cabinet keeps its own texts"
    listed = await cabinet_texts.admin_texts(db, ADMIN)
    assert listed["languages"] == ["ru", "en", "uk"] and any(i["key"] == KEY for i in listed["texts"])

    out = await cabinet_texts.put_texts(cabinet_texts.TextsIn(lang="ru", texts={KEY: "  Кабинет корги  ", "Тарифы": "Тарифы"}), db, ADMIN)
    assert out == {"lang": "ru", "custom": 1}, "a text equal to the default is not stored"
    await cabinet_texts.put_texts(cabinet_texts.TextsIn(lang="en", texts={KEY: "Corgi account"}), db, ADMIN)
    assert await cabinet_texts.public_texts(db) == {"ru": {KEY: "Кабинет корги"}, "en": {KEY: "Corgi account"}}
    item = next(i for i in (await cabinet_texts.admin_texts(db, ADMIN))["texts"] if i["key"] == KEY)
    assert item["custom"] == {"ru": "Кабинет корги", "en": "Corgi account"} and item["default"]["en"] == "Account"

    # An empty field returns the default; the other language is untouched.
    await cabinet_texts.put_texts(cabinet_texts.TextsIn(lang="ru", texts={KEY: ""}), db, ADMIN)
    assert await cabinet_texts.public_texts(db) == {"en": {KEY: "Corgi account"}}
    actions = (await db.execute(select(AuditLog.action))).scalars().all()
    assert actions.count("cabinet.texts.updated") == 3


@pytest.mark.asyncio
async def test_unknown_or_oversized_texts_are_refused(database):
    db = database
    for texts in ({"Нет такого текста": "x"}, {KEY: "x" * 501}):
        with pytest.raises(HTTPException) as err:
            await cabinet_texts.put_texts(cabinet_texts.TextsIn(lang="uk", texts=texts), db, ADMIN)
        assert err.value.status_code == 422
    with pytest.raises(ValidationError):
        cabinet_texts.TextsIn(lang="de", texts={KEY: "Konto"})
    assert await db.get(AppSetting, cabinet_texts.SETTING) is None, "a refused save stores nothing"
    # A damaged or outdated stored value never breaks the cabinet: unknown keys are dropped.
    db.add(AppSetting(key=cabinet_texts.SETTING, value=json.dumps({"ru": {KEY: "Свой", "Удалённый текст": "x"}, "de": {KEY: "y"}})))
    await db.commit()
    assert await cabinet_texts.public_texts(db) == {"ru": {KEY: "Свой"}}
    row = await db.get(AppSetting, cabinet_texts.SETTING)
    row.value = "not json"
    await db.commit()
    assert await cabinet_texts.public_texts(db) == {}


# The cabinet side (the owner's text wins, the rest keeps the cabinet's tables): cabinet/src/cabinet-texts.test.tsx (vitest).
