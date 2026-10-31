# Внешние зависимости

Дистрибутив `v28.56.0`, runtime/API `21.5.1`.

Перечень всего, без чего часть функций не работает. Для каждой зависимости: зачем нужна, что
происходит без неё, где брать. Пошаговое тестирование — в
[TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md](TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md).

Принцип проекта: **отсутствие ключа не ломает запуск**. Функция отключается, кнопка не показывается
или возвращается понятная ошибка. Это проверено тестами.

## 1. Обязательные (без них магазин не работает)

| Зависимость | Переменные | Без неё |
| --- | --- | --- |
| PostgreSQL 18.6 | `DATABASE_URL`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Backend не стартует |
| Redis 7.4 | `REDIS_URL` | `/health/ready` → `redis: false`, фоновые блокировки не работают |
| Секрет приложения | `APP_SECRET` | Сессии не подписываются, старт отклоняется |
| Медиа-каталог | `MEDIA_DIR` | Ошибка `StaticFiles` при импорте |

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
| Caddy / nginx | сервер | TLS, маршрутизация; `deploy/Caddyfile`, `deploy/nginx/` |
| GitHub Releases | `booarkz-cpu/shop-by-boo` | Источник автообновления и мобильных артефактов |
| Hetzner API | `HETZNER_API_TOKEN` | Автомасштабирование узлов; без него — ручное |

## 4. Инструменты разработки и CI

| Инструмент | Версия в проекте | Где используется |
| --- | --- | --- |
| Python | 3.12 (CI), работает на 3.13 | backend, scripts, tests |
| Node.js | 22 (CI) | admin, cabinet, miniapp |
| ruff | 0.14.2 | lint |
| pytest | 9.1.1 | тесты |
| alembic | 1.20.1 | 88 миграций, head `0088_filter_and_regions` |
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

Код магазина самостоятельный: `backend/app/remnawave.py`, `remnawave_events.py`,
`remnawave_shop_api.py` — собственные реализации, работающие с API Remnawave напрямую.

## 7. Порядок выдачи доступа

1. Определите, какие функции нужны: без Remnawave и платежей магазин не продаёт.
2. Создайте `.env` из `.env.example` — там перечислены все переменные с комментариями.
3. Заполните обязательные (§1), проверьте `docker compose config --quiet`.
4. Запустите базовые тесты — они должны остаться зелёными.
5. Добавляйте функциональные группы по одной, фиксируя результат в таблице гайда.

Никогда не коммитьте `.env`. `.gitignore` уже исключает `.env`, `.env.*`, `node_modules`,
`.rollback`, `.control`.
