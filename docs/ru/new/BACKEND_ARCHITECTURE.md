# Устройство backend

Один процесс FastAPI (`backend/app/main.py`, сервис `backend` и резерв `backend_standby`), фоновый `worker` (`backend/worker.py`) и бот (`backend/app/bot.py`, aiogram) работают на одном коде, одной базе PostgreSQL и одном Redis. Support Pro — отдельное приложение со своей базой (`support-pro/`), с магазином связано мостом `shop_bridge`. Правила API — [API.md](API.md), таблицы — [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).

## Клиенты и общий код

| Клиент | Как обращается к магазину |
| --- | --- |
| Админ-панель (`apps/lucy-admin/web/`) | `/api/admin/*`, права роли |
| Личный кабинет и Mini App (`apps/user-cabinet/`; Mini App — та же сборка с `NEXT_PUBLIC_SURFACE=miniapp`) | `/api/me/*`, `/api/app-config`, `/api/payments/*` |
| Приложения Android и iOS (`mobile/android-*`, `mobile/ios-*`) | те же `/api/me/*`, а также `/api/mobile/*` (макет экранов, события) |
| Telegram-бот | вызывает модули магазина напрямую в том же коде. Покупку бот отдаёт Mini App, оплата Stars идёт через `telegram_stars.py` в ту же функцию подтверждения |
| Worker | расписания: продления, напоминания, сверка с Remnawave, резервные копии, рассылки |

Своей бизнес-логики у клиентов нет. Цены, сроки, лимиты и выдачу доступа считает только backend.

## Деньги и доступ: где что происходит

```
покупка, продление (кабинет / Mini App / приложение / бот → Mini App)
        │ POST /api/payments/create + Idempotency-Key
        ▼
провайдер ──► вебхук (подпись) ──► payments_api._confirm_and_fulfill_payment
                                    │  блокировки, financial_ledger, одна выдача
                                    ▼
подарочный код ──► gift_orders ──► RemnawaveClient (remnawave.py)
ручная выдача, бонусные дни ──────►   create_user / extend_idempotent / update_entitlements
семья, компания ──► seat_access ──►
```

| Операция | Единственное место | Кто вызывает |
| --- | --- | --- |
| Подтверждение оплаты любого провайдера | `payments_api._confirm_and_fulfill_payment` | вебхуки `payments_api`, общий помощник шлюзов `gateways/common.py`, Telegram Stars, сверка `schedulers`, песочница, восстановление |
| Создание пользователя в панели для своей подписки клиента | `payments_api` (покупка), `gift_orders` (подарочный код) | — |
| Продление своей подписки | `extend_idempotent`: `payments_api`, `gift_orders`, ручная выдача `admin_api`, бонусные дни `bonus_days` | — |
| Смена тарифа и лимитов | `subscription_commerce` → `update_entitlements` | кабинет, приложения |
| Место в чужой подписке (семья, компания) | `seat_access.grant_seat` / `end_seat` (с v28.59.0) | `growth.sync_member`, `corporate.sync_member` |

Список закреплён тестом `tests/test_single_business_logic.py`. Если новый модуль сам создаёт или продлевает пользователя панели, тест падает с его именем, и решать, нужен ли второй путь, приходится явно.

## Модули по областям

| Область | Модули |
| --- | --- |
| Приложение, промежуточный слой, лимиты, CSRF, ошибки | `main.py`, `runtime_security.py`, `security.py` (RBAC), `config.py`, `db.py` |
| Вход и сессии | `auth_api.py`, `admin_auth_api.py`, `app_login.py`, `passkeys.py`, `customer_passkeys.py`, `account_merge.py` |
| Каталог и покупка | `tariff_api.py`, `subscription_commerce.py`, `subscriptions.py`, `payments_api.py`, `payments.py`, `gateways/`, `telegram_stars.py`, `payment_platform_api.py` |
| Подарки, промо, рефералы, партнёры | `gift_orders.py`, `gift_batches.py`, `promo_generator.py`, `referrals.py`, `referral_program.py`, `partners.py` |
| Remnawave | `remnawave.py` (клиент), `panel_admin.py`, `remnawave_events.py`, `sub_proxy.py`, `node_health.py`, `node_autoscale.py`, `provisioner.py` |
| Семья и компании | `growth.py`, `corporate.py`, `seat_access.py` |
| Контент и бот | `bot.py`, `menu_tree.py`, `bot_banners.py`, `info_pages.py`, `app_config.py`, `mobile_layout.py` |
| Эксплуатация | `operations_api.py`, `ops_alerts.py`, `backups_api.py`, `backup_verify.py`, `integrity.py`, `heartbeat.py`, `hot_standby.py` |
| Импорт | `history_import.py`, `admin_customer_operations.py` |

## Согласованность данных

- Модели и миграции описывают одну схему — `tests/test_schema_matches_migrations.py`.
- Во многих таблицах связи по `*_id` держит код, а не внешние ключи. Отчёт «Целостность данных» (`integrity.py`, `GET /api/admin/integrity`, раздел «Аналитика → Запуск и оповещения») показывает записи без связи по 16 связям денег и доступа. Внешние ключи можно включать, когда отчёт пуст на реальных установках. Порядок: `NOT VALID`, затем `VALIDATE`.
- `subscriptions.remnawave_uuid` хранит числовой id пользователя Remnawave 3.x. Колонка не переименована, чтобы не ломать установки, резервные копии и выгрузки; в коде для неё есть синоним `Subscription.remnawave_user_id`.

## Изменения этапа 5 (v28.59.0)

| Что | Где | Тест |
| --- | --- | --- |
| Общая выдача мест семьи и компаний вместо двух копий | `seat_access.py` | `test_single_business_logic.py`, `test_corporate.py`, `test_growth.py` |
| Защита от второй копии бизнес-логики | — | `test_single_business_logic.py` |
| Единый формат ошибки 500 с `request_id` | `errors.py` | `test_error_format.py` |
| Страницы списков: `limit`, `offset`, `X-Total-Count`; аналитика оплат по периоду с суммами в базе | `pagination.py`, `payment_platform_api.py`, `enterprise_api.py` | `test_pagination.py` |
| Отчёт целостности | `integrity.py`, админка `ops.tsx` | `test_integrity_report.py` |
| Колонка «Доступ» (право или вид вызывающего) в перечне API | `scripts/generate-api-docs.py` | `test_current_documentation.py` |
| Схема базы из моделей | `scripts/generate-db-schema.py` | `test_database_schema_doc.py` |
| Разбор DMARC через `defusedxml` | `mail_domain.py` | `test_mail_domain.py` |
| Синоним `remnawave_user_id` | `models.py` | `test_corporate.py`, `test_growth.py` |

## Что не сделано и почему

| Что | Почему | Когда |
| --- | --- | --- |
| Внешние ключи в базе | Сначала нужен пустой отчёт целостности на реальной установке; без него миграция может не пройти | после проверки на сервере (этапы 10, 18) |
| Вход клиента через общую зависимость FastAPI вместо вызова в обработчике | 150+ маршрутов, у части из них свои варианты: владелец, партнёр, Mini App. Пропуск проверки ловит тест маршрутов | постепенно, при изменении маршрутов |
| Пагинация всех старых списков | Меняет поведение экранов админки; переводятся вместе с экранами | этап 6 |
| Таблицы доменов и сертификатов | Появятся вместе с менеджером доменов | этап 11 |
