# Референсные репозитории

Пять проектов склонированы и изучены 2026-11-01 в `/tmp/vpn-shop-references` (вне основного репозитория,
оригиналы не изменялись). Для каждого зафиксированы фактические данные из клона: число файлов, ветка,
последний коммит, лицензия, стек, структура. Ничего не описано по памяти.

## Сводка

| № | Репозиторий | Файлов | Стек | Лицензия | Последний коммит |
| --- | --- | --- | --- | --- | --- |
| 1 | `Case211/remnawave-admin` | 1397 | Python + FastAPI + React/TS | **AGPL-3.0** + plugin exception | `72bf224` 2026-10-26 |
| 2 | `eGamesAPI/remnawave-reverse-proxy` | 252 | Shell + nginx/Caddy + Astro-доки | **MIT** | `93e6631` 2026-10-16 |
| 3 | `BEDOLAGA-DEV/remnawave-bedolaga-telegram-bot` | 2008 | Python 3.14 + aiogram + FastAPI | **Commons Clause** (база MIT) | `1a2d310` 2026-10-28 |
| 4 | `BEDOLAGA-DEV/bedolaga-cabinet` | 1104 | React 19 + Vite + TypeScript | **AGPL-3.0** | `c9d3e41` 2026-10-28 |
| 5 | `Mrvibecodic/remnawave-subscription-middleware` | 146 | PHP 8.1 без фреймворков | **ЛИЦЕНЗИИ НЕТ** | `9a8072e` 2026-10-28 |

Все пять доступны и склонированы успешно. Ни один не пришлось брать из архива или API вместо git.

## 1. Case211/remnawave-admin

**Назначение.** Панель управления и Telegram-бот поверх панели Remnawave: пользователи, ноды, анти-абьюз,
почта, мониторинг.

**Важно для решения о переносе:** в README прямо сказано, что проект **стал платным**. В репозитории
осталась последняя бесплатная версия **5.2.0**, она не обновляется; актуальная развивается отдельно по
подписке на nexuslink.ru. То есть даже при совместимой лицензии это замороженная кодовая база.

**Лицензия.** AGPL-3.0 с дополнительным исключением по §7 (plugin exception): плагины, взаимодействующие
только через документированный интерфейс, не считаются производными работами и могут распространяться на
своих условиях. Модификации самого проекта остаются под AGPL-3.0.

Для нашего проекта это означает: **перенос кода невозможен** без перевода всего магазина на AGPL, что
несовместимо с лицензией Corgi Lusi Source 2.8.

**Стек и структура.** Backend: FastAPI 0.115, SQLAlchemy 2.0.36, asyncpg, alembic, aiogram 3.12,
webauthn, pyotp. Frontend: React + TypeScript (194 `.tsx`, 112 `.ts`). 709 `.py`, 79 `.md`, 11 workflows,
**267 тестовых файлов**. Compose: `bot`, `remnawave-admin-db`, `web-backend`, `web-collector`,
`web-frontend`, `prometheus`, `redis`.

**Архитектурно интересное** (`web/backend/core/`, 60+ модулей): `hwid_guard`, `ip_guard`, `login_guard`,
`attack_detector`, `torrent_p2p_whitelist`, `traffic_rate_monitor`, `throttle_sync`, `shaper_rollout`,
`ndpi_rollout`, `plugin_installer`, `webhook_security`, `api_key_auth`, `token_blacklist`, `fail2ban_logger`,
`reputation`, `sessions`, `violation_notifier`, `online_snapshot_recorder`.

**Что пригодилось как идея, а не как код.** Разделение «guard» на отдельные модули по типу угрозы
(hwid / ip / login / rate) — у нас эти проверки есть, но сосредоточены в `anti_sharing.py`, `abuse.py`,
`security.py`. Идея полезна для будущего рефакторинга, перенос кода — нет.

## 2. eGamesAPI/remnawave-reverse-proxy

**Назначение.** Скрипт установки reverse proxy (nginx или Caddy) для панели Remnawave: сертификаты,
защита панели секретной cookie или TinyAuth, узлы, WARP, NetBird.

**Лицензия.** MIT (Copyright (c) 2025 eGames). Перенос разрешён при сохранении уведомления об авторстве.

**Критично:** в README стоит предупреждение автора дважды — «THIS REPOSITORY IS AN EDUCATIONAL EXAMPLE …
NOT FOR PRODUCTION AND NOT FOR PRODUCTION USE! … USE AT YOUR OWN RISK!». То есть автор сам не
позиционирует проект как production-решение.

**Стек и структура.** Shell-модули `src/modules/` (24 файла): `warp.sh`, `tinyauth.sh`,
`subscription_rules.sh`, `server_routing.sh`, `node_plugins.sh`, `client_balancer.sh`, `certificates.sh`,
`add_node.sh`, `ipv6.sh`, `dns_records.sh`, `netbird.sh`. Отдельные ветки установки для nginx и Caddy.
Документация — Astro (65 `.mdx`, 67 `.png`). 1 workflow, тестов нет.

