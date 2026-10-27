"""The look of push notifications is edited in the admin panel and applied when a push is sent."""
import pytest
from pydantic import ValidationError

from app import push_style
from app.push_style import PushStyle, render


def test_defaults_render_brand_buttons_and_banner():
    look = render(PushStyle(), "subscription_expiring", "Подписка заканчивается", "Осталось 3 дн.", "https://api.corgi.test")
    assert look["title"] == "⏳ Подписка заканчивается" and look["body"] == "Осталось 3 дн."
    assert look["image"] == "https://api.corgi.test/api/bot/banners/default/app-premium.jpg"
    assert look["buttons"] == [{"label": "Продлить", "section": "premium"}, {"label": "Подписка", "section": "subscription"}]
    assert (look["channel"], look["section"], look["accent"], look["group"]) == ("important", "premium", "#FF8A1F", "subscription_expiring")
    assert render(PushStyle(), "never-heard-of", "T", "B")["section"] == "notifications", "unknown kinds use «Остальные»"
    assert render(PushStyle(), "campaign", "T", "B", "http://plain")["image"] == "", "pictures only over https"


def test_administrator_templates_switches_and_validation():
    style = PushStyle.model_validate({"accent": "#00AAFF", "images": False, "group": False, "kinds": {
        "campaign": {"title": "{brand}: {title}", "body": "{body} 🐶", "emoji": "", "buttons": [{"label": "Хочу", "section": "premium"}],
                     "channel": "promo", "image": "https://cdn.example/sale.png"},
        "support": {"enabled": False}}})
    look = render(style, "campaign", "Скидка", "Сегодня {x}")
    assert (look["title"], look["body"], look["image"], look["group"]) == ("Корги Люси: Скидка", "Сегодня {x} 🐶", "", "")
    assert render(style, "support.reply", "a", "b")["enabled"] is False
    assert "payment" in style.kinds, "kinds the admin did not touch keep their defaults"
    for bad in ({"accent": "orange"}, {"kinds": {"spam": {}}}, {"kinds": {"campaign": {"image": "javascript:alert(1)"}}},
                {"kinds": {"campaign": {"buttons": [{"label": "1"}, {"label": "2"}, {"label": "3"}]}}},
                {"kinds": {"campaign": {"section": "../admin"}}}):
        with pytest.raises(ValidationError):
            PushStyle.model_validate(bad)


def test_every_shop_kind_maps_to_an_edited_style():
    assert set(push_style.KIND_MAP.values()) <= set(push_style.KINDS)
    assert push_style.style_kind("support.reply") == "support" and push_style.style_kind("payment_success") == "payment"
