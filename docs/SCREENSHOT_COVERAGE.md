# Покрытие экранов изображениями

В проверяемых каталогах 208 PNG-файлов и 206 различных значений SHA-256. Таблица учитывает сохранённые изображения. Источник указывает сценарий их получения.

| Интерфейс или материал | Файлов | Размеры в пикселях (количество) | Сценарий |
| --- | ---: | --- | --- |
| Lucy Admin Web | 114 | 1440×900 (100), 390×844 (7), 543×1158 (1), 1104×157 (1), 1104×341 (1), 1104×387 (1), 1104×430 (1), 1104×693 (1), 1104×766 (1) | [apps/lucy-admin/web/scripts/screenshots-catalog.mjs](../apps/lucy-admin/web/scripts/screenshots-catalog.mjs) |
| Кабинет | 23 | 1440×900 (23) | [apps/lucy-admin/web/scripts/screenshots-catalog.mjs](../apps/lucy-admin/web/scripts/screenshots-catalog.mjs) |
| VPN Shop Android | 12 | 1080×2400 (12) | [.github/workflows/mobile-screenshots.yml](../.github/workflows/mobile-screenshots.yml) |
| VPN Shop iOS | 11 | 1206×2622 (11) | [.github/workflows/mobile-screenshots.yml](../.github/workflows/mobile-screenshots.yml) |
| Lucy Admin Android | 7 | 1080×2400 (7) | [.github/workflows/mobile-screenshots.yml](../.github/workflows/mobile-screenshots.yml) |
| Lucy Admin iOS | 7 | 1206×2622 (7) | [.github/workflows/mobile-screenshots.yml](../.github/workflows/mobile-screenshots.yml) |
| Corgi Lucy Client Android | 10 | 1080×2209 (10) | [apps/vpn-client/android/app/src/androidTest/java/shop/corgi/client/ClientScreensTest.kt](../apps/vpn-client/android/app/src/androidTest/java/shop/corgi/client/ClientScreensTest.kt) |
| Telegram Mini App | 8 | 780×1688 (8) | [scripts/screenshots/miniapp.mjs](../scripts/screenshots/miniapp.mjs) |
| Превью чата бота | 4 | 780×1688 (4) | [scripts/screenshots/bot_chat.py](../scripts/screenshots/bot_chat.py) |
| Карточки магазинов Android и iOS | 12 | 1080×1920 (6), 1320×2868 (6) | [scripts/store/render.py](../scripts/store/render.py) |

## Одинаковые файлы

- [screenshots/client/home-v150.png](../screenshots/client/home-v150.png), [screenshots/client/home.png](../screenshots/client/home.png)
- [screenshots/storefront_user/03_overview.png](../screenshots/storefront_user/03_overview.png), [screenshots/storefront_user/05_checkout_success.png](../screenshots/storefront_user/05_checkout_success.png)

## Границы проверки

Браузерные сценарии и мобильные сборки используют демонстрационные данные. Превью Telegram-бота смоделированы по текстам и баннерам бота. Карточки магазинов оформлены из исходных снимков.
Для подтверждения оплаты, соединения VPN или запуска на физическом устройстве нужны отдельные результаты тестов. Для привязки к новой версии сохраните ссылку на запуск, ревизию сборки и результат сценария.
Соответствие пунктов меню Lucy Admin Web существующим файлам проверяет [test_screenshots.py](../tests/test_screenshots.py).

Пересчёт выполняется командой `python3 scripts/audit/check_screenshots.py`. Для проверки сохранённой таблицы используйте `python3 scripts/audit/check_screenshots.py --check`.
