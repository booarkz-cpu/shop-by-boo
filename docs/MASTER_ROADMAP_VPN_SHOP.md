# Мастер-дорожная карта VPN Shop

Дистрибутив `v28.95.0`, runtime/API `21.5.1`, миграция магазина `0094_store_subscriptions`.

Состояние на `2026-10-31`. Отметка «сделано» означает, что есть подтверждение в коде или в
результате проверки; «не проверено» — что функциональность существует, но живой прогон не выполнен.

## 1. Где проект находится

Магазин зрелый: 173 модуля backend, 275 Python-файлов, 88 миграций, 219 тестовых файлов,
три фронтенда (admin, cabinet, miniapp), мобильные приложения для Android и iOS, 13 workflow.
Архитектурно задача «собрать всё в одну панель» уже решена в предыдущих версиях — переписывать
с нуля не требуется.

Текущее состояние по блокам задания:

| Блок | Состояние |
| --- | --- |
| Единая админ-панель | Реализована, 30+ разделов, сборка проходит |
| Личный кабинет | Реализован (`cabinet`), сборка и тесты проходят |
| Remnawave | Реализовано, живой прогон не проверен |
| Reverse proxy | Конфигурации есть, живой прогон не проверен |
| Telegram-бот и Mini App | Реализованы, живой прогон не проверен |
| Платежи | 15 провайдеров, логика покрыта тестами, живые платежи не проверены |
| Ночное автообновление | Реализовано полностью, ночной прогон не проверен |
| Docker и установщик | Реализованы, запуск не проверен (нет Docker) |
| Мобильные приложения | Исходники есть, сборка не проверена, артефакты неподписаны |
| Документация | 455 md-файлов, 12 добавлено этим релизом |

## 2. Приоритеты

### P0 — блокирует production

| Задача | Статус | Что нужно |
| --- | --- | --- |
| Проверить восстановление из резервной копии | Не проверено | Сервер; пройти §11 [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) |
| Живой платёж хотя бы у одного провайдера | Не проверено | Ключи провайдера |
| Проверить, что подписка не выдаётся без подтверждённого платежа | Логика покрыта тестами | Живой прогон с провайдером |
| Проверить миграции на копии боевой БД | Не проверено | Копия БД |
| Убедиться в отсутствии секретов в репозитории | Проверено: `git grep` чист | — |

### P1 — основная функциональность

| Задача | Статус | Что нужно |
| --- | --- | --- |
| Remnawave: выдача, продление, отключение, устройства | Логика покрыта | `REMNAWAVE_URL`, `REMNAWAVE_TOKEN` |
| Reverse proxy: TLS, upstream, health | Конфиги есть | Сервер с доменом |
| Telegram: `/start`, меню, покупка, поддержка | Логика покрыта | `BOT_TOKEN` |
| Юридические документы: оферта, политика конфиденциальности, правила пользования сервисом по законодательству РФ | Проекты готовы в v28.73.0 ([описание](ru/new/LEGAL_DOCUMENTS.md)); страницы выключены до проверки | Реквизиты продавца от владельца; проверка юристом перед публикацией |
| Mini App: проверка `initData` | Логика покрыта | `BOT_TOKEN` |
| Docker: сборка и запуск 17 сервисов | Не проверено | Docker |
| Установщик на чистом VPS | Не проверено | VPS |
| Ночное автообновление по расписанию | Реализовано | VPS с systemd |
| Откат при реальном сбое | Реализовано | Управляемый сбой |

### P2 — качество продукта

| Задача | Статус |
| --- | --- |
| Единый design system (тёмная тема, Inter, JetBrains Mono) | Реализовано: `admin/src/style.css` содержит `--accent`, `--surface`, Inter, `html[data-theme="light"]` |
| Адаптивная навигация и мобильная вёрстка админки | Реализовано, скриншоты в `screenshots/admin_panel` |
| Skeleton-загрузка, пустые состояния, ошибки | Реализовано в компонентах UI |
| Локализация кабинета | `ru` и `en` |
| Локализация мобильных приложений | `mobile/l10n/{admin,user}.json` |
| Обновление скриншотов под текущий UI | Частично: наборы от `v28.10.0`, `screenshots/*` актуальнее |
| Версия в разделе «Обновления» | Исправлено в этом релизе |

