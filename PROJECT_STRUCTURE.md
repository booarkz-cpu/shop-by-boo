# Shop by Boo — структура проекта

Каноническая карта каталогов для текущего стабильного runtime. Репозиторий использует FastAPI/aiogram на backend и React/Vite для web-клиентов. Это зафиксированное архитектурное решение: переход на Next.js App Router потребует отдельного миграционного релиза с переносом маршрутизации, SSR-контрактов и E2E, поэтому текущие production-контракты не маскируются под Next.js.

## Корень

```text
shop-by-boo/
├── backend/                 FastAPI API, модели, миграции и фоновые операции
│   ├── app/                 роутеры, безопасность, платежи, provisioning, support
│   ├── alembic/             миграции PostgreSQL/SQLite
│   └── tests/               unit/integration tests
├── bot/                     Telegram bot и worker handlers
├── admin/                   React/Vite админская панель
│   ├── src/                 feature-модули и design-system.css
│   └── e2e/                 Chromium workflows
├── cabinet/                 React/Vite кабинет пользователя
├── miniapp/                 Telegram Mini App оболочка кабинета
├── mobile/                  Android/iOS клиентские и admin исходники
├── desktop/                 контракты desktop WireGuard shell
├── support-pro/             изолированный сервис поддержки
├── deploy/                  production installer и operational scripts
├── scripts/                 тесты, диагностика, backup и release packaging
├── docs/                    актуальные инструкции, карта покрытия и архивы
├── docker-compose.yml       локальный и тестовый orchestration
├── .env.example             полный контракт конфигурации без секретов
└── .github/workflows/       CI, Docker, deploy, mobile и release workflows
```

## Границы модулей

| Контур | Владелец | Правило изменений |
| --- | --- | --- |
| Identity/security | `backend/app/security.py`, `passkeys.py`, `customer_passkeys.py` | Любая новая auth-функция требует негативного теста и аудита |
| Commerce/payments | `backend/app/subscription_commerce.py`, `payments.py`, `payment_policy.py` | Финансовые записи неизменяемы; webhook идемпотентен |
| Remnawave/provisioning | `backend/app/remnawave.py`, `provisioner.py`, `subscriptions.py` | Повторная операция безопасна, ownership проверяется до remote-вызова |
| Telegram | `bot/`, `backend/app/bot*` | Bot/Mini App не дублируют бизнес-правила API |
| Web UI | `admin/src`, `cabinet/src`, `miniapp/src` | Визуальные токены общие, бизнес-логика остаётся в API/feature-модулях |
| Operations | `deploy/`, `scripts/`, `.github/workflows/` | Backup/restore и release contract проверяются CI |

## Конфигурация

1. Скопируйте `.env.example` в `.env`.
2. Заполните только секреты владельца: bot token, database URL, Remnawave credentials, payment secrets, alert chat IDs.
3. Для локальных тестов используйте `.env.test.example`; production secrets не коммитятся.
4. Перед запуском проверьте `bash scripts/test-up.sh` и `python scripts/check-current-docs.py`.

## Рабочий поток релиза

```text
feature change → backend/frontend tests → typecheck/build → Docker/CI
→ documentation contract → review of external gates → release workflow
```

Release не объявляется production-ready, если не подтверждены provider E2E, owner signing mobile assets и внешний Remnawave stand.

