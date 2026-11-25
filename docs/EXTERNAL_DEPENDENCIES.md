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
| PostgreSQL 19.0 | `DATABASE_URL`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Backend не стартует |
| Redis 8.10 | `REDIS_URL` | `/health/ready` → `redis: false`, фоновые блокировки не работают |
| Секрет приложения | `APP_SECRET` | Сессии не подписываются, старт отклоняется |
| Медиа-каталог | `MEDIA_DIR` | Ошибка `StaticFiles` при импорте |

### PostgreSQL 19.0

Магазин, Support Pro и тестовые профили используют официальный образ
`postgres:19.0-alpine@sha256:cac45fb483caee3668946088a1c0532db89d5285c28dbfeac889b4068296e06f`
(индекс манифеста с registry-1.docker.io на 2026-11-24). Каталог данных лежит в новых томах
`*postgres19_data`. `scripts/upgrade-postgres19.sh` переносит данные из томов PostgreSQL 18
через `pg_dump -Fc`, сверяет число строк, делает `ANALYZE` и оставляет том 18 и дамп.
В учениях CI магазин и Support Pro получают разные тестовые данные. После переноса, восстановления
каждого дампа и старта копии каждого тома PostgreSQL 18 проверяются версия сервера, имя базы
и SHA-256 всех полей 1500 заказов и 42 идентификаторов пользователей. Исходные тома для проверки
отката монтируются только для чтения.
Скрипт не удаляет тома. Нехватка места и сбой `pg_restore` останавливают перенос, не трогая том 18.
Живой VPS этим изменением не мигрировался. PASS реестра не менялся.

