# Статус реализации по этапам

Состояние на 2026-11-02. База: `main` @ `161e9b4d`, дистрибутив `v28.57.0`, миграция магазина `0088_filter_and_regions`. Этапы выполняются по одному, следующий начинается по команде владельца.

| № | Этап | Статус | Подтверждение / что осталось |
| --- | --- | --- | --- |
| 1 | Инвентаризация и клонирование референсов | PASS | Выполнен 2026-11-01, перепроверен 2026-11-02 по исходникам: [STAGE_1_VERIFICATION](STAGE_1_VERIFICATION.md); исправлены 10 неточностей в числах и путях, выводы о лицензиях подтверждены |
| 2 | Feature gap analysis | NOT_STARTED | [FEATURE_COMPARISON_MATRIX](FEATURE_COMPARISON_MATRIX.md), [REMNAWAVE_FEATURE_MATRIX](REMNAWAVE_FEATURE_MATRIX.md) |
| 3 | Полный технический аудит | NOT_STARTED | FULL_TECHNICAL_AUDIT, SECURITY_AUDIT, PERFORMANCE_AUDIT, [BUG_REGISTRY](BUG_REGISTRY.md) |
| 4 | Исправление ошибок | NOT_STARTED | BUGFIX_LOG, REGRESSION_TESTS |
| 5 | Backend и единая бизнес-логика | NOT_STARTED | API, BACKEND_ARCHITECTURE, DATABASE_SCHEMA |
| 6 | Единая административная панель | NOT_STARTED | [ADMIN_CONTROL_MATRIX](ADMIN_CONTROL_MATRIX.md), ADMIN_PANEL_GUIDE, ADMIN_MODULES, RBAC |
| 7 | UI/UX redesign | NOT_STARTED | UI_UX_GUIDE |
| 8 | Личный кабинет | NOT_STARTED | USER_CABINET_GUIDE; тарифы Lucy Mini/Max/Ultra |
| 9 | Архитектура Remnawave | NOT_STARTED | REMNAWAVE_ARCHITECTURE, DATA_MODEL, API_DESIGN, DEPLOYMENT_AGENT_ARCHITECTURE |
| 10 | Установка Remnawave через админку | NOT_STARTED | Нужен VPS для живой проверки (иначе BLOCKED_EXTERNAL) |
| 11 | Отдельный домен и Subscription Portal | NOT_STARTED | Расширение `backend/app/sub_proxy.py` и `deploy/Caddyfile`, без второго proxy |
| 12 | Менеджер расширений Remnawave | NOT_STARTED | SelfSteal, Node Plugins, Xray, WARP, NetBird, IPv6, Routing, Balancer, Rules, Checker |
| 13 | Telegram-бот и Mini App | NOT_STARTED | Нужен `BOT_TOKEN` для живой проверки |
| 14 | Платёжная система | NOT_STARTED | Нужны ключи провайдеров (иначе BLOCKED_SECRETS) |
| 15 | Docker, установщик, автообновление, Automation Center | NOT_STARTED | |
| 16 | Безопасность и мониторинг | NOT_STARTED | |
| 17 | Android, iOS и документация | NOT_STARTED | Сравнение sing-box / Xray; сборки — только в CI |
| 18 | Полное тестирование и релиз | NOT_STARTED | |

## Незавершённая работа вне этапов

| Работа | Где | Статус |
| --- | --- | --- |
| Вход в приложения через Telegram (код в боте), Яндекс, VK, Google; раздел «Приложения: экраны и кнопки», `GET /api/mobile/config` | ветка `feat/v28.31.0-mobile` (основа `v28.30.0`) | IMPLEMENTED, тесты проходили на старой базе. Для `main` нужна перенумерация миграции `0077_google_login` → `0089` и перенос. Войдёт в этапы 8 и 17 |
