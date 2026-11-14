"""Brand texts as defaults (owner's decision 4 of 2026-11-12, «да, везде»): one source, the same words everywhere."""
import re
from pathlib import Path

import pytest

from app import brand_copy, bot_texts
from test_subscription_commerce import database  # noqa: F401 — the shared database fixture

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs/BRAND_COPY.md").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_texts_are_the_ones_of_the_brand_document():
    doc = _flat(DOC)
    assert brand_copy.TITLE["ru"] in doc
    assert brand_copy.TAGLINE["ru"] in doc
    for lang in ("ru", "en"):
        assert _flat(brand_copy.FULL[lang]) in doc
        assert brand_copy.MAINTENANCE[lang] in doc
    assert brand_copy.SHORT["en"] in doc
    # The Russian short text of the document names SBP and «Мир»; the default does not: the methods are the owner's.
    assert "СБП" not in brand_copy.SHORT["ru"] and "Visa" not in str(brand_copy.PUBLIC) and "Mastercard" not in str(brand_copy.PUBLIC)


def test_every_language_has_every_text():
    for key in ("name", "tagline", "short", "full", "maintenance"):
        assert set(brand_copy.PUBLIC[key]) == {"ru", "en", "uk"}, key
        assert all(v.strip() for v in brand_copy.PUBLIC[key].values()), key


def test_the_english_name_is_one_everywhere():
    assert bot_texts.DEFAULTS["shop_name"][2] == brand_copy.NAME["en"] == "Corgi Lusi"
    for path in (ROOT / "backend/app").glob("*.py"):
        assert "Corgi Lucy" not in path.read_text(encoding="utf-8"), path.name


def test_bot_welcome_carries_the_tagline_in_three_languages():
    for lang, index in (("ru", 1), ("en", 2), ("uk", 3)):
        assert brand_copy.TAGLINE[lang] in bot_texts.DEFAULTS["welcome"][index]
        assert "{name}" in bot_texts.DEFAULTS["welcome"][index]


def test_cabinet_maintenance_screen_uses_the_brand_text():
    stickers = (ROOT / "apps/user-cabinet/src/stickers.tsx").read_text(encoding="utf-8")
    assert f'MAINTENANCE_TEXT = "{brand_copy.MAINTENANCE["ru"]}"' in stickers


@pytest.mark.asyncio
async def test_public_config_hands_out_the_brand_and_keeps_the_owners_subtitle(database):
    from app.main import public_config
    from app.models import AppSetting
    out = await public_config(database)
    assert out["brand"]["tagline"]["ru"] == brand_copy.TAGLINE["ru"] and out["miniapp"]["subtitle"] == brand_copy.TAGLINE["ru"]
    database.add(AppSetting(key="miniapp_subtitle", value="Своя строка"))
    await database.commit()
    assert (await public_config(database))["miniapp"]["subtitle"] == "Своя строка"


def test_maintenance_answer_carries_the_brand_text():
    import json
    from app.main import _maintenance_response
    body = json.loads(_maintenance_response().body)
    assert body["detail"] == "Service is in maintenance mode" and body["message"] == brand_copy.MAINTENANCE
