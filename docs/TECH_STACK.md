# Технологический стек

Версии взяты из `backend/requirements.txt`, `*/package.json`, `Dockerfile` и `docker-compose.yml`
на коммите `e3b9387`. Ничего не переписано «по памяти»: каждую строку можно проверить по указанному
файлу.

## Backend

| Компонент | Версия | Файл | Назначение |
| --- | --- | --- | --- |
| Python | 3.12-slim (pinned digest) | `backend/Dockerfile` | язык исполнения |
| FastAPI | 0.161.1 | `requirements.txt` | REST API, зависимости, OpenAPI |
| Starlette | 1.9.0 | `requirements.txt` | ASGI-основа FastAPI |
| Uvicorn | 0.54.0 (`[standard]`) | `requirements.txt` | ASGI-сервер |
| SQLAlchemy | 2.1.6 (`[asyncio]`) | `requirements.txt` | ORM, async-сессии |
| asyncpg | 0.32.0 | `requirements.txt` | драйвер PostgreSQL |
| Alembic | 1.20.1 | `requirements.txt` | миграции (88 ревизий) |
| aiogram | 3.31.0 | `requirements.txt` | Telegram-бот |
| aiohttp | 3.14.5 | `requirements.txt` | HTTP-клиент бота |
| httpx | 0.28.1 | `requirements.txt` | HTTP-клиент API и проверок |
| h2 | 4.4.1 | `requirements.txt` | HTTP/2 для httpx |
| redis | 6.4.0 | `requirements.txt` | клиент Redis |
| pydantic-settings | 2.16.1 | `requirements.txt` | конфигурация из окружения |
| PyJWT | 2.15.1 | `requirements.txt` | токены сессий и агентов |
| cryptography | 50.0.2 | `requirements.txt` | подписи, шифрование секретов |
| python-multipart | 0.0.32 | `requirements.txt` | загрузка файлов |
| paramiko | 5.1.0 | `requirements.txt` | SSH-терминал узлов |
| boto3 | 1.43.118 | `requirements.txt` | S3-совместимое хранилище копий |
| qrcode `[pil]` | 8.2 | `requirements.txt` | QR конфигураций |
| Pillow | 13.0.0 | `requirements.txt` | обработка изображений |
| PyYAML | 6.0.3 | `requirements.txt` | конфиги Caddy и правила |
| reportlab | 4.4.9 | `requirements.txt` | PDF-отчёты и чеки |
| webauthn | 3.0.1 | `requirements.txt` | passkeys (WebAuthn) |
| maxminddb | 2.6.2 | `requirements.txt` | география GeoLite2 |

## Тесты

| Компонент | Версия | Файл |
| --- | --- | --- |
| pytest | 9.1.1 | `requirements-test.txt` |
| pytest-asyncio | 1.4.0 | `requirements-test.txt` |
| pytest-timeout | 2.4.0 | `requirements-test.txt` |
| aiosqlite | 0.22.1 | `requirements-test.txt` (локальный SQLite-прогон) |
| Vitest | см. `cabinet/package.json` | модульные тесты кабинета |
| Playwright | см. `admin/package.json` | e2e в браузере |

## Frontend

| Компонент | Версия | Где | Назначение |
| --- | --- | --- | --- |
| Node.js | 22 | CI (`node-version: "22"`) | сборка фронтендов |
| Next.js | 16.4.2 | `admin`, `cabinet` | SSR-сборка, статический экспорт |
| React | 19.3.1 | `admin`, `cabinet` | интерфейс |
| React DOM | 19.3.1 | `admin` | рендер |
| TypeScript | 7.0.2 | `admin` | строгая типизация |
| Tailwind CSS | ^4.3.3 | `admin` | стили |
| nginx | pinned digest | `admin/Dockerfile`, `cabinet/Dockerfile`, `miniapp` | раздача собранной статики |

Шрифты интерфейса: **Inter** (текст) и **JetBrains Mono** (технические данные), заданы в стилях
панели и кабинета.

## Мобильные приложения

