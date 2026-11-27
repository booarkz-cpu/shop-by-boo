# Технологический стек

Версии ниже соответствуют файлам этой ревизии. Для мобильных приложений источниками служат Gradle и проекты Xcode. Загрузки дистрибутива v28.161.0 и мобильных выпусков приведены в [README](../README.md).

## Backend

| Компонент | Версия | Файл | Назначение |
| --- | --- | --- | --- |
| Python runtime | 3.15.2-slim (pinned digest) | `services/backend/Dockerfile` | production runtime; точный digest синхронизирован с Compose и установщиком |
| Python compatibility gate | 3.14 + 3.15 | `.github/workflows/ci.yml` | полный backend suite в двух shards на обеих версиях; 3.14 сохранён как обратный compatibility gate. Lint, audit и остальные workflow-задания идут на 3.15 |
| FastAPI | 0.165.0 | `requirements.txt` | REST API, зависимости, OpenAPI |
| Starlette | 1.10.0 | `requirements.txt` | ASGI-основа FastAPI |
| Uvicorn | 0.54.0 (`[standard]`) | `requirements.txt` | ASGI-сервер |
| SQLAlchemy | 2.1.9 (`[asyncio]`) | `requirements.txt` | ORM, async-сессии |
| asyncpg | 0.32.0 | `requirements.txt` | драйвер PostgreSQL |
| Alembic | 1.20.1 | `requirements.txt` | миграции (88 ревизий) |
| aiogram | 3.34.0 | `requirements.txt` | Telegram-бот |
| aiohttp | 3.14.5 | `requirements.txt` | HTTP-клиент бота |
| httpx | 0.28.1 | `requirements.txt` | HTTP-клиент API и проверок |
| h2 | 4.4.1 | `requirements.txt` | HTTP/2 для httpx |
| redis | 8.2.0 | `requirements.txt` | клиент Redis |
| pydantic-settings | 2.16.3 | `requirements.txt` | конфигурация из окружения |
| PyJWT | 2.15.1 | `requirements.txt` | токены сессий и агентов |
| cryptography | 50.0.2 | `requirements.txt` | подписи, шифрование секретов |
| python-multipart | 0.0.34 | `requirements.txt` | загрузка файлов |
| paramiko | 5.1.0 | `requirements.txt` | SSH-терминал узлов |
| boto3 | 1.44.11 | `requirements.txt` | S3-совместимое хранилище копий |
| qrcode `[pil]` | 8.2 | `requirements.txt` | QR конфигураций |
| Pillow | 13.0.0 | `requirements.txt` | обработка изображений |
| PyYAML | 6.0.3 | `requirements.txt` | конфиги Caddy и правила |
| reportlab | 5.1.0 | `requirements.txt` | PDF-отчёты и чеки |
| webauthn | 3.0.1 | `requirements.txt` | passkeys (WebAuthn) |
| maxminddb | 3.3.0 | `requirements.txt` | география GeoLite2 |

## Тесты

| Компонент | Версия | Файл |
| --- | --- | --- |
| pytest | 9.2.0 | `requirements-test.txt` |
| pytest-asyncio | 1.4.1.post1 | `requirements-test.txt` |
| pytest-timeout | 2.4.0 | `requirements-test.txt` |
| aiosqlite | 0.22.1 | `requirements-test.txt` (локальный SQLite-прогон) |
| Vitest | см. `apps/user-cabinet/package.json` | модульные тесты кабинета |
| Playwright | см. `apps/lucy-admin/web/package.json` | e2e в браузере |

## Frontend

| Компонент | Версия | Где | Назначение |
| --- | --- | --- | --- |
| Node.js | 26 LTS | CI (`node-version: "26"`), образы `node:26-alpine` | сборка фронтендов |
| Next.js | 16.4.4 | `admin`, `cabinet` | SSR-сборка, статический экспорт |
| React | 19.3.1 | `admin`, `cabinet` | интерфейс |
| React DOM | 19.3.1 | `admin` | рендер |
| TypeScript | 7.0.2 | `admin` | строгая типизация |
| Tailwind CSS | ^4.3.3 | `admin` | стили |
| nginx | 1.30 (pinned digest) | `apps/lucy-admin/web/Dockerfile`, `apps/user-cabinet/Dockerfile`, `miniapp` | раздача собранной статики |

Шрифты интерфейса: **Inter** (текст) и **JetBrains Mono** (технические данные), заданы в стилях
панели и кабинета.

## Мобильные приложения

