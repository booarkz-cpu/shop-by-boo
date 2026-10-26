# Список работ v28.32.0

Дистрибутив `v28.32.0`, runtime/API `21.5.1`, миграция магазина `0077_app_growth`, Support Pro `0008`. Заметки: [RELEASE_V28_32_0.md](RELEASE_V28_32_0.md).

| № | Работа | Где | Статус |
| --- | --- | --- | --- |
| 1 | Адрес магазина в сборке, одноразовые ссылки входа из бота и кабинета | `app_login.py`, `bot.py`, `cabinet/src/app-login.tsx`, приложения | готово |
| 2 | Вход через Telegram, Яндекс, VK и Google в приложениях | `app_login.py`, `main.py`, `cabinet_api.py`, приложения | готово |
| 5 | Push-кампании по сегментам | `app_growth.py`, `admin/src/appGrowth.tsx` | готово |
| 6 | Аналитика приложений и воронка | `app_growth.py`, `CorgiAnalytics` (Android/iOS), `admin/src/appGrowth.tsx` | готово |
| 7 | Розыгрыши и баннер акции в приложениях | `mobile_layout.py`, экраны Android/iOS, `app-giveaways.jpg` | готово |