### P3 — улучшения

| Задача | Статус |
| --- | --- |
| Автоматический анализ опасности миграций | Отсутствует, решение принимает человек |
| Проверка CVE в цикле автообновления | Отсутствует, Dependabot отдельно |
| Wiki на трёх языках | Требует прав Wiki; эквивалент — `docs/{ru,en,uk}` |
| Расширение `corgi-cli` и `browser-extension` | Минимальные заготовки |

## 3. Тарифы

Названия тарифов в коде не зашиты — они создаются в админке и хранятся в БД (`Plan`). Поэтому
консистентность «Lucy Mini / Max / Ultra», количество устройств и безлимит трафика проверяются
**в работающей установке**, а не в репозитории.

Зафиксированные в задании характеристики (3 дня / 1 устройство для теста; 2 устройства Max;
4 устройства Ultra) должны быть выставлены в админке → «Тарифы». Проверить, что:

- `Plan.enabled` корректен для каждого тарифа;
- ограничение устройств соответствует заявленному;
- безлимит трафика включён только если Remnawave это поддерживает;
- выделение «Ultra» как выгодного подтверждается реальными ценами.

Цены и скидки в репозитории не заданы — их не следует придумывать. Статус: требует работающей
установки.

## 4. Брендинг

Название продукта «Корги Люси» присутствует в коде: `app_name` по умолчанию `Корги Люси`,
`support_ai.SYSTEM`, `push_style.brand`, `wg_pool.name_prefix`, `status_page`. Лозунг
«Свободный интернет без лишнего Гав!» задаётся через контент админки (`app_config`).

## 5. Реестр функций по фактическому коду

Состояние на `2026-11-01`, коммит `e3b9387`. Статусы:
`IMPLEMENTED` — код есть и покрыт тестами; `PARTIAL` — работает не всё из заявленного;
`NOT_VERIFIED` — код есть, живой прогон не выполнен (нет секретов или доступа); `MISSING` — кода нет;
`BLOCKED` — требует внешнего ресурса, который недоступен.

