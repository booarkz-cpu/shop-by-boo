"""Texts of the «Корги Люси» brand as the shop's defaults (owner's decision 4 of 2026-11-12: «да, везде»).

The source is docs/BRAND_COPY.md; tests/test_brand_copy.py keeps the two in step. Every text here is only a
default: what the owner wrote in the admin panel (Mini App subtitle, bot texts) always wins.

The payment text is deliberately not here: it may name only the methods the owner's contract really has."""
from __future__ import annotations

NAME = {"ru": "Корги Люси", "en": "Corgi Lusi", "uk": "Коргі Люсі"}
TITLE = {"ru": "Корги Люси — Свободный интернет без лишнего Гав"}
TAGLINE = {"ru": "Твой интернет. Твои правила. Твоя Люси", "en": "Your internet. Your rules. Your Lusi",
           "uk": "Твій інтернет. Твої правила. Твоя Люсі"}
SHORT = {"ru": "Корги Люси — VPN без лишнего Гав. Подключение за минуту.",
         "en": "Corgi Lusi — a VPN without the extra woof. Connect in a minute.",
         "uk": "Коргі Люсі — VPN без зайвого Гав. Підключення за хвилину."}
FULL = {"ru": "Корги Люси — VPN-сервис с простым подключением. Выберите тариф, оплатите и получите ссылку — приложение настроится само. "
              "Управлять подпиской можно в Telegram-боте, личном кабинете и приложении. Твой интернет. Твои правила. Твоя Люси.",
        "en": "Corgi Lusi is a VPN service that is simple to connect. Pick a plan, pay and get a link — the app sets itself up. "
              "Manage your subscription in the Telegram bot, the web cabinet or the app. Your internet. Your rules. Your Lusi.",
        "uk": "Коргі Люсі — VPN-сервіс із простим підключенням. Оберіть тариф, оплатіть і отримайте посилання — застосунок налаштується сам. "
              "Керувати підпискою можна в Telegram-боті, особистому кабінеті та застосунку. Твій інтернет. Твої правила. Твоя Люсі."}
MAINTENANCE = {"ru": "Люси ненадолго ушла на прогулку: идут технические работы. Подписки работают как обычно — скоро вернёмся.",
               "en": "Lusi is out for a short walk: maintenance in progress. Your subscriptions keep working — we will be back soon.",
               "uk": "Люсі ненадовго пішла на прогулянку: тривають технічні роботи. Підписки працюють як звичайно — скоро повернемося."}

# What /api/public/config hands to the cabinet, the Mini App and the apps.
PUBLIC = {"name": NAME, "title": TITLE["ru"], "tagline": TAGLINE, "short": SHORT, "full": FULL, "maintenance": MAINTENANCE}
