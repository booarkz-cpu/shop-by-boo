# Полный технический аудит (этап 3)

База: `main` @ `9f31d19b` (v28.57.0, runtime 21.5.1, миграция `0088_filter_and_regions`, Support Pro 0008). Проверка 2026-11-02. Безопасность — в [SECURITY_AUDIT](SECURITY_AUDIT.md), производительность — в [PERFORMANCE_AUDIT](PERFORMANCE_AUDIT.md), ошибки — в [BUG_REGISTRY](BUG_REGISTRY.md).

Как проверялось: скрипты по исходникам и по приложению FastAPI, полный набор тестов на PostgreSQL 16 и Redis, все миграции на пустой базе, `alembic` autogenerate против моделей, bandit, pip-audit, сверка вызовов Remnawave с опубликованным контрактом. Скрипты лежат вне репозитория; команды и результаты приведены в разделах.

## Сводка находок

| ID | Уровень | Область | Суть | Этап |
| --- | --- | --- | --- | --- |
| TECH-01 | высокий | Frontend | Клиенты API админки и кабинета превращают ответ 2xx, который не разобрался как JSON, в `{}`. Вероятная первопричина BUG-H1 и BUG-H2 | 4 |
| TECH-02 | средний | Database | Модели и миграции расходятся: autogenerate находит 110 операций | 4 |
| TECH-03 | средний | Database | 134 колонки `*_id` без внешнего ключа, в том числе `payments.user_id` и `subscriptions.user_id` | 5 |
| TECH-04 | средний | Remnawave | `subscriptions.remnawave_uuid` хранит числовой `id` пользователя панели, а не UUID. Название вводит в заблуждение; импорт истории может принести настоящие UUID, которые API 3.4 отвергнет | 4–5 |
| TECH-05 | средний | Remnawave | Версия панели в проекте не зафиксирована; проверка совместимости с живой панелью не проводилась | 9 |
| TECH-06 | средний | Frontend | `apps/lucy-admin/web/src/main.tsx` — 126 КБ, 60 строк длиннее 400 символов; повтор кода в `documents.tsx` (BUG-H3) | 4, 6 |
| TECH-07 | низкий | Backend | Три отдельные реализации защиты от SSRF (`content_branding_api.py`, `payments.py` `_public_client`, `plugins.py`), а два модуля ей не пользуются (SEC-01) | 4 |
| TECH-08 | низкий | Infrastructure | Нет healthcheck у `worker`, `bot`, `mail_receiver`, `support_worker` (`backend_standby` наследует его у backend через `extends` — уточнено на этапе 4); нет лимита памяти у `bot` и сервисов Support Pro | 4 |
| TECH-09 | низкий | Backend | У `provisioner.py` нет поведенческого теста, только проверки по тексту кода | 4 |

## Backend

| Что | Результат |
| --- | --- |
| Архитектура | FastAPI, 173 модуля в `backend/app`. `main.py` (991 строка) создаёт приложение, подключает 59 роутеров и в конце импортирует 16 вынесенных разделов (`*_api.py`), которые регистрируют маршруты на `app`. Самые большие модули: `models.py` 2166 строк, `mail_domain.py` 1052, `payments.py` 1046, `payments_api.py` 1009 |
| API | 836 маршрутов. Все маршруты, объявленные декораторами в исходниках, действительно зарегистрированы. В новой версии FastAPI роутеры подключаются лениво (`_IncludedRouter`), поэтому `app.routes` показывает только 244 из них; проверять маршруты надо обходом вложенных роутеров |
| Авторизация и RBAC | Все 552 административных маршрута, кроме входа, требуют `current_admin` и `require_permission`. Вход клиента проверяется внутри обработчиков (SEC-05) |
| Бизнес-логика оплат | Идемпотентность по `(user_id, idempotency_key)`, блокировки пользователя в Redis, `SELECT … FOR UPDATE`, повторная проверка оплаты у провайдера, продление в Remnawave через `extend_idempotent` (сверяет срок до и после). Нагрузочный тест в CI подтверждает одно продление на оплату |
| Фоновые задачи | Отдельный сервис `worker`, задачи в таблице `jobs` с попытками и следующей попыткой; рассылки защищены `SET NX` в Redis |
| Транзакции | Блокировки строк при изменении баланса, подписок, подарков; записи журнала аудита в той же транзакции |
| Ошибки | Глушение исключений (`except Exception: pass`) — 2 места. Ответы об ошибках на русском, через `HTTPException` |
| Производительность | См. PERFORMANCE_AUDIT |

## Remnawave

Последняя версия: backend **3.4.7** (2026-10-22, тег в `remnawave/backend`), npm-пакет контракта `@remnawave/backend-contract` **3.4.15** — 218 команд API.

| Проверка | Результат |
| --- | --- |
| Пути и методы | Все 38 пар «метод + путь», которые вызывает магазин (`remnawave.py`, `panel_admin.py`, `vpn_sessions.py`, `panel_usage.py`, `bot.py` и др.), есть в контракте 3.4.15 |
| Тела запросов | Создание пользователя (`username`, `expireAt`, `trafficLimitBytes`, `trafficLimitStrategy`, `activeInternalSquads`, `telegramId`, `hwidDeviceLimit`), изменение (`id` числом), продление (`days`) совпадают со схемами zod контракта |
| Идентификатор пользователя | В 3.4 `userId` — число (`numberParamSchema`); строка UUID схему не проходит. Магазин хранит числовой `id` (`str(data["id"])`), но в колонке с названием `remnawave_uuid` (TECH-04) |
| Тест контракта | `tests/test_remnawave_contract.py` проверяет клиент на заглушке с ответами в формате 3.4 (`{"response": …}`) |
| Живая панель | Не проверялось: нет адреса и токена — `BLOCKED_SECRETS` |