| Платформа и версия в исходниках | Стек | Каталоги |
| --- | --- | --- |
| VPN Shop Android 3.9.2 | AGP 9.5.2, Kotlin 2.4.21, Jetpack Compose, встроенный **Xray-core** (`libv2ray.aar`) | `apps/vpn-shop/android` |
| Corgi Lucy Client Android 1.10.3 | AGP 9.5.3, Kotlin 2.4.21, Jetpack Compose, встроенный **Xray-core** (`libv2ray.aar`) | `apps/vpn-client/android` |
| Lucy Admin Android 3.9.2 | AGP 9.5.3, Kotlin 2.4.21, Jetpack Compose | `apps/lucy-admin/android` |
| VPN Shop iOS 3.9.2 | Swift 6, SwiftUI, **LibXray** + HevSocks5Tunnel | `apps/vpn-shop/ios` |
| Lucy Admin iOS 3.9.2 | Swift 6, SwiftUI | `apps/lucy-admin/ios` |

Все три Android-приложения используют Gradle 9.9.2 и Compose BOM 2026.11.01, собираются с API 37.1, минимальным API 26 и целевым API 36. Каждый Gradle Wrapper проверяет SHA-256 ZIP по `distributionSha256Sum`. [Контрольные суммы Gradle](https://gradle.org/release-checksums/).

| Android build chain | Проверенный upstream | Совместимость | Лицензия |
| --- | --- | --- | --- |
| Android Gradle Plugin | [9.5.3](https://developer.android.com/reference/tools/gradle-api) | Gradle не ниже 9.6; API 37 | Apache-2.0 |
| Gradle | [9.9.2](https://gradle.org/releases/) | JDK 17+; проект проверяет официальный `-bin` SHA-256 | Apache-2.0 |
| Kotlin / Compose compiler | [2.4.21](https://github.com/JetBrains/kotlin/releases/tag/v2.4.21) | закреплён одинаково во всех трёх проектах | Apache-2.0 |
| Jetpack Compose BOM | [2026.11.01](https://developer.android.com/develop/ui/compose/bom/bom-mapping?from=2026.09.00&to=2026.11.01) | согласованный набор AndroidX Compose | Apache-2.0 |

Тесты: XCUITest на симуляторе, UI-тесты на эмуляторе Android, Maestro (`mobile/maestro`).

## Данные и инфраструктура

| Компонент | Версия | Файл | Назначение |
| --- | --- | --- | --- |
| PostgreSQL | 19.0-alpine (pinned digest) | `docker-compose.yml` | основная БД и Support Pro; том 18 остаётся для отката |
| Redis | 8.10-alpine (pinned digest) | `docker-compose.yml` | блокировки, кэш |
| Caddy | 2.11, build из `infrastructure/reverse-proxy/caddy` | `docker-compose.yml` | TLS, HTTP/3, маршруты |
| Prometheus | конфиг `infrastructure/monitoring/prometheus` | `prometheus.example.yml`, `vpnshop-alerts.yml` | метрики и алерты |
| Grafana | 2 дашборда | `infrastructure/monitoring/grafana/*.json` | `vpnshop-operations`, `vpnshop-platform` |
| WireGuard | конфиг `infrastructure/deployment/wireguard` | — | служебный туннель |
| OWASP ZAP | `.zap/` | — | сканирование в CI |

Все внешние образы закреплены по digest `@sha256:` — это исключает подмену тега.

## CI/CD

| Компонент | Что делает |
| --- | --- |
| GitHub Actions | 21 workflow обеспечивает CI, сборку контейнеров и приложений, публикацию, проверку зависимостей и эксплуатационные проверки |
| [`actions/checkout` 7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) (`3d3c42e5aac5ba805825da76410c181273ba90b1`), [`setup-java` 6.3.0](https://github.com/actions/setup-java/releases/tag/v6.3.0) (`d1374f8ac74474200d16ef8ecee22c7ae7a51880`), [`setup-go` 7.1.0](https://github.com/actions/setup-go/releases/tag/v7.1.0) (`d8cbb8045d7f43706b9177cceb36c1f91a6644d5`) | официальные stable закреплены по immutable commit SHA во всех workflow; лицензия каждого action — MIT; для Java сохранены аннотации компилятора (`problem-matcher: true`) |
| `actions/setup-python@v7`, `setup-node@v7`, `github-script@v9` | подготовка Python и Node.js, вызовы GitHub API |
| `actions/upload-artifact` 7.0.2 | Сохраняет отчёты k6 и ZAP, результаты тестов и мобильные сборки. Во всех workflow закреплён один коммит `cf430e030ddbb5b0abf93d22962f4752f3646cd9`. Лицензия MIT. [Upstream](https://github.com/actions/upload-artifact/releases/tag/v7.0.2) |
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
