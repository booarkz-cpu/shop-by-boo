# Инвентаризация проекта — VPN Shop by Corgi Lucy

Дистрибутив `v28.57.0`, runtime/API `21.5.1`, миграция магазина `0088_filter_and_regions`,
Support Pro `0008`, мобильные приложения 3.4.0.

Все числа в этом документе получены из репозитория на коммите `e3b9387` (`main`), а не из README:
`git ls-files`, таблица маршрутов собранного приложения, `alembic heads`, `docker-compose.yml`.
Дата снимка — 2026-11-01.

## 1. Состояние репозитория

| Параметр | Значение |
| --- | --- |
| Ветка | `main` (единственная; `remotes/origin/main` — та же) |
| Последний коммит | `e3b9387` — `docs(log): фактическое состояние публикации v28.57.0` |
| Рабочее дерево | чистое |
| Файлов под контролем версий | **1991** |
| Каталог `.git` | 244 МБ |
| Рабочее дерево без `.git` | 107 МБ |
| Тегов | **51** (`v28.1.0` … `v28.57.0`) |
| Опубликованных релизов | 100 страниц по API, последний — `v28.57.0` (`2026-11-01`) |

## 2. Состав по типам файлов

| Расширение | Файлов | Что это |
| --- | --- | --- |
| `.md` | 586 | документация, включая архив |
| `.py` | 582 | backend, тесты, скрипты |
| `.png` | 235 | скриншоты интерфейсов |
| `.tsx` | 129 | админ-панель и кабинет |
| `.jpg` | 113 | баннеры бота и скриншоты |
| `.sh` | 45 | установка, эксплуатация, релиз |
| `.json` | 32 | манифесты, конфиги |
| `.ts` | 26 | клиентская логика, e2e |
| `.kt` | 24 | Android (user и admin) |
| `.html` | 24 | статические страницы отчётов |
| `.yml` | 23 | workflows и конфиги |
| `.swift` | 10 | iOS (user и admin) |

## 3. Состав по каталогам

| Каталог | Файлов | Назначение |
| --- | --- | --- |
| `docs/` | 573 | документация на трёх языках + архив |
| `backend/` | 331 | API, бот, worker, миграции |
| `tests/` | 228 | pytest-набор |
| `mobile/` | 176 | Android и iOS, user и admin |
| `screenshots/` | 142 | галереи интерфейсов |
| `admin/` | 120 | админ-панель (Next.js) |
| `cabinet/` | 110 | личный кабинет и Mini App (Next.js) |
| `support-pro/` | 93 | отдельный сервис поддержки |
| `scripts/` | 77 | эксплуатация и релиз |
| `.github/` | 61 | 15 workflows, соглашения |
| `deploy/` | 18 | Caddy, nginx, prometheus, grafana, wireguard, mail-tls |
| `miniapp/` | 6 | nginx-конфигурация Mini App |
| `desktop/` | 4 | README-заготовки для трёх ОС |
| `browser-extension/` | 2 | заготовка расширения |
| `terraform/` | 1 | заготовка инфраструктуры |

## 4. Backend

| Параметр | Значение |
| --- | --- |
| Python-модулей в `backend/app` | **173** |
| Строк в `backend/app` | **45 728** |
| Крупнейшие модули | `models.py` 2166, `mail_domain.py` 1052, `payments.py` 1046, `payments_api.py` 1009, `main.py` 991, `e2e_v2.py` 959, `runtime_settings.py` 956 |
| Маршрутов (метод, путь) | **836** |
| Уникальных путей | **718** |
| Миграций магазина | **88**, единственный head `0088_filter_and_regions` |
| Миграций Support Pro | **8** |

### Распределение маршрутов

| Префикс | Маршрутов | Назначение |
| --- | --- | --- |
| `/api/admin/…` | 458 | админ-панель |
| `/api/me/…` | 134 | личный кабинет и приложения |
| `/api/auth/…` | 24 | вход, OAuth, passkeys, сессии |
| `/api/public/…` | 21 | публичные данные (брендинг, статус, документы) |
| `/api/webhooks/…` | 18 | уведомления платёжных касс и Remnawave |
| `/api/internal/…` | 17 | межсервисные вызовы (Support Pro, staging) |
| `/api/payments/…` | 6 | создание платежа и возвраты |
| `/api/agent/…` | 6 | агент узла (метрики, DPI, доступ) |
| `/api/reseller/…` | 5 | реселлеры |
| `/api/plugin/…` | 5 | плагины |
| `/api/mobile/…` | 4 | мобильные каталоги и панели |

Крупнейшие домены админки: `backups` (14), `plugins` (14), `customer-operations` (13),
`remnawave` (13), `auth` (13), `v6` (11), `enterprise` (10), `referrals` (9), `sub-proxy` (9),
`panel` (9).

## 5. Frontend

| Приложение | Файлов | Стек | Состояние |
| --- | --- | --- | --- |
| `admin` | 120 (60 `.tsx`) | Next.js 16.4.2, React 19.3.1, TS 7.0.2, Tailwind 4.3.3 | собирается, typecheck чист |
| `cabinet` | 110 (52 `.tsx`) | Next.js 16.4.2, React 19.3.1 | собирается, 55 vitest-тестов |
| `miniapp` | 6 | nginx + статика из `cabinet` | отдаётся через Caddy |
| `desktop` | 4 | README-заготовки | не реализовано |
| `browser-extension` | 2 | заготовка | не реализовано |