## Frontend

| Что | Результат |
| --- | --- |
| Структура | Next.js со статическим экспортом: `apps/lucy-admin/web/` и `apps/user-cabinet/`; Mini App — это сборка кабинета с `NEXT_PUBLIC_SURFACE=miniapp` (`apps/telegram-mini-app/` содержит только Dockerfile и nginx) |
| Маршрутизация | Внутренние разделы в одном приложении; nginx отдаёт `index.html` на любой неизвестный путь (`try_files … /index.html`) |
| API-клиент | `req()` в `apps/lucy-admin/web/src/main.tsx:79` и в `apps/user-cabinet/src/main.tsx:100`: `let d = {}; try { d = await r.json() } catch {}`, ошибка выбрасывается только при `!r.ok`. Ответ 2xx, который не JSON (HTML от SPA-заглушки при неверно настроенном `/api`, пустое тело), становится `{}` (TECH-01) |
| Обработка ошибок | `AdminErrorBoundary`, error boundary в кабинете и в каждом разделе Mini App, `error.tsx` в обоих приложениях |
| Защита от пустых данных | 70 мест вида `(x \|\| []).map(…)`, 30 из них в `apps/lucy-admin/web/src/main.tsx`; 103 вызова `.trim()`. Прежние исправления `trim` (коммиты `2673787d`, `a251c11b`, `a708b318`, 2026-10-01) нормализовали значение в месте вызова, а не причину |
| Сборка и типы | `typecheck + build` admin, cabinet и miniapp проходят в CI (PR #164); встроенные скрипты выносятся в файлы под CSP (`apps/user-cabinet/scripts/csp-externalize.mjs`) |
| Адаптивность | Скриншоты мобильных экранов делает CI, но артефакты недоступны из этой среды (хранилище заблокировано прокси) — `BLOCKED_ACCESS` |

## Database

| Что | Результат |
| --- | --- |
| Миграции | Все миграции от пустой базы до `0088_filter_and_regions` проходят за 4 с; 156 таблиц, 491 индекс, 56 внешних ключей. В CI есть тест параллельного запуска миграций |
| Модели и миграции | `alembic` autogenerate против моделей: 110 расхождений (39 `add_index`, 38 `remove_constraint`, 32 `remove_index`, 1 `modify_nullable`). Почти все — модель описывает `unique=True, index=True`, а база содержит отдельное ограничение и отдельный индекс. Реальное расхождение: `gift_redemptions.operation_key` в модели `NOT NULL`, в базе допускает `NULL` (миграция `0032`) |
| Связи | 134 колонки `*_id` без внешнего ключа; целостность держится на коде (TECH-03) |
| Индексы | 26 лишних, 6 внешних ключей без индекса — PERFORMANCE_AUDIT |
| Backup | `backups_api.py` (10 маршрутов: создание, проверка, восстановление с подтверждением второго администратора, выгрузка), `backup_verify.py` (восстановление в отдельную базу и сверка числа строк `users`, `subscriptions`, `payments`), `telegram_backup.py`, S3 через boto3. Тесты — `test_backup_bundle.py`, `test_backup_cli.py`. Восстановление на живом сервере — `BLOCKED_EXTERNAL` |

## Infrastructure

| Что | Результат |
| --- | --- |
| Compose | 17 сервисов, одна сеть `ingress`, 12 томов. Наружу — только Caddy (80, 443, 443/udp) и приём почты (25) |
| Образы | Базовые образы закреплены по digest; приложения не от root; `read_only`, `cap_drop: ALL` |
| Healthchecks | Есть у redis, db, backend (и `backend_standby` через `extends`), admin, miniapp, cabinet, support_db, support_redis, support_pro, caddy. Нет — TECH-08 (исправлено в v28.58.0) |
| Caddy | Один набор блоков для всех доменов; подписки идут через `SUB_PROXY_DOMAINS` в общий блок; балансировка backend → standby для обновления без простоя; строгие заголовки безопасности |
| TLS | Выпускает Caddy автоматически; проверка на реальном домене — `BLOCKED_EXTERNAL` |
| Установщик | `install.sh` запускается через `curl … \| sudo bash` с тега репозитория; `deploy/install-vps.sh` читает ответы с терминала. Запуск на чистом VPS — этап 10, `BLOCKED_EXTERNAL` |

## Тесты

Полный набор backend на PostgreSQL 16 и Redis 7 (без `test_parallel_alembic_upgrade_survives_the_race`, который запускается в CI): 2469 passed, 62 skipped, 2 failed за 27 мин 38 с. Оба падения — один тест, зависящий от `PAYMENTS_SANDBOX=true` из окружения CI (BUG-T1); с этой переменной он проходит. В CI на PR #164 прошли 18 проверок: backend, admin/cabinet/miniapp, Support Pro, lint, Docker Compose, контейнеры, Chromium e2e, сборки Android и iOS.

## Что дальше

Этап 4: TECH-01 (с воспроизведением BUG-H1/H2), TECH-02, TECH-04, TECH-07/SEC-01, SEC-02, SEC-03, TECH-08, TECH-09, BUG-H3 — каждое с regression-тестом. TECH-03 и пагинация — этап 5.
