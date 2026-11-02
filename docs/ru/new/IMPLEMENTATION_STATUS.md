# Статус реализации по этапам

Состояние на 2026-11-02. База: дистрибутив `v28.62.0`, миграция магазина `0089_index_cleanup` (после этапа 7 и дополнений к этапу 6). Этапы выполняются по одному, следующий начинается по команде владельца.

| № | Этап | Статус | Подтверждение / что осталось |
| --- | --- | --- | --- |
| 1 | Инвентаризация и клонирование референсов | PASS | Выполнен 2026-11-01, перепроверен 2026-11-02 по исходникам: [STAGE_1_VERIFICATION](STAGE_1_VERIFICATION.md); исправлены 10 неточностей в числах и путях, выводы о лицензиях подтверждены |
| 2 | Feature gap analysis | PASS | Выполнен 2026-11-02 по исходникам: [FEATURE_COMPARISON_MATRIX](FEATURE_COMPARISON_MATRIX.md) (45 функций в трёх группах), [REMNAWAVE_FEATURE_MATRIX](REMNAWAVE_FEATURE_MATRIX.md). Нет 11 функций, частично — 5; дубликатов не планируется. PASS относится к анализу, а не к функциям |
| 3 | Полный технический аудит | PASS | Выполнен 2026-11-02: [FULL_TECHNICAL_AUDIT](FULL_TECHNICAL_AUDIT.md), [SECURITY_AUDIT](SECURITY_AUDIT.md), [PERFORMANCE_AUDIT](PERFORMANCE_AUDIT.md), [BUG_REGISTRY](BUG_REGISTRY.md). Высоких уязвимостей нет; 9 технических находок, 6 по безопасности (2 средних), 4 по производительности; 7 новых записей в реестре ошибок. Вызовы Remnawave сверены с контрактом 3.4.15 (последний backend 3.4.7). Проверки со стендом, доменом и ключами — `BLOCKED_*` |
| 4 | Исправление ошибок | PASS | Выпуск v28.58.0 (2026-11-02): [BUGFIX_LOG](BUGFIX_LOG.md), [REGRESSION_TESTS](REGRESSION_TESTS.md). Исправлено 11 записей реестра (BUG-H1–H3, A1–A7, T1) и добавлен тест проверки вызывающего (SEC-05); миграция `0089_index_cleanup`; 11 новых или изменённых наборов тестов. Перенесено на этапы 5, 6, 13: внешние ключи, переименование `remnawave_uuid`, пагинация, `defusedxml`, лимиты памяти, разбиение `admin/src/main.tsx` |
| 5 | Backend и единая бизнес-логика | PASS | Выпуск v28.59.0 (2026-11-02): [API](API.md), [BACKEND_ARCHITECTURE](BACKEND_ARCHITECTURE.md), [DATABASE_SCHEMA](DATABASE_SCHEMA.md). Одна выдача мест семьи и компаний (`seat_access.py`), тест единственности путей выдачи доступа и подтверждения оплат, формат ошибки 500, страницы списков, отчёт целостности, колонка «Доступ» в перечне API, `defusedxml`. Внешние ключи ждут пустого отчёта целостности на реальной установке; вход клиента через общую зависимость и пагинация старых списков — постепенно (этап 6) |
| 6 | Единая административная панель | PASS | Выпуск v28.60.0 (2026-11-02): «Система → Админ-центр» и [ADMIN_CONTROL_MATRIX](ADMIN_CONTROL_MATRIX.md), сгенерированная из маршрутов API: 25 из 30 модулей управляются из панели, у остальных пяти (установка, домены, сертификаты, Reverse Proxy, расширения нод) указаны этапы 10–12. Таблица прав ролей, поиск в журнале действий, журнал изменений прослойки подписок. Дополнения в v28.62.0 по новой редакции задания: System Control Center («Состояние системы»: 14 проверок — backend, интерфейсы, база, миграции, Redis, Remnawave, узлы, Caddy, TLS, платежи, фоновые задачи, резервные копии, бот, обновления), [ADMIN_PANEL_GUIDE](ADMIN_PANEL_GUIDE.md), [ADMIN_MODULES](ADMIN_MODULES.md), [RBAC](RBAC.md). Что пока требует консоли сервера — в руководстве. Работа каждой кнопки проверяется на этапе 18 |
| 7 | Полный UI/UX redesign | PASS | Выпуск v28.61.0 (2026-11-02): [UI_UX_GUIDE](UI_UX_GUIDE.md). Палитра `#090D16`/`#0F172A`/синий, Inter и JetBrains Mono закреплены тестом; новые разделы «Remnawave: панель», «Портал подписки», «Доступность и качество»; общие состояния блоков; 503/502 вместо внутренней ошибки без Remnawave; e2e открывает все разделы на 1440 и 390 px. Мастер установки и менеджер доменов — вместе с их backend на этапах 10–11 |
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