## 6. Мобильные приложения

| Приложение | Файлов | Стек |
| --- | --- | --- |
| `mobile/android-user` | — | Kotlin + Compose, встроенный Xray-core |
| `mobile/android-admin` | — | Kotlin + Compose |
| `mobile/ios-user` | 10 `.swift` | Swift + SwiftUI |
| `mobile/ios-admin` | — | Swift + SwiftUI |

Всего 24 файла Kotlin и 10 Swift. Версия приложений 3.4.0. Сборка проверяется в CI
(`Android • PKCE build`, `iOS • PKCE build`, UI-тесты на эмуляторе и симуляторе).

## 7. Инфраструктура

### Docker Compose — 17 сервисов

| Сервис | Образ | Профиль | Healthcheck |
| --- | --- | --- | --- |
| `volume_init` | redis 7.4 | — | нет |
| `redis` | redis 7.4 | — | да |
| `db` | postgres 18.6 | — | да |
| `backend` | build | — | да |
| `backend_standby` | build | `standby` | нет |
| `worker` | build | — | нет |
| `mail_receiver` | build | `mail` | нет |
| `bot` | build | — | нет |
| `admin` | build | — | да |
| `miniapp` | build | — | да |
| `cabinet` | build | — | да |
| `support_db` | postgres 18.6 | — | да |
| `support_redis` | redis 7 | — | да |
| `support_migrate` | build | — | нет |
| `support_pro` | build | — | да |
| `support_worker` | build | — | нет |
| `caddy` | build | — | да |

Все образы закреплены по digest (`@sha256:`), кроме собственных сборок.

### GitHub Actions — 15 workflows

`ci.yml`, `docker.yml`, `publish-release.yml`, `deploy.yml`, `docs-links.yml`,
`claude-roadmap.yml`, `dependabot-automerge.yml`, `build-mobile.yml`, `mobile-release.yml`,
`mobile-screenshots.yml`, `remnawave-live.yml`, `load-security.yml`, `load-live.yml`,
`hetzner-live.yml`, `payments-acceptance.yml`.

### Скрипты эксплуатации — 27

Установка (`install.sh`, `deploy/install-vps.sh`, `deploy/install-docker.sh`), обновление
(`update.sh`, `update-from-github.sh`, `auto-update.sh`), откат (`rollback.sh`), резервные копии
(`backup.sh`), диагностика (`doctor.sh`, `preflight.sh`, `security-scan.sh`), секреты
(`rotate-secrets.sh`), мобильные сборки (3 скрипта), staging/интеграция (4 скрипта),
hot-standby, zero-downtime, миграция PostgreSQL.

## 8. Тесты

| Уровень | Количество | Команда |
| --- | --- | --- |
| Backend pytest | **216 файлов**, 1825 тестов проходит | `pytest -q tests --timeout=180` |
| Кабинет vitest | 16 файлов, 55 тестов | `npm test` в `cabinet` |
| E2E Playwright | 8+ спецификаций в `admin/e2e` | `npx playwright test` |
| Мобильные UI | Android эмулятор, iOS симулятор | workflows `ci.yml` |
| Контракты документации | 5 скриптов | `scripts/check-*.py` |

## 9. Документация

| Группа | Файлов |
| --- | --- |
| `docs/ru` | 165 |
| `docs/en` | 25 |
| `docs/uk` | 25 |
| `docs/modules` | 30+ описаний модулей |
| `docs/wiki` | 27 (9 страниц × 3 языка) |
| `docs/archive` | 209 исторических снимков |

Корневые указатели: `README.md` (1361 строка), `DOCUMENTATION.md`, `docs/INDEX.md`,
`FUNCTIONS.md`, `PROJECT_SPEC.md`, `PROJECT_STRUCTURE.md`.

## 10. Что в проекте отсутствует

Зафиксировано по факту, а не по обещаниям в документации:

* **Десктопные приложения** — `desktop/{linux,macos,windows}` содержат только README.
* **Расширение браузера** — `browser-extension` содержит 2 файла заготовки.
* **Terraform** — один файл, инфраструктура не описана.
* **`corgi-cli`** — только README, кода нет.

Эти пункты перечислены в `docs/current-guides.json` как существующие файлы (README есть),
но функциональности за ними нет. Упоминать их как готовые нельзя.

## 11. Связанные документы

* [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) — как компоненты связаны между собой
* [TECH_STACK.md](TECH_STACK.md) — версии зависимостей и что НЕ используется
* [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md) — внешние репозитории первого этапа
* [REFERENCE_REPOSITORIES.md](REFERENCE_REPOSITORIES.md) — пять проектов, склонированных и разобранных
* [CODE_REUSE_REGISTER.md](CODE_REUSE_REGISTER.md) — что берём из них, а что пишем сами
* [PROJECT_FILE_MAP.md](PROJECT_FILE_MAP.md) — полный список файлов
