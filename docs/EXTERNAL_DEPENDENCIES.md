# Внешние зависимости

Дистрибутив `v28.161.0`, runtime/API `21.5.1`.

Перечень всего, без чего часть функций не работает. Для каждой зависимости: зачем нужна, что
происходит без неё, где брать. Пошаговое тестирование — в
[TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md](TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md).

Принцип проекта: **отсутствие ключа не ломает запуск**. Функция отключается, кнопка не показывается
или возвращается понятная ошибка. Это проверено тестами.

## 1. Обязательные (без них магазин не работает)

| Зависимость | Переменные | Без неё |
| --- | --- | --- |
| PostgreSQL 18.7 | `DATABASE_URL`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Backend не стартует |
| Redis 7.4 | `REDIS_URL` | `/health/ready` → `redis: false`, фоновые блокировки не работают |
| Секрет приложения | `APP_SECRET` | Сессии не подписываются, старт отклоняется |
| Медиа-каталог | `MEDIA_DIR` | Ошибка `StaticFiles` при импорте |

### PostgreSQL 18.7 patch baseline

Магазин, Support Pro и тестовые профили используют официальный образ
`postgres:18.7-alpine@sha256:ff64c9e3bdf8e2120107d3559de8db314e8305f7e38c5105903c6295876738ff`. Это patch-обновление в пределах major 18; формат каталога данных и тома
`*postgres18_data` не меняются. Официальные [release notes](https://www.postgresql.org/docs/18/release-18-7.html)
не требуют dump/restore для 18.x, но требуют проверить затронутые индексы по пунктам `REINDEX` и
создать новый полный backup вместо доверия прежним incremental backup. Миграция 18→19 остаётся
отдельной задачей: этот baseline не запускает её и не удаляет старые тома.

Источник образа: [Docker Official Image](https://hub.docker.com/_/postgres). Лицензия PostgreSQL —
[PostgreSQL License](https://www.postgresql.org/about/licence/).

## 2. Функциональные (отключаются без ключа)

| Зависимость | Переменные | Что теряется |
| --- | --- | --- |
| Remnawave | `REMNAWAVE_URL`, `REMNAWAVE_TOKEN`, `REMNAWAVE_WEBHOOK_SECRET` | Нет выдачи подписок |
| Telegram Bot API | `BOT_TOKEN`, `ADMIN_TELEGRAM_ID` | Бот не запускается, Mini App не авторизует |
| Платёжные провайдеры | см. §6 гайда | Checkout недоступен, кроме sandbox вне production |
| Яндекс OAuth | `YANDEX_CLIENT_ID`, `YANDEX_CLIENT_SECRET`, `YANDEX_REDIRECT_URI` | Кнопка входа скрыта |
| VK OAuth | `VK_CLIENT_ID`, `VK_CLIENT_SECRET`, `VK_REDIRECT_URI` | Кнопка входа скрыта |
| FCM | `FCM_PROJECT_ID`, `FCM_SERVICE_ACCOUNT_JSON` | Нет push на Android |
| APNs | `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_PRIVATE_KEY`, `APNS_BUNDLE_ID`, `APNS_ENVIRONMENT` | Нет push на iOS |
| S3-совместимое хранилище | `boto3`, креды AWS | Только локальные бэкапы |
| SMTP | параметры почты в `.env` | Нет писем; in-app уведомления работают |

## 3. Инфраструктурные

| Зависимость | Где | Комментарий |
| --- | --- | --- |
| Docker + Compose | сервер | 17 сервисов в `docker-compose.yml` |
| systemd | сервер | Ночное автообновление; без него агент только создаёт `.control` |
| Caddy / nginx | сервер | TLS, маршрутизация; `infrastructure/reverse-proxy/Caddyfile`, `infrastructure/reverse-proxy/nginx/` |
| GitHub Releases | `booarkz-cpu/shop-by-boo` | Источник автообновления и мобильных артефактов |
| Hetzner API | `HETZNER_API_TOKEN` | Автомасштабирование узлов; без него — ручное |

## 4. Инструменты разработки и CI

| Инструмент | Версия в проекте | Где используется |
| --- | --- | --- |
| Python | backend production — 3.14; backend CI — 3.14 + 3.15; Support Pro production — 3.15 | временная совместимость перед переключением backend runtime; обе версии проходят полный backend suite |
| Support Pro runtime | FastAPI 0.165.0; SQLAlchemy 2.1.9; aiogram 3.33.0; Pydantic 2.14.4 / core 2.50.5; OpenTelemetry API 1.45.2 | закреплённый Python 3.15 dependency graph; unit/integration, Alembic, PostgreSQL/Redis и container tests |
| Node.js | 26 LTS (CI и образы) | admin, cabinet, miniapp |
| Web runtime и тесты | Next.js 16.4.6; React 19.3.1; TypeScript 7.0.2; lucide-react 1.77.0; Playwright 1.65.1; jsdom 31.0.1 | Lucy Admin, кабинет и общий dependency graph Telegram Mini App |
| ruff | 0.17.3 | lint |
| pytest | 9.1.1 | тесты |
| alembic | 1.20.1 | 92 миграции, head `0094_store_subscriptions` |
| Gradle / Android SDK | `mobile/android-*` | сборка APK/AAB |
| Xcode | `mobile/ios-*` | сборка IPA |

## 5. Что нельзя проверить без доступа

Полный список со статусами — §14 [гайда по тестированию](TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md).
Кратко: живые Remnawave, Telegram, платежи, OAuth, Docker, установщик, ночное автообновление,
сборка мобильных приложений.

## 6. Сторонние репозитории, изученные при аудите

Проект **не включает** код этих репозиториев: у них свои лицензии, и копирование без проверки
совместимости недопустимо. Они изучены как источник идей и для проверки совместимости API.

| Репозиторий | Лицензия/статус | Как соотносится |
| --- | --- | --- |
| `booarkz-cpu/remnawave-manager` | свой проект владельца, доступ на запись | Управление Remnawave; не дублируется в магазине |
| `eGamesAPI/remnawave-reverse-proxy` | сторонний, только чтение | Референс reverse proxy |
| `Case211/remnawave-admin` | сторонний, только чтение | Референс админки |
| `BEDOLAGA-DEV/remnawave-bedolaga-telegram-bot` | сторонний, только чтение | Референс бота |
| `BEDOLAGA-DEV/bedolaga-cabinet` | сторонний, только чтение | Референс кабинета |
| `STEP-CORP/StepBot` | сторонний, только чтение | Референс бота |

Код магазина самостоятельный: `services/backend/app/remnawave.py`, `remnawave_events.py`,
`remnawave_shop_api.py` — собственные реализации, работающие с API Remnawave напрямую.

## 7. Порядок выдачи доступа

1. Определите, какие функции нужны: без Remnawave и платежей магазин не продаёт.
2. Создайте `.env` из `.env.example` — там перечислены все переменные с комментариями.
3. Заполните обязательные (§1), проверьте `docker compose config --quiet`.
4. Запустите базовые тесты — они должны остаться зелёными.
5. Добавляйте функциональные группы по одной, фиксируя результат в таблице гайда.

Никогда не коммитьте `.env`. `.gitignore` уже исключает `.env`, `.env.*`, `node_modules`,
`.rollback`, `.control`.
