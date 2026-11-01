# Реестр переиспользования кода

Решение по каждой функции пяти референсных проектов: что берём, что пишем сами, что не нужно.
Основание — лицензия источника (см. [REFERENCE_REPOSITORIES.md](REFERENCE_REPOSITORIES.md)) и
фактическое наличие функции у нас.

Дата решения: 2026-11-01. Коммит основного репозитория, на котором сверялось: `7ac7985`.

## Правило

| Лицензия источника | Перенос разрешён | Что делаем |
| --- | --- | --- |
| MIT | да, с сохранением copyright | можно, если функции нет |
| AGPL-3.0 | только открыв весь продукт по AGPL | **не переносим** |
| Commons Clause | нет: запрещена продажа производного | **не переносим** |
| Лицензия отсутствует | нет: полное авторское право | **не переносим** |

**Итог: ни одна строка стороннего кода в проект не переносилась.** Единственный источник, откуда перенос
формально разрешён (`remnawave-reverse-proxy`, MIT), нам не нужен: у нас свой reverse proxy на Caddy.

## 1. Функции, которые уже есть у нас

Проверено по коду и таблице маршрутов собранного приложения, а не по README.

| Функция | Источник-идея | Наша реализация | Статус |
| --- | --- | --- | --- |
| Зеркало подписки на своём домене | middleware `index.php` | `backend/app/sub_proxy.py` (537 строк) | есть, с тем же обоснованием: домен панели не открывается из РФ |
| Блок устройства по HWID с заглушкой | middleware `overrides.php` | `sub_proxy.py` (`x-hwid`, `x-hwid` в User-Agent) | есть |
| Грейс-доступ при истечении | middleware `grace.php` | `backend/app/grace_access.py` | есть, с cooldown и «сбрасывать трафик при оплате» |
| Переписывание заголовков по приложению | middleware `clientver.php` | `sub_proxy.py` (правила по User-Agent и ОС) | есть |
| Склейка двух подписок в одну ссылку | middleware `addsub.php` | `sub_proxy.py` | есть, только для URI-списков |
| Журнал запросов подписки | middleware `request_log` | `sub_proxy.py` → «Журнал подписки» | есть, 14 дней |
| Доп. конфиги WireGuard/VLESS | middleware `wglease.php` | `backend/app/wg_pool.py` | есть |
| Нейтральная страница для сканеров | middleware `landing.php` | `sub_proxy.py` | есть |
| Reverse proxy с автоматическим TLS | reverse-proxy целиком | `deploy/Caddyfile` + сервис `caddy` | есть, TLS и HTTP/3 |
| Анти-абьюз по HWID/IP/UA | admin `hwid_guard`, `ip_guard` | `anti_sharing.py`, `abuse.py` | есть |
| Мониторинг нод и алерты | admin `attack_detector`, `metrics` | `monitoring`, `deploy/prometheus`, `deploy/grafana` | есть |
| Почтовый домен: свой MX, SPF/DKIM/DMARC | admin `mail/` | `mail_domain.py` (1052 строки), `mail_receiver.py` | есть |
| Терминал узлов | admin `terminal_sessions` | `node_terminal.py` (617 строк) | есть |
| Анти-торрент | admin `torrent_p2p_whitelist` | `torrent_detection.py`, `platform_api.py` | есть |
| Apple IAP | bot `apple_iap*` | `payment_platform.py`: `apple_iap`, App Store Server API, ES256 | есть |
| Google Play Billing | bot (в README) | `payment_platform.py`: `google_play`, androidpublisher, RS256 | есть |
| Триал | bot `trial_activation_service` | `POST /api/me/trial`, `TrialGrant`, `trial_history` | есть |
| Промокоды | bot `promocode_service` | `promo-codes` (5 маршрутов), `promo_group` | есть |
| Подарочные подписки | bot `gift_*` | `gift_orders.py`, `admin/gifts` | есть |
| Склейка аккаунтов | bot `account_merge_service` | `account_merge.py` (712 строк) | есть |
| Запрет одноразовых почт | bot `disposable_email_service` | `guest_checkout.py`, `mobile_panels.py` (`block_disposable`) | есть |
| Конкурсы рефералов | bot `contest_rotation_service` | `referral_contests.py` | есть |
| Фискализация | bot `nalogo_*` | `fiscal.py` (631 строка), `admin/fiscal` | есть |
| Push-уведомления | admin `push_service` | `push.py` (642 строки), `push_campaigns.py` | есть |
| Плагины | admin `plugin_installer` | `plugins.py` (889 строк), `admin/plugins` | есть |
| Автоматизация по правилам | admin `automation_engine` | `automation.py` (520 строк), `admin/automation` | есть |
| Резервные копии в S3 | admin `backup_s3` | `backup_verify.py`, `boto3`, `scripts/backup.sh` | есть |
| Ограничение скорости на ноде | admin `throttle_sync`, `shaper_rollout` | `node_terminal.py`, агент узла | есть |
| OAuth: Яндекс, VK, Google | cabinet | `auth_api.py`: `/api/auth/{yandex,vk,google}` | есть |
| Passkeys (WebAuthn) | admin `webauthn_svc` | `passkeys`, 8 маршрутов | есть |
| 2FA (TOTP) | admin `totp` | `security.py` (`verify_totp`) | есть |
| RBAC | admin `rbac` | `security.py` (`PERMISSIONS`, `require_permission`) | есть |
| Темы оформления | cabinet `BackgroundConfigEditor` | `admin/src/main.tsx` (`ThemePresets`), `app_config.py` | есть |