**Отношение к нашему проекту.** Магазин **не использует** его: собственный reverse proxy — Caddy
(`deploy/Caddyfile`, сервис `caddy` в compose), который сам выпускает TLS и маршрутизирует домены.
Замена Caddy на nginx потребовала бы заново решать автоматический TLS, HTTP/3 и маршрутизацию.

**Что пригодилось.** `subscription_rules.sh` и `client_balancer.sh` — идеи правил для подписки; у нас это
`sub_proxy.py` с правилами по User-Agent.

## 3. BEDOLAGA-DEV/remnawave-bedolaga-telegram-bot

**Назначение.** Полнофункциональная платформа продажи VPN-подписок через Telegram поверх Remnawave.

**Лицензия.** «Commons Clause» License Condition v1.0 поверх **MIT** (Licensor: Fr1ngg). Commons Clause
**отзывает право продавать** софт: нельзя предоставлять третьим лицам за плату продукт или услугу, ценность
которой целиком или в существенной части происходит от функциональности софта. Наш магазин — коммерческий
продукт, поэтому **перенос кода запрещён**.

**Стек.** Python 3.14, aiogram 3.31, SQLAlchemy 2.1.6, alembic 1.20.1, asyncpg, FastAPI 0.141, redis 8.1,
yookassa 3.12, cryptography 50, pyjwt 2.15. 1764 `.py`, **783 тестовых файла**, 10 workflows.

**Структура.** `app/handlers/` (19 групп: start, menu, subscription, balance, referral, promocode, polls,
contests, tickets, support, gift_activation, stars_payments, webhooks, admin), `app/services/` (~180
сервисов), `app/cabinet/`, `app/webapi/`, `app/webserver/`, `app/middlewares/`, `app/localization/`.

**Кассы в `app/services/`:** yookassa, freekassa, cloudpayments, platega, rollypay, lava, mulenpay, pal24,
wata, antilopay, aurapay, anore, cashera, paritypay, tribute, cryptobot + **cispay, etoplatezhi, jupiter,
riopay, severpay, tabpay, overpay, kassa_ai** (8 касс, которых у нас нет) + apple_iap (с
`apple_iap_reconciliation_service`) и Google Play.

**Прочие сервисы, заслуживающие внимания:** `disposable_email_service`, `grace_access_*` (5 модулей),
`contest_rotation_service`, `wheel_service`, `donut_service`, `coupon_service`, `pricing_engine`,
`tariff_custom_days`, `tariff_custom_traffic`, `user_revival_service`, `paid_traffic_reset_service`,
`legal_consent_service`, `mail_*`, `nalogo_*` (фискализация), `s2s_postback_service`,
`system_error_log_service`, `log_rotation_service`, `notification_delivery_service`.

## 4. BEDOLAGA-DEV/bedolaga-cabinet

**Назначение.** Веб-кабинет для бота из п.3: личный кабинет, OAuth, лендинги, аналитика продаж, RBAC,
подарочные подписки.

**Лицензия.** **AGPL-3.0** (Version 1, 14 January 2025), Copyright BEDOLAGA DEV. Есть `NOTICE` со
сторонними материалами (карта регионов России, CC0). AGPL требует открыть исходники производной работы при
сетевом доступе — **перенос запрещён**.

**Стек.** React 19.2.8, Vite 8.3.5, TypeScript 5.2.2, Biome, husky. 598 `.tsx`, 450 `.ts`, 281 тестовый
файл, 7 workflows. Версия 1.81.1.

**Структура.** `src/pages/` (180+ страниц, включая 40+ админских: `AdminGraceAccess`, `AdminDpiChecker`,
`AdminBanSystem`, `AdminCampaigns`, `AdminCoupons`, `AdminAuditLog`, `AdminBulkActions`,
`AdminChannelSubscriptions`, `AdminEmailTemplates`, `AdminApplicationReview`), `src/api/`,
`src/locales/` (en, ru, fa, zh — четыре языка).

**Отличие по архитектуре.** У кабинета **нет своего backend**: он статический, а `/api/*` проксируется на
backend бота. У нас кабинет — самостоятельное Next.js-приложение со своим API.

**Языки.** У них 4 (en, ru, fa, zh); у нас 3 (ru, en, uk) — по заданию.

## 5. Mrvibecodic/remnawave-subscription-middleware

**Назначение.** Прослойка для подписок Remnawave: встаёт перед панелью и на лету правит выдачу подписки —
заголовки под приложения, заглушки для заблокированных устройств, «грейс-сквот» при истечении. Основной
сценарий — **зеркало для России**: клиент ходит на РФ-домен, прослойка проксирует на origin-домен панели.
В комплекте веб-админка поверх API панели и пересылка вебхуков на несколько адресов.