| Компонент | Функция | Состояние | Файлы | Зависимости |
| --- | --- | --- | --- | --- |
| Backend | REST API, 836 маршрутов на 718 путях | IMPLEMENTED | `backend/app/main.py`, 173 модуля | PostgreSQL, Redis |
| Backend | health `/health`, `/health/live`, `/health/ready` | IMPLEMENTED | `main.py` | PostgreSQL, Redis |
| Backend | RBAC на каждом админ-маршруте | IMPLEMENTED | `security.py`, `require_permission` | — |
| Backend | идемпотентность платежей и webhook | IMPLEMENTED | `payments_api.py` (`register_provider_event`) | PostgreSQL |
| Backend | 88 миграций, единственный head | IMPLEMENTED | `backend/alembic/versions` | PostgreSQL |
| Backend | фоновые задачи и планировщики | IMPLEMENTED | `schedulers.py`, `worker.py` | Redis |
| Backend | интеграция Remnawave (доступ, срок, трафик) | NOT_VERIFIED | `remnawave*`, `panel_usage.py` | `REMNAWAVE_URL`, `REMNAWAVE_TOKEN` |
| Backend | 17 платёжных касс и Telegram Stars | PARTIAL | `payments.py`, `payments_api.py`, `gateways/` | ключи касс |
| Backend | 22 webhook-пути (кассы + Remnawave) | IMPLEMENTED | `payments_api.py` | подписи провайдеров |
| Backend | OAuth: VK, Яндекс, Google, email | NOT_VERIFIED | `auth_api.py` | client id/secret |
| Backend | passkeys (WebAuthn) | IMPLEMENTED | `passkeys`, `webauthn==3.0.1` | — |
| Backend | резервные копии и проверка целостности | IMPLEMENTED | `backup_verify.py`, `scripts/backup.sh` | S3 (опц.) |
| Backend | ночное автообновление | IMPLEMENTED | `auto_update_api.py`, `scripts/auto_update.py` | systemd, root |
| Backend | терминал узлов по SSH | NOT_VERIFIED | `node_terminal.py` | `paramiko`, доступ к узлам |
| Backend | почтовый домен и приём почты | NOT_VERIFIED | `mail_domain.py`, профиль `mail` | домен, DNS |
| Backend | push FCM/APNs | NOT_VERIFIED | `push.py` | ключи FCM/APNs |
| Backend | география, доступность, репутация | PARTIAL | `geoip.py`, `ripe_atlas.py`, `network_intel` | MaxMind, RIPE, AbuseIPDB |
| Backend | анти-абьюз и анти-шеринг | IMPLEMENTED | `abuse_suspension.py`, `anti_sharing.py` | — |
| Бот | `/start`, меню, покупка, поддержка | NOT_VERIFIED | `bot.py` (860 строк) | `BOT_TOKEN` |
| Бот | меню и баннеры из админки | IMPLEMENTED | `bot_banners.py`, `menu-tree.tsx` | — |
| Mini App | серверная проверка `initData` | IMPLEMENTED | `auth_api.telegram_user_from_init_data` | `BOT_TOKEN` |
| Кабинет | подписки, устройства, платежи, поддержка | IMPLEMENTED | `cabinet/` 52 компонента | API |
| Кабинет | 55 vitest-тестов | IMPLEMENTED | `cabinet/src/*.test.tsx` | — |
| Админ-панель | 458 маршрутов, 60 компонентов | IMPLEMENTED | `admin/src` | API |
| Админ-панель | экран ошибки вместо чёрной страницы | IMPLEMENTED | `admin/src/app/error.tsx` | — |
| Админ-панель | центр автоматизации | IMPLEMENTED | `automation.py`, `automation.tsx` | — |
| Админ-панель | раздел «Обновления» | IMPLEMENTED | `autoUpdate.tsx` | update agent |
| Мобильные | Android user с встроенным Xray | PARTIAL | `mobile/android-user` | SDK, сборка |
| Мобильные | iOS user и admin | PARTIAL | `mobile/ios-user`, `mobile/ios-admin` | Xcode |
| Мобильные | Android admin | PARTIAL | `mobile/android-admin` | SDK |
| Инфраструктура | 17 сервисов Compose, образы по digest | IMPLEMENTED | `docker-compose.yml` | Docker |
| Инфраструктура | Caddy: TLS, HTTP/3, маршруты | IMPLEMENTED | `deploy/Caddyfile` | домены |
| Инфраструктура | установщик | NOT_VERIFIED | `install.sh`, `deploy/install-vps.sh` | чистый VPS |
| Инфраструктура | откат и горячий резерв | IMPLEMENTED | `rollback.sh`, `hot-standby.sh` | снимок |
| CI/CD | 15 workflows, gate публикации | IMPLEMENTED | `.github/workflows` | GitHub |
| CI/CD | публикация релиза | IMPLEMENTED | `publish-release.yml` | зелёные CI и Docker |
| CI/CD | ночная проверка внешних ссылок | IMPLEMENTED | `docs-links.yml`, `check-external-links.py` | сеть |
| Документация | 3 языка, 383 живых файла | IMPLEMENTED | `docs/{ru,en,uk}`, `docs/wiki` | — |
| Документация | контракты версии, карты, ссылок | IMPLEMENTED | `scripts/check-*.py` | — |
| Десктоп | приложения Linux/macOS/Windows | MISSING | `desktop/*` — только README | — |
| Расширение браузера | — | MISSING | `browser-extension` — 2 файла | — |
| Terraform | инфраструктура как код | MISSING | `terraform/` — 1 файл | — |
| `corgi-cli` | CLI | MISSING | `corgi-cli/README.md` | — |

Итог по таблице: **27 `IMPLEMENTED`**, 5 `PARTIAL`, 7 `NOT_VERIFIED`, 4 `MISSING` — всего 43 функции.
Ни одна `NOT_VERIFIED` не выдаётся за проверенную: для каждой указано, чего не хватает.
`BLOCKED` не присвоен ни одной строке намеренно: у каждой заблокированной функции есть код,
поэтому честнее `NOT_VERIFIED` с названным условием снятия, а не `BLOCKED`, за которым легко
скрыть неработающую реализацию.

