# Инвентаризация проекта — VPN Shop by Corgi Lucy

Актуальные пути приложений, сервисов и хранилищ приведены в [архитектуре проекта](PROJECT_ARCHITECTURE.md).
Версии внешних компонентов, лицензии и контрольные суммы образов собраны в [реестре зависимостей](EXTERNAL_DEPENDENCIES.md).

## Мобильные пакеты от 26 ноября 2026 года

Пакеты собраны из коммита `925e6180d183670c007ea807f6808740a636a81a` ветки `main`.
Для APK сверены манифест, подпись и SHA-256. Для iOS проверены SHA-256, платформа и `Info.plist`
внутри обоих IPA и обоих пакетов симулятора. [Запуск Mobile packages №45759099802](https://github.com/booarkz-cpu/shop-by-boo/actions/runs/45759099802)

| Приложение | Исходники | Идентификатор пакета | Версия | Номер сборки | ОС в манифесте |
| --- | --- | --- | --- | ---: | --- |
| VPN Shop для Android | `apps/vpn-shop/android` | `shop.remnawave.user` | 3.9.0 | 3900 | API 26 и выше, целевой API 36 |
| Корги Люси — Клиент для Android | `apps/vpn-client/android` | `shop.corgi.client` | 1.10.1 | 1101 | API 26 и выше, целевой API 36 |
| Lucy Admin для Android | `apps/lucy-admin/android` | `shop.remnawave.admin` | 3.9.0 | 3900 | API 26 и выше, целевой API 36 |
| VPN Shop для iOS | `apps/vpn-shop/ios` | `shop.remnawave.user` | 3.9.0 | 3900 | iOS 16.0 и выше |
| Lucy Admin для iOS | `apps/lucy-admin/ios` | `shop.remnawave.admin` | 3.9.0 | 3900 | iOS 16.0 и выше |

В APK магазина и самостоятельного клиента проверены восемь экземпляров `libgojni.so`.
Для каждой архитектуры (arm64-v8a, armeabi-v7a, x86 и x86_64) хеш библиотеки совпал в обоих APK.
SHA-256 скачанного архива из задания Android — `1077e84e8a4bddcf2b713600918ee86dd624d7f892ae56379bbda00f06e3831c`.
[Артефакт mobile-android](https://github.com/booarkz-cpu/shop-by-boo/actions/runs/45759099802/artifacts/15089111778)

Задание iOS записало статус `blocked_missing_apple_identity`. В IPA для iPhone и пакетах симулятора собраны
основные приложения. Запуск Packet Tunnel на устройстве требует подписанного приложения с расширением и
профилем Network Extension. Сборку с расширениями проверяет отдельное задание «iOS • tunnel and rich push extensions».
SHA-256 скачанного архива iOS — `0c3612bec7cc47286040832a10119e6f0ca555898d02052db7c65e0a4b812a5f`.
[Артефакт mobile-ios](https://github.com/booarkz-cpu/shop-by-boo/actions/runs/45759099802/artifacts/15088962215) · [CI коммита](https://github.com/booarkz-cpu/shop-by-boo/actions/runs/45759099927)

### Работа туннеля на эмуляторе и симуляторе

| Приложение | Среда | Результат на `925e6180` |
| --- | --- | --- |
| VPN Shop для Android | Android API 34, x86_64 | Эмулятор подключился к Xray, получил контрольную страницу через туннель и отключился. После добавления пользовательского правила страница стала недоступна, после удаления снова открылась. [Журнал задания](https://github.com/booarkz-cpu/shop-by-boo/actions/runs/45759099789/job/139704604980) |
| Corgi Lucy Client для Android | Android API 34, x86_64 | Клиент импортировал подписку, передал запрос через VPN и отключился. Проверены состояние при отсутствии ответа контрольной страницы и режим локального прокси с паролем. [Журнал задания](https://github.com/booarkz-cpu/shop-by-boo/actions/runs/45759099900/job/139704605038) |
| VPN Shop для iOS | iPhone Simulator, Xcode 26.6 | Два цикла запуска и остановки подтвердили TCP и передачу DNS по UDP через внешний файловый дескриптор. Проверена принадлежность дескриптора после остановки. [Журнал задания](https://github.com/booarkz-cpu/shop-by-boo/actions/runs/45759099927/job/139704605765) |

В протоколе сборки iOS указаны libXray `5a0f7d8d1c28b34afb5727b04b26a10f6dbac7e3`
и hev-socks5-tunnel `75dbc1e9ace6c70d3d1b94df7c283efe1de7effc`. Для каждого из двух
XCFramework сохранены контрольные суммы срезов устройства arm64 и симулятора arm64/x86_64.
[Протокол сборки](https://github.com/booarkz-cpu/shop-by-boo/actions/runs/45759099927/artifacts/15089636515)

## Исторический снимок за 1–2 ноября 2026 года

Разделы 1–11 ниже описывают рабочее дерево `e3b9387` периода выпуска `v28.57.0`. Подсчёты основаны на
`git ls-files`, таблице маршрутов приложения, `alembic heads` и `docker-compose.yml`.

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
| `services/backend/` | 331 | API, бот, worker, миграции |
| `tests/` | 228 | pytest-набор |
| `mobile/` | 176 | Android и iOS, user и admin |
| `screenshots/` | 142 | галереи интерфейсов |
| `apps/lucy-admin/web/` | 120 | админ-панель (Next.js) |
| `apps/user-cabinet/` | 110 | личный кабинет и Mini App (Next.js) |
| `services/support-pro/` | 93 | отдельный сервис поддержки |
| `scripts/` | 77 | эксплуатация и релиз |
| `.github/` | 61 | 15 workflows, соглашения |
| `infrastructure/` | 20 | установщик, Caddy, nginx, prometheus, grafana, wireguard, mail-tls, Terraform; `deploy/` — 5 переходников старых путей |
| `apps/telegram-mini-app/` | 6 | nginx-конфигурация Mini App |
| `desktop/` | 4 | README-заготовки для трёх ОС |
| `browser-extension/` | 2 | заготовка расширения |
| `infrastructure/provisioning/` | 1 | заготовка инфраструктуры (Terraform) |

## 4. Backend

| Параметр | Значение |
| --- | --- |
| Python-модулей в `services/backend/app` | **173** |
| Строк в `services/backend/app` | **45 728** |
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
| `apps/vpn-shop/android` | — | Kotlin + Compose, встроенный Xray-core |
| `apps/lucy-admin/android` | — | Kotlin + Compose |
| `apps/vpn-shop/ios` | 10 `.swift` | Swift + SwiftUI |
| `apps/lucy-admin/ios` | — | Swift + SwiftUI |

Всего 24 файла Kotlin и 10 Swift. Версия приложений 3.8.0. Сборка проверяется в CI
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

Установка (`install.sh`, `infrastructure/deployment/install-vps.sh`, `infrastructure/deployment/install-docker.sh`), обновление
(`update.sh`, `update-from-github.sh`, `auto-update.sh`), откат (`rollback.sh`), резервные копии
(`backup.sh`), диагностика (`doctor.sh`, `preflight.sh`, `security-scan.sh`), секреты
(`rotate-secrets.sh`), мобильные сборки (3 скрипта), staging/интеграция (4 скрипта),
hot-standby, zero-downtime, миграция PostgreSQL.

## 8. Тесты

| Уровень | Количество | Команда |
| --- | --- | --- |
| Backend pytest | **220 файлов**, 2534 теста собирается (`pytest --collect-only`, 2026-11-02) | `pytest -q tests --timeout=180` |
| Кабинет vitest | 16 файлов, 55 тестов | `npm test` в `cabinet` |
| E2E Playwright | 8+ спецификаций в `apps/lucy-admin/web/e2e` | `npx playwright test` |
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
