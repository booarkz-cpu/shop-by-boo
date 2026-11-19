"""Extraction regressions; the CI lint job additionally runs the real RU/EN/UK dictionaries."""
import json
import sys
import xml.etree.ElementTree as ET
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


@pytest.mark.parametrize("app", ["vpn-shop", "lucy-admin"])
def test_native_android_catalogs_have_matching_ru_en_uk_keys(app):
    resource_root = ROOT / "apps" / app / "android/app/src/main/res"
    catalogs = {}
    for qualifier in ("values", "values-en", "values-uk"):
        path = resource_root / qualifier / "strings.xml"
        catalogs[qualifier] = {
            element.attrib["name"] for element in ET.parse(path).getroot()
            if element.tag in {"string", "plurals", "string-array"}
        }
    assert catalogs["values"] == catalogs["values-en"] == catalogs["values-uk"]


def test_vpn_shop_native_android_labels_are_localized():
    resource_root = ROOT / "apps/vpn-shop/android/app/src/main/res"
    expected = {
        "values": {"diagnostics": "Диагностика", "privacy": "Конфиденциальность"},
        "values-uk": {"diagnostics": "Діагностика", "privacy": "Конфіденційність"},
    }
    for qualifier, labels in expected.items():
        actual = {
            element.attrib["name"]: element.text
            for element in ET.parse(resource_root / qualifier / "strings.xml").getroot()
        }
        assert {key: actual[key] for key in labels} == labels


def test_lucy_admin_uk_critical_labels_are_complete():
    paths = [
        ROOT / "apps/lucy-admin/android/app/src/main/assets/l10n.json",
        ROOT / "apps/lucy-admin/ios/VpnShopAdmin/l10n.json",
    ]
    catalogs = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    assert catalogs[0] == catalogs[1]
    expected = {
        "otp": "Код 2FA",
        "https_required": (
            "Укажіть адресу API, що починається з https://. Локальний http:// дозволено лише "
            "для localhost, 127.0.0.1 і 10.0.2.2."
        ),
        "all_telegram": "Усі користувачі з Telegram",
        "broadcast_text": "Текст HTML-розсилки",
        "broadcast_hint": (
            "Чергу доставляє Telegram-бот. Повторна спроба продовжується зі збереженого "
            "лічильника."
        ),
        "restricted": "Доступ обмежено",
        "cleared": "Обмеження знято",
        "broadcast_retried": "Розсилку повернуто до черги",
        "password_short": "Пароль має містити щонайменше 8 символів",
        "cash_queue": "Черга платежів",
    }
    assert {key: catalogs[0]["uk"][key] for key in expected} == expected


def test_missing_engine_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        Engine(str(tmp_path / "does-not-exist")).unknown("ru", {"подключение"})
