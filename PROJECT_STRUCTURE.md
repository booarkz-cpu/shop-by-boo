# Shop by Boo — структура проекта

Дистрибутив `v28.31.0`, runtime/API `21.5.1`. Полный список всех отслеживаемых файлов: [PROJECT_FILE_MAP.md](docs/PROJECT_FILE_MAP.md).

Каноническая карта каталогов для текущего стабильного runtime. Репозиторий использует FastAPI/aiogram на backend и React/Vite для web-клиентов. Это зафиксированное архитектурное решение: переход на Next.js App Router потребует отдельного миграционного релиза с переносом маршрутизации, SSR-контрактов и E2E, поэтому текущие production-контракты не маскируются под Next.js.

## Корень

```text
shop-by-boo/
├── backend/                 FastAPI API, модели, миграции и фоновые операции
│   ├── app/                 роутеры, безопасность, платежи, provisioning, support
│   ├── alembic/             миграции PostgreSQL/SQLite
│   └── requirements*.txt    runtime и test зависимости Python
├── bot/                     Telegram bot и worker handlers
├── admin/                   Next.js (static export) админская панель
│   ├── src/app/             App Router: layout и клиентская страница
│   ├── src/                 feature-модули, admin-shell, dashboard, theme.css
│   └── e2e/                 Chromium workflows
├── cabinet/                 Next.js кабинет пользователя и Telegram Mini App (telegram.ts, scripts/csp-externalize.mjs)
├── miniapp/                 Docker-образ Mini App: сборка кабинета с NEXT_PUBLIC_SURFACE=miniapp
├── mobile/                  Android/iOS клиентские и admin исходники
├── desktop/                 контракты desktop WireGuard shell
├── support-pro/             изолированный сервис поддержки
├── deploy/                  production installer и operational scripts
├── scripts/                 тесты, диагностика, backup и release packaging
├── tests/                   backend unit/integration/PostgreSQL regression tests
├── docs/                    актуальные инструкции, карта покрытия и архивы
├── docker-compose.yml       локальный и тестовый orchestration
├── .env.example             полный контракт конфигурации без секретов
└── .github/workflows/       CI, Docker, deploy, mobile и release workflows
```

## Границы модулей

| Контур | Владелец | Правило изменений |
| --- | --- | --- |
| Identity/security | `backend/app/security.py`, `passkeys.py`, `customer_passkeys.py`, `account_merge.py` | Любая новая auth-функция требует негативного теста и аудита; merge требует обе стороны, preview и reconciliation |
| Commerce/payments | `backend/app/subscription_commerce.py`, `payments.py`, `payment_policy.py` | Финансовые записи неизменяемы; webhook идемпотентен |
| Remnawave/provisioning | `backend/app/remnawave.py`, `provisioner.py`, `subscriptions.py` | Повторная операция безопасна, ownership проверяется до remote-вызова |
| Telegram | `bot/`, `backend/app/bot*` | Bot/Mini App не дублируют бизнес-правила API |
| Web UI | `admin/src`, `cabinet/src`, `miniapp/src` | Визуальные токены общие, бизнес-логика остаётся в API/feature-модулях |
| Operations | `deploy/`, `scripts/`, `.github/workflows/` | Backup/restore и release contract проверяются CI |
| Live configuration | `backend/app/runtime_settings.py`, `admin/src/runtime-settings.tsx` | Только явно типизированные поля; секреты маскируются; применение версионировано и аудируется |

## Конфигурация

1. Скопируйте `.env.example` в `.env`.
2. Заполните только секреты владельца: bot token, database URL, Remnawave credentials, payment secrets, alert chat IDs.
3. Для локальных тестов используйте `.env.test.example`; production secrets не коммитятся.
4. Перед запуском проверьте `bash scripts/test-up.sh` и `python scripts/check-current-docs.py`.

## Рабочий поток релиза

Изменение проходит проверки Python, браузерные сценарии, типы и сборки, затем CI и Docker на точном коммите `main`. Workflow формирует детерминированный архив, SHA-256 и манифест. Publisher проверяет загруженные файлы и неизменность коммита до публикации, затем запускает Docker на релизном теге.