**33 функции уже реализованы.** Перенос был бы дублированием, а не ускорением.

## 2. Платёжные кассы — точный подсчёт

Это отдельный раздел, потому что числа здесь легко завысить.

| Показатель | Факт | Чем проверено |
| --- | --- | --- |
| Кассы с webhook-маршрутом | **17** + `remnawave` = 18 путей | таблица маршрутов: `/api/webhooks/{anore, antilopay, aurapay, cashera, cloudpayments, crypto, cryptobot, freekassa, lava, mulenpay, pal24, paritypay, platega, rollypay, tribute, wata, yookassa}` |
| Платформенные провайдеры | **5** | `payment_platform.py`: `stripe`, `paypal`, `crypto`, `apple_iap`, `google_play` |
| Способы оплаты в реестре | **18** записей | `payment_methods.py`, включая `sbp` и `card` как подсказки метода |
| Telegram Stars | есть, **3 маршрута** | `/api/me/stars-subscriptions`, `/{row_id}/cancel`, `/api/me/wallet/stars-invoice` |
| Tribute | есть | `/api/webhooks/tribute`, `/api/me/wallet/tribute` |

Итого **больше 20 способов принять деньги**, из них 17 внешних касс с подтверждением через webhook.

### Кассы, которых у нас нет

Все восемь реализованы в `bedolaga-bot` под **Commons Clause** — переносить нельзя.

| Касса | Решение | Обоснование |
| --- | --- | --- |
| Cispay | писать самим, если появится спрос | перенос запрещён лицензией |
| Etoplatezhi | писать самим | запрещён |
| Jupiter | писать самим | запрещён |
| RioPay | писать самим | запрещён |
| SeverPay | писать самим | запрещён |
| TabPay | писать самим | запрещён |
| OverPay | писать самим | запрещён |
| Kassa AI | писать самим | запрещён |

**Ни одна из восьми не блокирует запуск.** У нас закрыты все крупные российские каналы: карты и СБП —
YooKassa, Freekassa, CloudPayments, Platega, RollyPay, Lava, Pal24, MulenPay, WATA, Antilopay, AuraPay,
Anore, Cashera, ParityPay; крипта — CryptoBot и `crypto`; звёзды — Telegram Stars; донаты — Tribute;
мобильные покупки — Apple IAP и Google Play. Архитектура `gateways/` позволяет добавить кассу одним
модулем плюс запись в `GATEWAYS`.

## 3. Функции, которых у нас нет и которые не нужны

