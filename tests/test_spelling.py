"""Extraction regressions; the CI lint job additionally runs the real RU/EN/UK dictionaries."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit.check_spelling import Engine, resources, words  # noqa: E402


def test_tokens_keep_misspellings_and_strip_placeholders_urls_and_markup():
    assert words("Подклчение {server} https://example.org/path user@example.org "
                 "<b>Conect</b> %1$s " + "\x60код_сервера\x60") == {"Подклчение", "Conect"}
    assert words("VPN v2rayNG Коргі Люсі") == set()
    assert words("під’єднання") == {"під'єднання"}
    assert "Conect" in words("Conect")


def test_extracts_values_and_android_plural_text_but_not_resource_keys(tmp_path):
    for name in ("admin", "user"):
        path = tmp_path / "packages" / "localization" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({lang: {"not_prose_key": "connection"}
                                    for lang in ("ru", "en", "uk")}), encoding="utf-8")
    path = tmp_path / "apps/demo/android/app/src/main/res/values-uk/strings.xml"
    path.parent.mkdir(parents=True)
    path.write_text('<resources><string name="one">Підключення <b>готове</b></string>'
                    '<plurals name="many"><item quantity="one">День</item></plurals>'
                    '<string name="code" translatable="false">not_prose</string></resources>',
                    encoding="utf-8")
    entries = list(resources(tmp_path))
    assert len(entries) == 8
    assert entries[-2].language == "uk"
    assert entries[-2].text == "Підключення готове"
    assert entries[-1].key == "many[0]"
    assert all(entry.text != "not_prose_key" for entry in entries)


def test_missing_engine_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        Engine(str(tmp_path / "does-not-exist")).unknown("ru", {"подключение"})