| Модуль | Назначение |
| --- | --- |
| `admin/src/components/ui/` | shadcn/Radix кнопки, меню, списки и tooltip |
| `admin/src/components/field-hints.tsx` | Контекстная помощь RU/EN для динамических форм |
| `admin/src/components/select-field.tsx` | Адаптер существующих форм к Radix Select |
| `backend/app/account_merge.py` | Двухсторонняя авторизация, conflict preview, атомарный перенос, aliases и retry journal |
| `backend/alembic/versions/0063_account_merge.py` | Merge schema и credential-specific passkey handles |
| `cabinet/src/account-merge.tsx` | Двухшаговый доступный интерфейс объединения аккаунтов |
| `docs/ru/ACCOUNT_MERGE_CURRENT.md` | Пользовательский, security и операторский регламент merge |
| `backend/app/runtime_settings.py` | Полный реестр, проверка зависимостей, шифрование, stage/apply/rollback и polling |
| `backend/alembic/versions/0064_runtime_settings.py` | Версия и защищённая история runtime-настроек |
| `backend/app/history_import.py` | Версионированный перенос истории подписок/платежей: сверка, повтор без дублей, откат |
| `backend/alembic/versions/0065_history_import.py` | Журнал переноса истории, импортированные платежи и связи подписок |
| `backend/alembic/versions/0066_push_notifications.py` | Реестр push-устройств и очередь доставки FCM/APNs |
| `backend/app/push.py` | Регистрация push-токенов, доставка FCM/APNs, отзыв при выходе и потере токена |
| `backend/alembic/versions/0067_plugin_runtime.py` | Издатели, пакеты, установки и доставки плагинов |
| `backend/alembic/versions/0072_traffic_analysis.py` | Вид срабатывания в счётчиках торрентов |
| `backend/alembic/versions/0073_e2e_v2.py` | Проверки staging E2E v2: запуски, случаи по платёжным системам, зашифрованные webhook для повтора |
| `backend/alembic/versions/0074_automation_engine.py` | Однократные выполнения правил автоматизации, обратимое ограничение подписок |
| `backend/alembic/versions/0075_app_config.py` | Согласия с офертой и сумма платежей Telegram Stars |
| `backend/app/app_config.py` | Конфигурация Mini App `GET /api/app-config`, согласие с офертой, редактор в админке |
| `backend/alembic/versions/0076_growth.py` | Места в семье, хеш IP пробных периодов, комиссия за подарок, события Remnawave, подписки Stars, семьи, причины отмены |
| `backend/app/telegram_stars.py` | Telegram Stars: пополнение кошелька, подписка с автопродлением каждые 30 дней, проверка, зачисление, возврат |
| `backend/app/remnawave_events.py` | Подписанные вебхуки Remnawave: уведомления клиентам, события автоматизации, защита пробного периода (IP, Telegram, HWID) |
| `backend/app/growth.py` | Семейная подписка, аналитика удержания, публичный статус сервиса |
| `scripts/upgrade-postgres.sh` | Перенос данных PostgreSQL 16 в PostgreSQL 18 при обновлении |
| `backend/app/network_intel.py` | ASN, владелец сети и репутация адресов узлов с кэшем свежести |
| `backend/app/plugins.py` | Среда плагинов: подписанные пакеты и каталоги, подтверждение прав, API плагина, подписанные события |
| `backend/app/widget.py` | Минимальная сводка подписки для виджета Android с кэшем трафика |
| `support-pro/app/email_channel.py` | Email-канал Support Pro: приём IMAP, цепочки, ответы SMTP, удаление и срок хранения |
| `backend/app/customer_profile.py` | Профиль клиента: имя и способы входа |
| `cabinet/src/telegram.ts` | Обёртка Telegram WebApp SDK: тема, haptics, BackButton/MainButton |
| `cabinet/scripts/csp-externalize.mjs` | Перенос inline-скриптов Next.js в файлы для строгой CSP |
| `admin/src/runtime-settings.tsx` | Поиск, группы, preview, история и deployment-классификация |
| `docs/ru/RUNTIME_SETTINGS_CURRENT.md` | Операторская инструкция live-config |
| `backend/app/release_identity.py` | Версия дистрибутива независимо от API |
| `scripts/package-distribution.py` | Архив, checksum и detached manifest |
| `scripts/publish-github-release.cjs` | Проверка и публикация GitHub Release |
| `scripts/generate-project-map.py` | Полная проверяемая карта файлов |


Release не объявляется production-ready, если не подтверждены provider E2E, owner signing mobile assets и внешний Remnawave stand.

