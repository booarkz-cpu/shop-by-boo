"""Layout of the Android and iOS apps: defaults, admin edits, validation and the public document."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app import bot_banners, mobile_layout
from app.models import AppSetting, AuditLog
from test_subscription_commerce import database

ADMIN = SimpleNamespace(email="root@example.test", role="admin")


class Req:
    def __init__(self, headers=None):
        self.headers = headers or {}


class Resp:
    def __init__(self):
        self.headers = {}


def sec(data, section_id):
    return next(s for s in data["sections"] if s["id"] == section_id)


def edited(**changes):
    data = mobile_layout.defaults().model_dump(mode="json")
    data.update(changes)
    return data


@pytest.mark.asyncio
async def test_defaults_describe_every_tab_with_buttons_and_banners(database):
    doc = await mobile_layout.resolve_layout(database, "ru")
    # The tab bar of the references: VPN in the middle, two sections on each side.
    assert doc["tabs"] == ["subscription", "premium", "vpn", "locations", "settings"]
    sections = {s["id"]: s for s in doc["sections"]}
    vpn = sections["vpn"]
    assert vpn["buttons"][0] == {"id": "connect", "label": "Подключить", "action": "connect", "target": "",
                                 "style": "primary", "icon": "power", "audience": "any"}
    # Every default section has its own Lusi banner shipped with the backend.
    for section in doc["sections"]:
        assert section["banner"] and section["banner"]["url"] == f"/api/bot/banners/default/app-{section['id']}.jpg", section["id"]
    # Buttons that need a link the administrator has not set are not sent at all.
    assert not any(b["action"] in ("cabinet", "telegram_channel") for s in doc["sections"] for b in s["buttons"])
    assert doc["texts"]["status_off"] == "VPN отключён"
    assert doc["theme"]["accent"] == "#FF8A1F"
    assert len(doc["version"]) == 16


@pytest.mark.asyncio
async def test_language_switches_labels_and_falls_back_to_russian(database):
    data = edited()
    sec(data, "vpn")["buttons"][0]["label"]["uk"] = ""
    await mobile_layout.admin_mobile_layout_save(mobile_layout.MobileLayout.model_validate(data), database, ADMIN)
    en = await mobile_layout.resolve_layout(database, "en")
    uk = await mobile_layout.resolve_layout(database, "uk")
    assert sec(en, "vpn")["buttons"][0]["label"] == "Connect"
    assert sec(uk, "vpn")["buttons"][0]["label"] == "Подключить"
    assert en["texts"]["status_off"] == "VPN is off" and en["version"] != uk["version"]
    assert mobile_layout.pick_lang("uk-UA") == "uk" and mobile_layout.pick_lang("de") == "ru"


@pytest.mark.asyncio
async def test_admin_edits_buttons_sections_and_banners(database):
    data = edited(cabinet_url="https://lk.example.com", telegram_channel="https://t.me/corgi_news")
    vpn = sec(data, "vpn")
    vpn["buttons"][0]["label"]["ru"] = "Включить защиту"
    vpn["buttons"][2]["visible"] = False
    vpn["banner"]["enabled"] = False
    data["sections"].append({"id": "promo", "kind": "custom", "enabled": True, "tab": False,
                             "title": {"ru": "Акция", "en": "", "uk": ""}, "subtitle": {"ru": "", "en": "", "uk": ""},
                             "body": {"ru": "Скидка 30% до конца месяца", "en": "", "uk": ""}, "icon": "gift",
                             "banner": {"enabled": True, "key": "promo", "link": "https://example.com/sale"},
                             "buttons": [{"id": "go", "label": {"ru": "Выбрать тариф", "en": "", "uk": ""}, "action": "open",
                                          "target": "premium", "style": "accent", "icon": "", "visible": True, "audience": "any"}]})
    data["texts"] = {"status_off": {"ru": "Защита выключена", "en": "", "uk": ""}}
    result = await mobile_layout.admin_mobile_layout_save(mobile_layout.MobileLayout.model_validate(data), database, ADMIN)
    preview = result["preview"]
    sections = {s["id"]: s for s in preview["sections"]}
    assert sections["vpn"]["buttons"][0]["label"] == "Включить защиту"
    assert "upgrade" not in [b["id"] for b in sections["vpn"]["buttons"]]
    assert sections["vpn"]["banner"] is None
    assert sections["promo"]["body"] == "Скидка 30% до конца месяца"
    assert sections["promo"]["banner"] == {"url": "/api/bot/banners/default/promo.jpg", "link": "https://example.com/sale"}
    assert "cabinet" in [b["action"] for b in sections["settings"]["buttons"]]
    assert preview["links"] == {"cabinet": "https://lk.example.com", "telegram_channel": "https://t.me/corgi_news"}
    assert preview["texts"]["status_off"] == "Защита выключена"
    audit = (await database.execute(select(AuditLog).where(AuditLog.action == "content.mobile_layout.updated"))).scalars().one()
    assert audit.actor == ADMIN.email

    await mobile_layout.admin_mobile_layout_reset(database, ADMIN)
    assert sec(await mobile_layout.resolve_layout(database, "ru"), "vpn")["buttons"][0]["label"] == "Подключить"


@pytest.mark.asyncio
async def test_uploaded_or_hidden_banner_follows_the_banner_registry(database):
    database.add(AppSetting(key=bot_banners.PREFIX + "app-vpn", value="/media/bot-banner-app-vpn-1.jpg"))
    database.add(AppSetting(key=bot_banners.OFF_PREFIX + "app-support", value="1"))
    await database.commit()
    sections = {s["id"]: s for s in (await mobile_layout.resolve_layout(database, "ru"))["sections"]}
    assert sections["vpn"]["banner"]["url"] == "/media/bot-banner-app-vpn-1.jpg"
    assert sections["support"]["banner"] is None
    layout = mobile_layout.defaults()
    layout.banners_enabled = False
    await mobile_layout.admin_mobile_layout_save(layout, database, ADMIN)
    assert all(s["banner"] is None for s in (await mobile_layout.resolve_layout(database, "ru"))["sections"])


@pytest.mark.parametrize("change, message", [
    (lambda d: sec(d, "vpn")["buttons"].append({**sec(d, "vpn")["buttons"][0]}), "Повторяется id кнопки"),
    (lambda d: sec(d, "vpn")["buttons"][1].update(target="nowhere"), "несуществующий раздел"),
    (lambda d: sec(d, "vpn")["buttons"][1].update(action="url", target="javascript:alert(1)"), "https://"),
    (lambda d: sec(d, "vpn")["buttons"][0].update(target="https://example.com"), "не принимает цель"),
    (lambda d: sec(d, "vpn")["buttons"][0].update(action="rm_rf"), "action"),
    (lambda d: sec(d, "vpn").update(enabled=False), "VPN нельзя выключить"),
    (lambda d: [s.update(tab=False) for s in d["sections"]], "от 2 до 5"),
    (lambda d: sec(d, "support").update(tab=True), "от 2 до 5"),
    (lambda d: d["sections"].append({**sec(d, "info")}), "Повторяется id раздела"),
    (lambda d: d["theme"].update(accent="orange"), "accent"),
    (lambda d: d.update(texts={"unknown_key": {"ru": "x"}}), "Неизвестные тексты"),
    (lambda d: sec(d, "locations")["buttons"][0].update(action="import_app", target="evilapp"), "happ"),
    (lambda d: d.update(cabinet_url="http://plain.example.com"), "https://"),
])
def test_invalid_layouts_are_rejected(change, message):
    data = mobile_layout.defaults().model_dump(mode="json")
    mobile_layout.MobileLayout.model_validate(data)  # the defaults themselves are valid
    change(data)
    with pytest.raises(ValidationError) as exc:
        mobile_layout.MobileLayout.model_validate(data)
    assert message in str(exc.value)


@pytest.mark.asyncio
async def test_unknown_banner_key_is_refused(database):
    data = edited()
    sec(data, "vpn")["banner"]["key"] = "no-such-banner"
    with pytest.raises(HTTPException) as exc:
        await mobile_layout.admin_mobile_layout_save(mobile_layout.MobileLayout.model_validate(data), database, ADMIN)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_broken_stored_value_falls_back_to_defaults(database):
    database.add(AppSetting(key=mobile_layout.SETTING_KEY, value='{"sections": "broken"}'))
    await database.commit()
    doc = await mobile_layout.resolve_layout(database, "ru")
    assert doc["tabs"] == ["subscription", "premium", "vpn", "locations", "settings"]


@pytest.mark.asyncio
async def test_public_endpoint_answers_304_for_an_unchanged_layout(database):
    resp = Resp()
    doc = await mobile_layout.mobile_layout(Req(), resp, "en", database)
    assert doc["lang"] == "en" and resp.headers["ETag"] == f'"{doc["version"]}"'
    again = await mobile_layout.mobile_layout(Req({"If-None-Match": resp.headers["ETag"]}), Resp(), "en", database)
    assert again.status_code == 304


@pytest.mark.asyncio
async def test_admin_document_lists_everything_the_editor_needs(database):
    doc = await mobile_layout.admin_mobile_layout(database, ADMIN)
    assert "connect" in doc["actions"] and "happ" in doc["import_apps"]
    assert doc["banner_keys"]["app-vpn"] == "Приложение: VPN"
    assert set(doc["preview"]) == {"ru", "en", "uk"}
    assert doc["layout"] == doc["defaults"]


def test_apps_ship_the_current_default_layout():
    """Both apps draw the bundled default before the shop answers; it must match the backend."""
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    expected = json.dumps(mobile_layout.bundled_defaults(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    for path in ("mobile/android-user/app/src/main/assets/default_layout.json", "mobile/ios-user/VpnShopUser/default_layout.json"):
        assert (root / path).read_text() == expected, f"{path}: regenerate with scripts/mobile/export-default-layout.py"
    bundled = mobile_layout.bundled_defaults()
    assert set(bundled) == {"ru", "en", "uk"}
    for section in bundled["ru"]["sections"]:
        # Every default banner exists as a file the backend serves.
        key = section["banner"]["url"].rsplit("/", 1)[1].removesuffix(".jpg")
        assert bot_banners.default_path(key) is not None, key


@pytest.mark.asyncio
async def test_clients_always_revalidate_the_layout(database):
    """An admin change must reach the apps at the next start: no max-age, only ETag revalidation."""
    resp = Resp()
    await mobile_layout.mobile_layout(Req(), resp, "ru", database)
    assert resp.headers["Cache-Control"] == "no-cache"


def test_buttons_open_shop_documents():
    data = mobile_layout.defaults().model_dump(mode="json")
    targets = {b["target"] for s in data["sections"] for b in s["buttons"] if b["action"] == "document"}
    assert targets == {"faq", "rules", "privacy", "offer"}
    sec(data, "vpn")["buttons"][1].update(action="document", target="cookies")
    with pytest.raises(ValidationError) as exc:
        mobile_layout.MobileLayout.model_validate(data)
    assert "документ" in str(exc.value)


@pytest.mark.asyncio
async def test_every_app_string_and_screen_block_is_editable(database):
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    # The backend copy of the app strings is the one the apps ship.
    assert (root / "backend/app/assets/mobile_strings.json").read_text() == (root / "mobile/l10n/user.json").read_text()
    strings = mobile_layout.app_strings()
    assert strings["sign_in"]["ru"] and strings["sign_in"]["en"] and len(strings) > 100
    data = edited(strings={"sign_in": {"ru": "Войти в Корги", "en": "", "uk": "Увійти до Коргі"}},
                  features={"vpn_location_card": False, "login_sign_up": False})
    await mobile_layout.admin_mobile_layout_save(mobile_layout.MobileLayout.model_validate(data), database, ADMIN)
    ru, en, uk = [await mobile_layout.resolve_layout(database, lang) for lang in ("ru", "en", "uk")]
    assert ru["strings"] == {"sign_in": "Войти в Корги"} and uk["strings"] == {"sign_in": "Увійти до Коргі"}
    assert en["strings"] == {}, "an English app keeps its own text when only ru/uk were replaced"
    assert ru["features"]["vpn_location_card"] is False and ru["features"]["login_sign_up"] is False
    assert ru["features"]["header_support"] is True and set(ru["features"]) == set(mobile_layout.FEATURES)
    with pytest.raises(ValidationError, match="Неизвестные строки"):
        mobile_layout.MobileLayout.model_validate(edited(strings={"no_such_key": {"ru": "x"}}))
    with pytest.raises(ValidationError, match="Неизвестные функции"):
        mobile_layout.MobileLayout.model_validate(edited(features={"self_destruct": True}))
    admin = await mobile_layout.admin_mobile_layout(database, ADMIN)
    assert "sign_in" in admin["strings"] and "vpn_plan_card" in admin["features"]
    assert json.loads(json.dumps(admin["layout"]))["features"]["vpn_location_card"] is False