## 6. Что дало сравнение с пятью референсными проектами

Все пять склонированы и разобраны 2026-11-01. Подробно — в
[REFERENCE_REPOSITORIES.md](REFERENCE_REPOSITORIES.md), решения по каждой функции — в
[CODE_REUSE_REGISTER.md](CODE_REUSE_REGISTER.md).

### Перенос кода

**Ни одной строки.** Лицензии четырёх из пяти проектов запрещают перенос в коммерческий продукт:

| Репозиторий | Лицензия | Перенос |
| --- | --- | --- |
| `Case211/remnawave-admin` | AGPL-3.0 + plugin exception | запрещён (проект к тому же стал платным, в репо замороженная 5.2.0) |
| `eGamesAPI/remnawave-reverse-proxy` | MIT | разрешён, но не нужен — свой Caddy; автор прямо запрещает production |
| `BEDOLAGA-DEV/remnawave-bedolaga-telegram-bot` | **Commons Clause** поверх MIT | запрещён: нельзя продавать производное |
| `BEDOLAGA-DEV/bedolaga-cabinet` | AGPL-3.0 | запрещён |
| `Mrvibecodic/remnawave-subscription-middleware` | **лицензии нет** | запрещён: полное авторское право |

### Что уже есть у нас (дублировать не нужно)

33 функции из референсов реализованы самостоятельно, в том числе все ключевые функции прослойки подписки:
зеркало подписки на своём домене, грейс-доступ, блок устройства по HWID, переписывание заголовков по
приложению, склейка двух подписок, журнал запросов, доп. конфиги WireGuard. Плюс Apple IAP и Google Play
Billing через `payment_platform.py`.

### Чего у нас нет

| Что | Решение |
| --- | --- |
| 8 касс (Cispay, Etoplatezhi, Jupiter, RioPay, SeverPay, TabPay, OverPay, Kassa AI) | писать самим при появлении спроса; запуск не блокируют — у нас 17 внешних касс и Telegram Stars |
| Колесо фортуны, донат-виджет | не планируется: геймификация не входит в бренд-задачу |
| Реактивация ушедших | не планируется: закрыто через `churn.py`, `feedback`, `loyalty.py` |
| Учёт расхода API-ключей плагинов | бэклог |
| Интеграция с fail2ban | бэклог |
| Единая политика хранения (retention) | бэклог: сейчас сроки заданы точечно |

Эти пять пунктов бэклога — **направления для собственной реализации**, а не перенос: их код под
запрещающими лицензиями.

## 7. Точка начала следующего этапа