| Платформа | Стек | Каталоги |
| --- | --- | --- |
| Android user | Kotlin, Jetpack Compose, встроенный **Xray-core** (`libv2ray.aar`) | `mobile/android-user` |
| Android admin | Kotlin, Compose | `mobile/android-admin` |
| iOS user | Swift, SwiftUI, **LibXray** + HevSocks5Tunnel | `mobile/ios-user` |
| iOS admin | Swift, SwiftUI | `mobile/ios-admin` |

Версия приложений — **3.4.0** (`versionName`, `MARKETING_VERSION`).
Тесты: XCUITest на симуляторе, UI-тесты на эмуляторе Android, Maestro (`mobile/maestro`).

## Данные и инфраструктура

| Компонент | Версия | Файл | Назначение |
| --- | --- | --- | --- |
| PostgreSQL | 18.6-alpine (pinned digest) | `docker-compose.yml` | основная БД и Support Pro |
| Redis | 7.4-alpine (pinned digest) | `docker-compose.yml` | блокировки, кэш |
| Caddy | build из `deploy/caddy` | `docker-compose.yml` | TLS, HTTP/3, маршруты |
| Prometheus | конфиг `deploy/prometheus` | `prometheus.example.yml`, `vpnshop-alerts.yml` | метрики и алерты |
| Grafana | 2 дашборда | `deploy/grafana/*.json` | `vpnshop-operations`, `vpnshop-platform` |
| WireGuard | конфиг `deploy/wireguard` | — | служебный туннель |
| OWASP ZAP | `.zap/` | — | сканирование в CI |

Все внешние образы закреплены по digest `@sha256:` — это исключает подмену тега.

## CI/CD

| Компонент | Что делает |
| --- | --- |
| GitHub Actions | 15 workflows: CI, Docker, публикация релиза, деплой, мобильные сборки, нагрузка, security, ночные контракты |
| `actions/checkout@v5`, `setup-python@v6`, `setup-node@v7`, `github-script@v9` | актуальные мажоры |
| concurrency | группы привязаны к коммиту: `ci-${ref}-${sha}`, `docker-${ref}-${sha}` |
| permissions | минимальные: `contents: read`, `packages: write` только в Docker |
| gate публикации | `publish-release.yml` требует зелёных `ci.yml` **и** `docker.yml` на том же SHA |

## Внешние интеграции

| Система | Протокол | Переменные |
| --- | --- | --- |
| Remnawave 3.x | REST + webhook | `REMNAWAVE_URL`, `REMNAWAVE_TOKEN`, `REMNAWAVE_WEBHOOK_SECRET` |
| 17 платёжных касс | REST + webhook | по паре ключей на кассу (см. `.env.example`) |
| Telegram Stars | Bot API | `BOT_TOKEN` |
| Telegram Bot API | long polling / webhook | `BOT_TOKEN`, `WEBAPP_URL` |
| VK, Яндекс, Google OAuth | OAuth 2.0 | `*_CLIENT_ID`, `*_CLIENT_SECRET` |
| SMTP | SMTP/TLS | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` |
| FCM, APNs | push | ключи Firebase и APNs |
| RIPE Atlas | REST | ключ с кредитами (опционально) |
| MaxMind | файл GeoLite2 | `MAXMIND_*` (опционально) |
| AbuseIPDB | REST | `ABUSEIPDB_API_KEY` (опционально) |

## Что НЕ используется

Чтобы не приписывать проекту лишнего:

| Технология | Почему нет |
| --- | --- |
| nginx как основной reverse proxy | используется Caddy; nginx только раздаёт статику фронтендов |
| Django / Flask | API на FastAPI |
| MongoDB / MySQL | только PostgreSQL |
| Docker Swarm / Kubernetes | обычный Compose на одном хосте |
| Prometheus + Grafana как обязательные | конфиги есть, но мониторинг опционален |
| Десктопные приложения | в `desktop/` только README |
| Браузерное расширение | в `browser-extension/` заготовка |
| Terraform | один файл, инфраструктура не описана |

## Связанные документы

* [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) — что физически есть в репозитории
* [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) — как компоненты связаны
* [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md) — внешние репозитории и лицензии
* [../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) — сторонние компоненты
