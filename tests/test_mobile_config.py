"""v28.31.0: everything in the customer apps is edited in the admin panel (GET /api/mobile/config)."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app import main as shop
from app import mobile_config as mc
from app.config import settings
from app.info_pages import PageIn, Translation, admin_save as save_doc
from app.models import AuditLog
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="root@example.test", role="admin")


@pytest.fixture(autouse=True)
def shop_env(monkeypatch):
    async def public_config(db):
        return {"app_name": "Корги Люси", "payment_providers": ["yookassa"], "trial_days": 3}
    monkeypatch.setattr(shop, "public_config", public_config)
    for key, value in {"bot_username": "corgi_lusi_bot", "bot_token": "1:T", "google_client_id": "", "google_client_secret": "",
                       "yandex_client_id": "y", "yandex_client_secret": "s", "vk_client_id": "", "vk_client_secret": ""}.items():
        monkeypatch.setattr(settings, key, value)


def test_defaults_are_valid_and_tabs_are_checked():
    cfg = mc.MobileConfig()
    assert [t.id for t in cfg.tabs if t.enabled] == ["home", "plans", "profile", "support"]
    with pytest.raises(ValidationError, match="от двух до пяти"):
        mc.MobileConfig(tabs=[{"id": t, "enabled": True} for t in ("home", "plans", "profile", "support", "servers", "info")])
    with pytest.raises(ValidationError, match="home"):
        mc.MobileConfig(tabs=[{"id": "plans"}, {"id": "profile"}])
    with pytest.raises(ValidationError, match="https://"):
        mc.Button(id="x", title={"ru": "Сайт"}, action="link", target="http://example.com")
    with pytest.raises(ValidationError, match="раздел"):
        mc.Button(id="x", title={"ru": "Куда-то"}, action="section", target="nowhere")


@pytest.mark.asyncio
async def test_admin_edits_reach_the_apps_in_every_language(database):
    db = database
    cfg = mc.MobileConfig(
        look={"app_name": "Lusi VPN", "accent": "#ff8800"},
        tabs=[{"id": "home"}, {"id": "servers", "title": {"ru": "Страны", "en": "Countries"}}, {"id": "support"}],
        home={"notice": {"ru": "Проблемы с подключением — уже чиним"}, "blocks": [{"kind": "connect"}, {"kind": "usage"}, {"kind": "promo", "enabled": False}]},
        buttons=[{"id": "bot", "title": {"ru": "Наш бот", "en": "Our bot"}, "action": "telegram_bot", "icon": "send"},
                 {"id": "news", "title": {"ru": "Канал"}, "action": "telegram_channel", "target": "@corgi_news", "placement": "support"},
                 {"id": "off", "title": {"ru": "Скрытая"}, "action": "plans", "enabled": False}],
        login={"methods": ["google", "telegram", "email", "yandex"]},
        plans={"compare": [{"label": {"ru": "Трафик", "en": "Traffic"}, "trial": "5 ГБ", "paid": "Безлимит"}]},
        profile={"items": ["email", "telegram", "logout"]})
    await mc.admin_save(cfg, db, ADMIN)
    assert (await db.execute(select(AuditLog).where(AuditLog.action == "mobile_config.saved"))).scalars().first()
    ru = await mc.build(db, None, "ru")
    assert ru["look"]["app_name"] == "Lusi VPN" and ru["look"]["colors"]["accent"] == "#ff8800"
    assert [(t["id"], t["title"]) for t in ru["tabs"]] == [("home", "VPN"), ("servers", "Страны"), ("support", "Поддержка")]
    assert ru["home"]["blocks"] == ["connect", "usage"] and ru["home"]["notice"].startswith("Проблемы")
    assert [(b["id"], b["target"]) for b in ru["buttons"]] == [("bot", "https://t.me/corgi_lusi_bot"), ("news", "https://t.me/corgi_news")]
    assert ru["login"]["methods"] == ["telegram", "email", "yandex"]  # Google is not configured on this shop
    assert ru["plans"]["compare"][0] == {"label": "Трафик", "trial": "5 ГБ", "paid": "Безлимит"}
    assert ru["profile"]["items"] == ["email", "telegram", "logout"]
    en = await mc.build(db, None, "en")
    assert en["tabs"][1]["title"] == "Countries" and en["buttons"][0]["title"] == "Our bot"
    assert en["buttons"][1]["title"] == "Канал"  # no English text: Russian is shown
    assert en["tabs"][2]["title"] == "Support" and en["plans"]["compare"][0]["label"] == "Traffic"


@pytest.mark.asyncio
async def test_documents_and_faq_come_from_the_documents_section(database):
    db = database
    await save_doc("faq", PageIn(ru=Translation(items=[{"question": "Как подключиться?", "answer": "Нажмите «Подключить»."}])), db, ADMIN)
    await save_doc("offer", PageIn(ru=Translation(body="Условия")), db, ADMIN)
    out = await mc.build(db, None, "ru")
    assert out["support"]["faq"][0]["question"] == "Как подключиться?"
    assert [d["kind"] for d in out["documents"]] == ["faq", "offer"]
    assert out["login"]["legal_links"] == [{"kind": "offer", "title": "Публичная оферта"}]


@pytest.mark.asyncio
async def test_the_public_endpoint_supports_etag_and_reset_restores_defaults(database):
    class Req:
        headers = {}
    class Resp:
        headers = {}
    first = await mc.mobile_config(Req(), Resp(), "ru", database)
    Req.headers = {"If-None-Match": f'"{first["version"]}"'}
    assert (await mc.mobile_config(Req(), Resp(), "ru", database)).status_code == 304
    await mc.admin_save(mc.MobileConfig(look={"app_name": "X"}), database, ADMIN)
    await mc.admin_reset(database, ADMIN)
    assert (await mc.build(database, None, "ru"))["look"]["app_name"] == "Корги Люси"