Источник образа: [Docker Official Image](https://hub.docker.com/_/postgres). Лицензия PostgreSQL —
[PostgreSQL License](https://www.postgresql.org/about/licence/).

В CI `python3 scripts/ci/check-compose-profiles.py` проверяет состав сервисов во всех
комбинациях профилей. Магазин и интеграционная конфигурация включают `mail_receiver` через
`mail` и `backend_standby` через `standby`. У автономного Support Pro сервис `clamav`
включается через `antivirus`. Проверка рендерит также локальную тестовую конфигурацию.
Для воспроизведения в чистой рабочей копии подготовьте `.env` и `.env.test` из одноимённых
шаблонов `.example`, а `support-pro/.env` и `services/support-pro/.env` — из
`services/support-pro/.env.example`. Проверку готовности запущенных сервисов выполняют
отдельные контейнерные задания CI. Задание Containers запускает резервный API и почтовый
приёмник на изолированной БД. Оно проверяет состояние healthcheck, UID 10001, файловую
систему только для чтения, HTTP на резервном API и SMTP EHLO на приёмнике. Почтовое
сообщение не создаётся. В образе backend без аргументов запускается API, а сервис
с командой Compose получает её после успешной миграции.

В автономном Support Pro профиль `antivirus` использует Debian-образ ClamAV для Linux amd64 и arm64.
В CI на обеих нативных архитектурах клиент загрузки Support Pro передаёт в clamd обычный файл
и файл с локальной тестовой сигнатурой. Сервис использует частный порт 3310 и сохраняет базы в томе `clamdata`.
[Образы проекта ClamAV](https://github.com/Cisco-Talos/clamav-docker)

### Версии и лицензии программ в контейнерах

Снимок проверен 26 ноября 2026 года по 15 файлам конфигурации, Dockerfile и скриптам переноса. Для каждого из 17 закреплений проверены SHA-256 самого OCI-индекса и дочерних манифестов и конфигураций linux/amd64 и linux/arm64. В таблице указан индекс, используемый при сборке или запуске. [Проверенная ревизия](https://github.com/booarkz-cpu/shop-by-boo/tree/6fd0aa3a37ec10478761dba31dd22a54528b50a8).

| Использование | Программа и версия | SHA-256 OCI-индекса | Лицензия программы |
| --- | --- | --- | --- |
| Backend, bot, Support Pro | CPython 3.15.2 | `65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928` | [PSF License Version 2](https://github.com/python/cpython/blob/v3.15.2/LICENSE) |
| Магазин и Support Pro | PostgreSQL 19.0 | `cac45fb483caee3668946088a1c0532db89d5285c28dbfeac889b4068296e06f` | [PostgreSQL License](https://github.com/postgres/postgres/blob/REL_19_0/COPYRIGHT) |
| Перенос и откат обеих баз | PostgreSQL 18.7 | `ff64c9e3bdf8e2120107d3559de8db314e8305f7e38c5105903c6295876738ff` | [PostgreSQL License](https://github.com/postgres/postgres/blob/REL_18_7/COPYRIGHT) |
| Чтение старых томов при переносе | PostgreSQL 16.15 | `721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea` | [PostgreSQL License](https://github.com/postgres/postgres/blob/REL_16_15/COPYRIGHT) |
| Отдельная база плана Remnawave | PostgreSQL 18.4 | `a02db8cac496f15b094798a38254f14d6e00741f709360e5e00bb6668ea31636` | [PostgreSQL License](https://github.com/postgres/postgres/blob/REL_18_4/COPYRIGHT) |
| Магазин и Support Pro | Redis Open Source 8.10.3 | `71885d8cc6e42f2bc0aa2eb853bfc4be200b5108a46ac50e117ae1df0531fb80` | [RSALv2, SSPLv1 или GNU AGPLv3 по выбору](https://github.com/redis/redis/blob/8.10.3/LICENSE.txt) |
| Сборка трёх веб-приложений | Node.js 26.13.0 | `c6ad9e9c1d80f6eb607c26b4b0a132ff7a2344fad1c78ea3baa2a7d4c8de6d94` | [MIT для Node.js](https://github.com/nodejs/node/blob/v26.13.0/LICENSE) |
| Обслуживание трёх веб-приложений | nginx 1.30.7 | `3bc3836dc0be3b811f238210360bf8e7ca8a2d0effdae46160bf1f3578710051` | [BSD-2-Clause](https://github.com/nginx/nginx/blob/release-1.30.7/LICENSE) |
| Автономный Support Pro, снимок до #470 | nginx 1.30.5 | `985220252f3863977e468f611ef118ebd01421289dd86ee1ae99cb068c3bce2b` | [BSD-2-Clause](https://github.com/nginx/nginx/blob/release-1.30.5/LICENSE) |
| Входной прокси | Caddy 2.11.9 | `78bd35025c7ba85961dd149ae670315129954e77abe2383ac47c89106b35ade9` | [Apache-2.0](https://github.com/caddyserver/caddy/blob/v2.11.9/LICENSE) |
| Профиль antivirus Support Pro | ClamAV 1.5.5 | `85f35b3eee903dbd96c5ca250c5aa13d230d97987c0f876f7d46f001f9414239` | [GNU GPLv2](https://github.com/Cisco-Talos/clamav/blob/clamav-1.5.5/COPYING.txt) |
| Хранилище плана Remnawave | Valkey 9.1.3 | `bf09d58e96d6b4524a15396b65b242bbe18beebbcc15a04d8ee75ddac62fae0b` | [BSD-3-Clause](https://github.com/valkey-io/valkey/blob/9.1.3/COPYING) |
| Панель Remnawave | Remnawave Panel 3.4.11 | `a5b9f81fe2cfacec1c41bd2bb43fa1a5980228b81aa2e744be4adffa3a00135b` | [GNU AGPLv3](https://github.com/remnawave/backend/blob/3.4.11/LICENCE) |
| Узел Remnawave | Remnawave Node 3.4.6 | `3d5fde656a36920f53c5c080f2dc821df8318f453803b07c4e5242752a549d69` | [GNU AGPLv3](https://github.com/remnawave/node/blob/3.4.6/LICENCE) |
| Страница подписки | Remnawave Subscription Page 8.0.1 | `ba8445b1e0d1c170cf314686ef638b73cabf42a0c6217d027e6cb958ca161ca6` | [GNU AGPLv3](https://github.com/remnawave/subscription-page/blob/8.0.1/LICENCE) |
| Аутентификация плана Remnawave | TinyAuth 5.2.0 | `220aa235c76393a73fece831d7ba967b8698d3907fd8e3c4c952f699c7b142a5` | [GNU AGPLv3](https://github.com/tinyauthapp/tinyauth/blob/v5.2.0/LICENSE) |
| Проверка узлов в плане Remnawave | Xray Checker 1.3.1 | `33c9a4987caa3a5f0af466ae3eeb233b53068931d0e2e7af357d4dfc5269bc4a` | [GNU AGPLv3](https://github.com/kutovoys/xray-checker/blob/v1.3.1/LICENSE) |

Источники в последнем столбце относятся к коду программы соответствующей версии. Пакеты дистрибутива, нативные библиотеки и встроенные сторонние компоненты имеют собственные условия. В LICENSE Node.js и CPython перечислены также лицензии включённых компонентов.

В указанном снимке тег `nginx:stable-alpine` у автономного Support Pro закреплён на nginx 1.30.5. Проверенный индекс для перехода на 1.30.8 — `8eb04fe3b385090e9aa02961f77398ad09b6bf33ab07f6669a5bb7acce22c0d3`. Образы трёх веб-приложений используют отдельное закрепление. [Изменение Support Pro](https://github.com/booarkz-cpu/shop-by-boo/pull/470) · [Лицензия nginx 1.30.8](https://github.com/nginx/nginx/blob/release-1.30.8/LICENSE).


### Образы инструментов сборки и CI

Оба тега закреплены по SHA-256 OCI-индекса. Для каждого проверены манифесты и конфигурации linux/amd64 и linux/arm64.

| Использование | Версия программы | SHA-256 OCI-индекса | Лицензия программы |
| --- | --- | --- | --- |
| Компиляция входного прокси Caddy | Go 1.27.4, Alpine | `70bd7ddea8b6cbe5d6943cde279d6b67feb10cc924fb9100d1d8757c1575b280` | [BSD-3-Clause](https://github.com/golang/go/blob/go1.27.4/LICENSE) |
| Проверка и тестирование правил оповещения | Prometheus promtool 3.5.0 | `63805ebb8d2b3920190daf1cb14a60871b16fd38bed42b857a3182bc621f4996` | [Apache-2.0](https://github.com/prometheus/prometheus/blob/v3.5.0/LICENSE) |

### Схемы баз данных

| Источник | Магазин | Support Pro |
| --- | --- | --- |
| Опубликованный v28.161.0 | `0094_store_subscriptions` | `0008` |
| Текущая рабочая ветка main | `0094_store_subscriptions` | `0009` |

В `0009` PostgreSQL расширяет `operators.totp_secret` до `text`. Откат до `0008` останавливается
при значении с префиксом `sp1:` или длиной больше 64 символов. На отдельной PostgreSQL
задание Support Pro проверяет обе стороны перехода, тип колонки и сохранность значения после
отклонённого отката. Для возврата рабочей установки используйте [согласованную копию](ru/WORKSPACE_UPGRADE.md).

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
| Python | backend production — 3.15.2-slim с digest; backend CI — 3.14 + 3.15; Support Pro production — 3.15; lint, audit, Docker, docs и живые проверки — 3.15 | production переключён после полного matrix gate; 3.14 сохранён только в матрице backend-тестов для обратной совместимости и отката |
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