**Ход мастер-задания из 18 этапов** — в [docs/ru/new/IMPLEMENTATION_STATUS.md](ru/new/IMPLEMENTATION_STATUS.md). На 2026-11-05 выполнены все 18 этапов: инвентаризация, сравнение с референсами, технический аудит, исправления в v28.58.0 ([журнал исправлений](ru/new/BUGFIX_LOG.md)), единая бизнес-логика в v28.59.0 ([устройство backend](ru/new/BACKEND_ARCHITECTURE.md)), Админ-центр в v28.60.0 ([управляемость из админки](ru/new/ADMIN_CONTROL_MATRIX.md)), интерфейс в v28.61.0 ([правила интерфейса](ru/new/UI_UX_GUIDE.md)), System Control Center с руководством по панели в v28.62.0 ([руководство](ru/new/ADMIN_PANEL_GUIDE.md), [роли и права](ru/new/RBAC.md)), личный кабинет в v28.63.0 ([руководство по кабинету](ru/new/USER_CABINET_GUIDE.md)), обновление языков, баз и компонентов в v28.64.0 ([стек](TECH_STACK.md)) архитектура Remnawave Manager в v28.65.0 ([архитектура](ru/new/REMNAWAVE_ARCHITECTURE.md)) мастер установки Remnawave в v28.66.0 ([мастер установки](ru/new/REMNAWAVE_INSTALLATION_WIZARD.md); проверка на настоящем VPS — BLOCKED_EXTERNAL) и портал подписки с менеджером доменов в v28.67.0 ([портал](ru/new/SUBSCRIPTION_PORTAL.md); настоящий домен — BLOCKED_EXTERNAL), все тексты и цвета портала из админки — в v28.68.0; этап 12 — менеджер расширений через API панели в v28.69.0 и модули серверов (SelfSteal, IPv6, ядро Xray, WARP, NetBird, Xray Checker, серверный роутинг) в v28.72.1; этап 13 — Telegram-бот из админки и тексты бота на трёх языках в v28.71.0–v28.72.0; этап 14 — проверка касс по коду, контрактный тест всех касс, журнал уведомлений и проекты юридических документов в v28.73.0 ([платежи](ru/new/PAYMENT_INTEGRATION.md); живые платежи — BLOCKED_SECRETS); этап 15 — автообновление Remnawave из админки, зашифрованная копия базы панели в магазине и Automation Center в v28.74.0 ([автообновление](ru/new/AUTO_UPDATE.md), [Automation Center](ru/new/AUTOMATION_CENTER.md); обновление на настоящем VPS — BLOCKED_EXTERNAL); этап 16 — подтверждение опасных действий, смена SSH-ключей, история безопасности, журналы контейнеров и метрики безопасности в v28.75.0 ([аудит](ru/new/SECURITY_AUDIT.md), [секреты](ru/new/SECRETS_MANAGEMENT.md)); этап 17 — iOS-приложения на Swift 6, пересъёмка всех скриншотов с проверкой в CI, вёрстка админки, руководства по установке Remnawave, доменам и API приложений в v28.76.0 ([iOS](ru/new/IOS_ARCHITECTURE.md), [установка Remnawave](ru/new/REMNAWAVE_INSTALLATION_GUIDE.md)). Этап 18 — полное тестирование и выпуск ([итоговая приёмка](ru/new/FINAL_ACCEPTANCE.md); живые проверки на VPS, доменах, кассах, push и iOS ждут доступов владельца): часть 1 — v28.77.0 (подпись Android, ссылки на APK, адрес магазина в приложениях, управление Remnawave, тест встроенного VPN, основной сценарий на живой панели — [выпуск](ru/RELEASE_V28_77_0.md)); часть 2 — v28.78.0 (вся админка под тестами, 30/30 модулей PASS; вход в панель Remnawave через магазин и через TinyAuth — [выпуск](ru/RELEASE_V28_78_0.md)); часть 3 — v28.79.0 (третье Android-приложение «Корги Люси: клиент» — [выпуск](ru/RELEASE_V28_79_0.md)).

Исследование завершено, документы созданы. Дальше — по порядку:

1. **Секреты.** Выдать по [TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md](TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md):
   `REMNAWAVE_URL` + `REMNAWAVE_TOKEN`, `BOT_TOKEN`, ключи одной кассы. Это снимает 8 из 9
   `NOT_VERIFIED`.
2. **Remnawave.** Полный цикл: создание пользователя, выдача, продление, отключение, лимит устройств,
   чтение трафика. Это первый `NOT_VERIFIED`, потому что без него магазин не выдаёт доступ.
3. **Платежи.** Один провайдер от создания заказа до выдачи подписки на реальные деньги.
4. **Бот и Mini App.** `/start`, меню, покупка, `initData` на боевом домене.
5. **Docker и установщик** на чистом VPS, затем матрица [AUTO_UPDATE_TESTING.md](AUTO_UPDATE_TESTING.md).

Блокировки и условие снятия каждой — в [MASTER_EXECUTION_BLOCKERS.md](MASTER_EXECUTION_BLOCKERS.md).

## 8. Порядок дальнейших работ

1. Выдать секреты по [TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md](TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md).
2. Пройти P0 на тестовом сервере.
3. Пройти P1: Remnawave → платежи → бот → Docker → установщик.
4. Пройти матрицу [AUTO_UPDATE_TESTING.md](AUTO_UPDATE_TESTING.md).
5. Только после этого публиковать стабильный тег как проверенный в бою.

Не публикуйте релиз как «полностью проверенный», пока пункты P0 не закрыты.