| № | Функция | Источник | Лицензия | Решение |
| --- | --- | --- | --- | --- |
| 1 | Колесо фортуны, донат-виджет | bot `wheel_service`, `donut_service` | Commons Clause | не планируется: геймификация не входит в бренд-задачу и создаёт риск «казино» |
| 2 | Реактивация ушедших клиентов | bot `user_revival_service` | Commons Clause | не планируется: задача закрыта иначе — `churn.py`, `feedback`, `loyalty.py` |
| 3 | Отдельный nginx-режим прокси | reverse-proxy | MIT | не нужно: свой Caddy, автор против production |
| 4 | Четыре языка кабинета (fa, zh) | cabinet `locales/` | AGPL-3.0 | не нужно: задание требует ru/en/uk |
| 5 | DPI-чекер в кабинете | cabinet `AdminDpiChecker` | AGPL-3.0 | частично закрыто: `block_monitor.py`, `filter_geo_ripe.py`, `NetworkIntel` |

## 4. Идеи для бэклога (не код)

Пять модулей из `remnawave-admin/core/`, которых у нас нет в явном виде. Это направления для
**собственной** реализации, не перенос.

| Идея | Что даёт | У нас сейчас |
| --- | --- | --- |
| `api_key_usage` — учёт расхода ключей плагинов | видно, сколько запросов тратит каждый ключ | ключи есть в `plugins.py`, учёта расхода нет |
| `fail2ban_logger` | автоматическая блокировка перебора на уровне хоста | есть rate limit и `security-scan.sh`, интеграции с fail2ban нет |
| `retention` — единая политика хранения | один экран «сколько хранить логи, журналы, копии» | хранение настроено точечно: `dmarc_report_retention_days` (180), `RETENTION_DAYS` у торрентов, сроки в `sub_proxy.py` |
| `webhook_security` — общий модуль проверки | одна точка правки правил подписи | подпись проверяется в каждом `gateways/*.py` — работает, но размазано |
| Разделение guard по типу угрозы | hwid / ip / login / rate отдельными модулями | всё в `anti_sharing.py`, `abuse.py`, `security.py` — работает, рефакторинг не делался намеренно |

Рефакторинг работающего кода ради структуры на этом этапе **не выполнялся**: риск сломать прод
выше выгоды, а задача этапа — исследование.

## 5. Уведомления об авторстве

Переноса не было, поэтому чужие copyright в `THIRD_PARTY_NOTICES.md` не добавлялись. Файл перечисляет
сторонние **библиотеки** (Python-пакеты, npm-пакеты, шрифты, Xray-core, LibXray) — это корректный состав.

Порядок на будущее, если понадобится MIT-код из `remnawave-reverse-proxy`: добавить блок в
`THIRD_PARTY_NOTICES.md` с copyright eGames, указать файл-источник и дату переноса, сохранить текст MIT.

## 6. Реестр решений

| Решение | Количество |
| --- | --- |
| Функция уже реализована у нас | 33 |
| Кассы, которые пишем сами при необходимости | 8 |
| Не требуется по заданию | 4 |
| Частично закрыто иначе | 1 |
| Взято как идея (не код), в бэклог | 5 |
| **Строк перенесённого кода** | **0** |

## 7. Как проверялось

| Проверка | Метод |
| --- | --- |
| Доступность пяти репозиториев | `git clone --depth 60`, все успешны |
| Лицензия каждого | чтение `LICENSE`/`COPYING`/`NOTICE` в корне и на глубине 2 |
| Отсутствие лицензии у middleware | `find . -iname "*licen*" -o -iname "*copying*" -o -iname "*notice*"` — пусто; grep по README и INSTALL — пусто |
| Наличие функции у нас | grep по `backend/app/*.py` и таблица маршрутов собранного приложения |
| Число касс | подсчёт уникальных путей `/api/webhooks/*` и записей `GATEWAYS` |
| Отсутствие переноса | в `THIRD_PARTY_NOTICES.md` только библиотеки; сторонних исходников в дереве нет |

## Связанные документы

* [REFERENCE_REPOSITORIES.md](REFERENCE_REPOSITORIES.md) — что представляют собой пять проектов
* [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md) — аудит предыдущего этапа
* [MASTER_ROADMAP_VPN_SHOP.md](MASTER_ROADMAP_VPN_SHOP.md) — реестр функций нашего проекта
* [../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) — сторонние компоненты