**Лицензия — главная находка этапа: файла лицензии НЕТ.** Проверены `LICENSE`, `COPYING`, `NOTICE` в корне
и на глубине двух уровней — ничего. В README и INSTALL.md упоминания лицензии и копирайта отсутствуют.
По умолчанию действует полное авторское право: **перенос кода запрещён**. При этом в `admin/assets/` есть
отдельные файлы лицензий для сторонних ассетов (`LICENSE-qrcode.txt`, `LICENSE-twemoji-country-flags.txt`,
`LICENSE.txt` для шрифта) — то есть автор лицензирует ассеты, но не свой код.

**Стек.** PHP 8.1+ без фреймворков и сторонних зависимостей, SQLite по умолчанию (MySQL/MariaDB по выбору),
96 `.php`, nginx + PHP-FPM в Docker (`ghcr.io/mrvibecodic/remnawave-subscription-middleware`), 2 workflow,
**тестов нет**. Статус — beta, в README предупреждение делать бэкап панели.

**Структура.** `lib/` — 24 модуля: `grace.php`, `overrides.php` (заглушки для заблокированных),
`geoip.php`, `metrics.php`, `cron.php`, `addsub.php` (склейка двух подписок), `clientver.php`,
`reports.php`, `branding.php`, `landing.php`, `chat.php`. `schema.sql` — 20+ таблиц, включая
`grace_users`, `overrides`, `request_log`, `webhook_log`, `forward_log`, `panel_write_log`,
`addsub_map`, `addsub_cache`, `chan_*` (канал), `app_*` (приложение).

**Сопоставление с нашим проектом — важный результат.** Ключевая функциональность прослойки у нас **уже
реализована**:

| Функция middleware | Наш аналог | Статус |
| --- | --- | --- |
| Зеркало подписки на своём домене | `backend/app/sub_proxy.py` (537 строк) | есть, с тем же обоснованием |
| Грейс-доступ при истечении | `backend/app/grace_access.py` | есть, с cooldown и «сброс трафика при оплате» |
| Заглушка для заблокированного устройства по HWID | `sub_proxy.py` (блок по `x-hwid`) | есть |
| Переписывание заголовков по приложению | `sub_proxy.py` (правила по User-Agent и ОС) | есть |
| Склейка двух подписок в одну ссылку | `sub_proxy.py` (`addsub`) | есть |
| Журнал запросов подписки | `sub_proxy.py` → «Журнал подписки», 14 дней | есть |
| Доп. конфиги WireGuard/VLESS | `wg_pool.py` | есть |
| Нейтральная страница для сканеров | `sub_proxy.py` | есть |

То есть переписывать middleware на PHP-стеке ради тех же функций не требуется.

## Сравнение архитектур

| Параметр | Наш магазин | remnawave-admin | bedolaga-bot | bedolaga-cabinet | middleware |
| --- | --- | --- | --- | --- | --- |
| Backend | FastAPI, 173 модуля | FastAPI + 60 core | FastAPI + 180 сервисов | нет своего | PHP без фреймворков |
| Frontend | Next.js 16 (admin + cabinet) | React + Vite | нет | React + Vite | PHP + jQuery-подобный |
| БД | PostgreSQL 18 | PostgreSQL | PostgreSQL | — | SQLite / MySQL |
| Тесты | 216 файлов, 1833 теста | 267 файлов | 783 файла | 281 файл | **0** |
| Workflows | 15 | 7 | 10 | 7 | 2 |
| Лицензия | Corgi Lusi Source 2.8 | AGPL-3.0 | Commons Clause | AGPL-3.0 | **нет** |
| Языков | 3 (ru/en/uk) | 2 | 2+ | 4 | 1 |

## Вывод по переносу

**Ни одна строка стороннего кода в проект не переносилась и не может быть перенесена.**

| Репозиторий | Перенос | Причина |
| --- | --- | --- |
| remnawave-admin | запрещён | AGPL-3.0: требует открыть весь магазин |
| remnawave-reverse-proxy | разрешён, но не нужен | MIT; у нас свой Caddy, автор против production |
| bedolaga-bot | **запрещён** | Commons Clause: нельзя продавать производное |
| bedolaga-cabinet | **запрещён** | AGPL-3.0 |
| subscription-middleware | **запрещён** | лицензия не указана = полное авторское право |

Если функция нужна и у нас её нет — она реализуется самостоятельно (см.
[CODE_REUSE_REGISTER.md](CODE_REUSE_REGISTER.md)).

## Ограничения исследования

| Что | Почему |
| --- | --- |
| Сторонние проекты не запускались | не было задачи, и это не дало бы права на перенос |
| Не читались все 1764 файла бота | для решения о переносе достаточно лицензии; глубокое чтение не меняет вывод |
| Звёзды и дата пуша — по клону | `git log -1` в клоне, а не в веб-интерфейсе |

## Связанные документы

* [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md) — аудит из предыдущего этапа, дополнен этими данными
* [CODE_REUSE_REGISTER.md](CODE_REUSE_REGISTER.md) — что берём, что пишем сами, что не нужно
* [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) — архитектура нашего проекта
* [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) — что физически есть у нас
