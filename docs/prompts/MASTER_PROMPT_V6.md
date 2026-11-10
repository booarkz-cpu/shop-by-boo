# ЕДИНЫЙ МАСТЕР-ПРОМПТ SHOP BY BOO / VPN SHOP BY CORGI LUCY

**Полная восстановленная редакция на основе исходного XML v2.0 и дополнения v3.0**  
**Целевой репозиторий:** `https://github.com/booarkz-cpu/shop-by-boo.git`  
**Формат:** Markdown для передачи Claude AI

> ВАЖНО: В предыдущих ответах использовались сокращённые реконструкции. Эта редакция построена из найденного исходного XML-файла размером 85 443 байта. Все его 36 верхнеуровневых разделов, вложенные элементы, атрибуты и текст включены ниже. Дополнительные требования из доступной истории добавлены отдельным приложением. Ничего из исходного XML не удаляется.

## Инструкция Claude

Полностью прочитай весь документ, включая приложение с исходным XML. Сохрани каждое требование, критерий, ограничение, ID, имя, URL, команду, статус и пример. Не сокращай и не переписывай задачи в общие формулировки. Создай трассируемый реестр требований; при объединении дублей сохраняй все уникальные детали и ссылки на источники. Если обнаружится дополнительная задача в полной истории, issue, PR, репозитории или скриншоте, добавь её, не удаляя существующие.

## Часть I. Полный текст исходного мастер-промпта в Markdown

### Document Purpose

Полный мастер-промпт Claude AI. Все задачи, требования и критерии сохраняются. Разрешено добавлять и объединять дубли только без потери уникальных требований.

### Critical Rule

Единственный целевой репозиторий всей экосистемы — shop-by-boo. Название не менять. Не создавать отдельные целевые репозитории для приложений, сервисов, API, мобильных клиентов, админки, платежей, инфраструктуры, документации или тестов. Всё находится в одном монорепозитории, но сохраняет логические границы, независимые сборки и возможность независимого развёртывания сервисов.

### Role

Действуй как автономная команда Principal Architect, Senior/Staff Engineers, DevOps, Security, QA, Mobile и Product Engineering. Не ограничивайся планом: анализируй, реализуй, тестируй, документируй и доказывай результат. Не заявляй о выполнении без доказательств. Не повторяй вопросы, ответы на которые уже есть в исходниках.

### Primary Repository

https://github.com/booarkz-cpu/shop-by-boo.git

### Source Repositories

#### Repo

https://github.com/booarkz-cpu/VPN-Shop-by-CorgiLusi.git

#### Repo

https://github.com/booarkz-cpu/remnawave-manager

#### Repo

https://github.com/eGamesAPI/remnawave-reverse-proxy

#### Repo

https://github.com/Case211/remnawave-admin

#### Repo

https://github.com/BEDOLAGA-DEV/remnawave-bedolaga-telegram-bot

#### Repo

https://github.com/BEDOLAGA-DEV/bedolaga-cabinet

#### Repo

https://github.com/STEP-CORP/StepBot/tree/main

#### Repo

https://github.com/booarkz-cpu/lucy-vpn-android

#### Mandatory Read

docs/CODE_REUSE_REGISTER.md

#### Mandatory Read

docs/REFERENCE_REPOSITORIES.md

#### Rule

Исходные репозитории — источники аудита и миграции, а не отдельные целевые репозитории. Проверить лицензии, авторские права, историю, зависимости и происхождение кода. Не удалять исходные репозитории и ветки. Составить карту компонентов, API, уникальных и дублирующихся функций, ошибок, плана миграции и результатов тестов.


### Monorepo

#### Apps

vpn-client/android; vpn-client/ios; vpn-shop; user-cabinet; telegram-bot; telegram-mini-app; lucy-admin/web; lucy-admin/android; lucy-admin/ios; status-page.

#### Services

api; authentication; payment-orchestrator; subscription-manager; remnawave-integration; node-manager; node-provisioning; auto-selection; masque; notification-service; support.

#### Packages

shared-ui; shared-api; shared-types; shared-config; localization; payment-contracts; security; testing.

#### Infrastructure

docker; installer; provisioning; vpn-nodes; reverse-proxy; monitoring; security; backup; deployment.

#### Other

database/migrations; database/schemas; database/seeds; scripts/audit; scripts/build; scripts/migration; scripts/release; scripts/maintenance; tests/unit; tests/integration; tests/e2e; tests/security; tests/mobile; tests/infrastructure; docs/ru; docs/en; docs/uk; docs/architecture; docs/payments; docs/remnawave; docs/masque; docs/installation; docs/security; docs/screenshots; artifacts/audit; artifacts/builds; artifacts/screenshots; artifacts/reports; .github/workflows.

#### Rule

Адаптируй структуру к фактическому стеку, не создавай фиктивных пустых модулей и не теряй самостоятельность сборок.


### Products
<text>`equal_priority` = `true`</text>

#### Корги Люси: Клиент
<text>`id` = `vpn-client`</text>

##### Purpose

Полностью бесплатный универсальный VPN-клиент Android/iOS для совместимых сторонних VPN-подписок. Не зависит от коммерческого backend VPN Shop, не требует обязательной регистрации или покупки.

##### Imports

URL; QR; файл; буфер обмена; ручное добавление; несколько подписок; обновление; редактирование; удаление; экспорт; диагностика конфигурации; проверка доступности серверов.

##### Protocols

VLESS; REALITY; Trojan; Shadowsocks; VMess; Hysteria 2; TUIC; MASQUE и другие — только если подтверждены движком и платформой.

##### Features

Split Tunneling; Smart Routing; Live Traffic; LAN Proxy Share; Self-Healing; Battery Saver; Pet the Corgi; Haptic Feedback; авто-выбор сервера; проверка задержки; уведомления; PIN; биометрия; диагностика; профили; импорт/экспорт; восстановление подключения.

##### Branding

###### Banner

Свободный Гав в интернете!

###### Slogan

Твой интернет. Твои правила. Твоя Люси

###### Style

Тёмная/космическая градиентная концепция; маскот корги; список серверов; цветной статус; задержка XX ms; SVG Add; заметные переключатели.

###### Remove

Лишние счётчики дней; декоративный огонёк; баннер «ЗАЩИТА В ОДНО КАСАНИЕ»; маска; кнопка «Безлимит».


##### Critical Bug

Приложение может падать при включении PIN/биометрии из настроек подключения. Получить Logcat/stack trace; найти первопричину; проверить Activity/Service lifecycle, VPNService, блокировку UI, разрешения и состояние подключения; исправить; блокировка UI не должна завершать VPNService или сессию; проверить минимум 15 сценариев.


#### VPN Shop by Corgi Lucy
<text>`id` = `vpn-shop`</text>

##### Scope

Backend; API; Telegram Bot; Telegram Mini App; кабинет; регистрация; авторизация; тарифы; подписки; платежи; Remnawave; VPN-ноды; статистика; пользователи; уведомления; поддержка; аналитика; автоматизация.

##### Lucy Max
<text>`devices` = `2`; `traffic` = `unlimited`</text>

##### Lucy Ultra
<text>`devices` = `4`; `traffic` = `unlimited`</text>

Визуально и коммерчески выгоднее Lucy Max.

##### Lucy Mini — Test
<text>`duration` = `3 days`; `devices` = `1`</text>

Для тестирования сервиса.

##### Rule

Не менять цены и коммерческие условия без обоснования и разрешения.

##### Authentication

Email; VK; Yandex — если безопасно и технически подтверждено.

##### Telegram

Проверить и исправить ранее сообщавшуюся проблему неработающего Telegram Bot. Проверить команды, меню, регистрацию, покупку, продление, оплату, выдачу подписки, уведомления, поддержку, Mini App, webhook, ошибки и восстановление после перезапуска.


#### Lucy Admin
<text>`id` = `lucy-admin`</text>

##### Interfaces

Web Admin; Android Admin; iOS Admin; единый API; RBAC; аудит.

##### Modules

Dashboard; Users; Roles; Tariffs; Subscriptions; Payments; Payment Providers; Remnawave; VPN Nodes; Node Provisioning; MASQUE; VLESS/REALITY; Hysteria 2; Server Monitoring; Network Monitoring; Telegram Bot; Telegram Mini App; User Cabinet; VPN Client Management; Commercial App Management; Android Builds; iOS Builds; GitHub; CI/CD; Pull Requests; Releases; Docker; Installer; Database; Backup/Restore/Rollback; Updates; Security Center; Audit Logs; API Management; Notifications; Support; Localization; Documentation; System Settings; Automation Center; Autonomous Audit; Checklist Dashboard; Screenshot Coverage; Admin Feature Parity; Payment Testing; Protocol Compatibility; Infrastructure Diagnostics; Node Installation and Maintenance; Auto-selection Management; Subscription Status Page; Server Protection; Dangerous Operations; Repair and Recovery; Migration Tools.

##### Parity Document

docs/ADMIN_FEATURE_PARITY_MATRIX.md

##### Parity Fields

Web; Android; iOS; API; статус; функциональность; тесты; ограничения; evidence.

##### Rule

Ни одна кнопка не должна быть декоративной или фиктивной.



### Full Audit

#### Scope

Архитектура; backend; frontend; API; мобильные приложения; БД; миграции; Telegram; платежи; Remnawave; Docker; installer; инфраструктура; безопасность; CI/CD; документация; лицензии; тесты; зависимости; конфигурации; производительность.

#### Find

Критические ошибки; уязвимости; неработающие функции; чёрные/пустые страницы; недоступные модули; фиктивные кнопки; неиспользуемый код; дублирующиеся сервисы/API; конфликтующие схемы БД; несовместимые библиотеки; ошибки сборки и развёртывания.

#### Known Error

ERROR: installation failed at line 427

#### Known Error

ImportError: cannot import AsyncSessionLocal from app.db; suggested SessionLocal

#### Known Error

Cannot read properties of undefined (reading 'trim')

#### Known Error

(s || []).map is not a function

#### Docker Checks

Dockerfile; Compose; volumes; networks; ports; health checks; restart policies; dependencies; environment; secrets; database; migrations; logs; доступность сервисов.

#### Rule

Устранять первопричины, а не только симптомы.


### Payment Ecosystem

#### Priority

Обязательная часть реализации, не отложенный backlog.

#### Architecture

Provider Registry; Adapter Interface; Capabilities Registry; Method Registry; Router; Priority Queue; Health Monitor; Circuit Breaker; Payment API; Webhook Router; Signature Validator; State Machine; Idempotency; Transaction Registry; Order Registry; Reconciliation; Refund Service; Recurring Payments; Risk Assessment; Chargeback Management; Tax/Fiscalization; Analytics; Audit Log.

#### Providers

Telegram Stars; Tribute; CryptoBot; Heleket; YooKassa; MulenPay; Pal24; Platega; WATA; FreeKassa; FreeKassa SBP; FreeKassa Card; CloudPayments; Kassa AI; RioPay; SeverPay; RollyPay; Overpay; AuraPay; Etoplatezhi; Antilopay; Jupiter; Donut; Lava; CisPay; Anore; TabPay; ParityPay; Cashera; Stripe; PayPal; Apple StoreKit; Google Play Billing; Crypto Gateway; Sandbox.

#### Configuration Ids

telegram_stars; tribute; cryptobot; heleket; yookassa; mulenpay; pal24; platega; wata; freekassa; freekassa_sbp; freekassa_card; cloudpayments; kassa_ai; riopay; severpay; rollypay; overpay; aurapay; etoplatezhi; antilopay; jupiter; donut; lava; cispay; anore; tabpay; paritypay; cashera.

#### Classification

Не путать провайдера, метод оплаты, конфигурационный ID, платформенный платёж и sandbox. Наличие адаптера/ID не означает работоспособность.

#### Methods

Банковские карты; СБП; QR СБП; SberPay; YooMoney; криптовалюта; встроенные методы платформ; иные методы только при подтверждении API.

#### Known Capabilities

##### YooKassa

card; sbp

##### Pal24

sbp; card

##### Platega

Динамические методы — проверить.

##### FreeKassa

sbp; card

##### Kassa AI

sbp; card; sberpay

##### RollyPay

sbp; card; crypto

##### Overpay

Динамические методы — проверить.

##### AuraPay

card; sbp

##### Etoplatezhi

card; sbp

##### Antilopay

card; sbp; sberpay

##### Jupiter

sbp

##### Donut

card; sbp; sbp_qr

##### Lava

card; sbp

##### CisPay

card; sbp; crypto

##### Anore

sbp; card; yoomoney; crypto

##### TabPay

card; sbp

##### ParityPay

card; sbp

##### Cashera

Динамические методы — проверить.

##### CloudPayments

Проверить выбор метода на странице провайдера.


#### Verify

Для Telegram Stars, Tribute, CryptoBot, Heleket, MulenPay, WATA, RioPay, SeverPay проверить адаптеры и официальные возможности. Не выдумывать методы. Mir Pay, T-Pay, Alfa Pay исследовать только при подтверждённой технической возможности.

#### Statuses

IMPLEMENTED; CONFIGURED; SANDBOX_VERIFIED; PRODUCTION_VERIFIED; BLOCKED_SECRETS; BLOCKED_PROVIDER; NOT_SUPPORTED; RETIRED.

#### Scenarios

Покупка; продление; автопродление; возврат; частичный возврат; повторная оплата; отмена; истечение; неуспешная оплата; сверка; chargeback; повторная проверка статуса; webhook; проверка суммы/валюты/заказа; защита от повторной обработки; восстановление; failover; sandbox; финансовый журнал; аналитика.

#### Platforms

Apple StoreKit и Google Play Billing: серверная проверка транзакций, статусы, отмены, истечения, восстановление. Telegram Stars: invoice, pre-checkout, successful_payment. Tribute: проверить фактические механизмы.

#### Security

Подписи webhook; replay protection; idempotency; проверка суммы, валюты, заказа; защита от подмены статуса; проверка через API провайдера; журнал; защита секретов; RBAC.

#### Docs

docs/PAYMENT_PROVIDER_INVENTORY.md; docs/PAYMENT_METHODS_MATRIX.md; docs/PAYMENT_CAPABILITIES_MATRIX.md; docs/PAYMENT_TESTING.md; docs/PAYMENT_SECURITY_REPORT.md; docs/PAYMENT_RECONCILIATION.md; docs/PAYMENT_PROVIDER_ONBOARDING.md.

#### Audit Scripts

scripts/audit/check_payments.py; check_payment_provider_registry.py; check_payment_capabilities.py; check_payment_webhooks.py; check_payment_methods_ui.py; check_payment_contracts.py; check_payment_reconciliation.py.

#### Rule

Не выполнять реальные платежи/возвраты без разрешения. Не выдумывать production secrets.


### Remnawave

#### Goal

Полная интеграция Remnawave в экосистему и Lucy Admin.

#### Capabilities

Пользователи; подписки; тарифы; устройства; трафик; сроки; ноды; конфигурации; статусы; подключения; статистика; блокировки; продление; выдача подписок.

#### Requirements

Проверить реальные API, модели, ограничения и версии; синхронизация; обработка ошибок; повторы; журнал; мониторинг; восстановление; контроль панели; миграция; backup. Продажа подписок через Remnawave через единый backend и платежи.


### Masque

#### Goal

Максимально автоматизированный Zero-Touch Provisioning MASQUE.

#### Version Claim

Xray-core v26.10.10+

#### Verification

Проверить существование версии и реальную поддержку MASQUE по официальным источникам. Не утверждать поддержку без подтверждения.

#### Node Provisioning

Python/Next.js; Bash; SSH; Docker; установка на чистую ноду; проверка портов; ACME/Let's Encrypt; TLS; безопасная передача сертификатов и ключей.

#### Multiplexing

Исследовать MASQUE HTTP/3 UDP; MASQUE HTTP/2 TCP; Hysteria 2 UDP; VLESS+REALITY TCP/UDP; конфликты 443; разные порты; ALPN; SNI; routing; listener; reverse proxy; ограничения REALITY; QUIC/TCP. Подготовить проверенные inbounds/routing.

#### Grpc

Проверить HandlerService, AddInbound, StatsService и необходимые методы. Реализовать hot reload без неоправданного прерывания соединений, точную статистику и синхронизацию лимитов.

#### Subscriptions

VLESS Reality; Hysteria 2; MASQUE; JSON/Base64 bundle; v2rayNG; NekoBox. Неподдерживаемый MASQUE не должен ломать остальные конфигурации.

#### Admin Ui

Переключатели MASQUE; проверка совместимости; скрытие дублирующих настроек; fallback domain; мониторинг установки; прогресс; диагностика.

#### Anti Dpi

Исследовать unauthorized requests; probing; fallback; легитимный веб-сервер; ограничения защиты. Не обещать гарантированную защиту от DPI.

#### Alternative Engine

Если Xray не поддерживает нужное, исследовать sing-box и другие движки.

#### Deliverables

Архитектура; официальное подтверждение; код; конфигурации; тесты; ограничения; безопасность; документация.

#### Report

docs/MASQUE_IMPLEMENTATION_REPORT.md


### Node Manager

#### Features

Добавление; удаление; изменение параметров; доступность; SSH; управление сервисами; мониторинг; диагностика; установка; обновление; восстановление; backup; проверка конфигураций; безопасность.

#### Bulk

Массовые операции показывают выбранные ноды, компоненты, последствия, rollback и backup до выполнения.


### Server Installation Maintenance

#### Rule

Восстановить и полноценно реализовать функциональность «Установка» и «Обслуживание и защита», показанную на скриншотах. Скриншоты — требования, не доказательство реализации. Проверить исходный код; отсутствующее реализовать; существующее проверить.

#### Catalog

Каталог карточек: название; описание; категория; тип подключения; целевые ноды; требования; кнопка; прогресс; результат; журнал; диагностика.

#### Mtproto

Установка MTProto Proxy на выбранную ноду; автоматическая настройка; корректная ссылка; показ ссылки; проверка доступности; журнал; удаление без влияния на другие сервисы.

#### Haproxy Cascade

Каскад HAProxy через 2–3 ноды; выбор транзитных и конечной; настройка маршрута; проверка каждого звена и TCP; диагностика; без ненужного второго шифрования; безопасное применение; rollback.

#### Live Traffic Test

Проверка реальным трафиком через подписку живого клиента; тестовый запрос; фактический маршрут и внешний адрес; результат; журнал; диагностика DNS, маршрутизации и подключения. Не подменять статической проверкой.

#### Geoassets

Обновление geoip.dat, geosite.dat и других GeoAssets; версия; источник; целостность; checksum; хранение; backup; применение; проверка конфигурации; минимальный перезапуск; rollback. Для нод без Docker Compose — безопасный поддерживаемый способ. Ориентир около 10 секунд только измерять, не гарантировать.

#### Xray Adblock

Отдельная блокировка рекламы/трекеров через DNS/geosite и подтверждённые возможности Xray; выбор нод; пользовательские домены; проверка DNS; rollback.

#### Adguard Home

Отдельная установка AdGuard Home; выбор нод; DNS; интеграция с Xray; списки; статистика; мониторинг; резервный DNS; диагностика; учитывать ресурсы. Не устанавливать конкурирующие механизмы без проверки.

#### Rkn Diagnostics

Проверка 443; selfsteal; порт 80; редирект 301; TLS 1.2/1.3; HSTS; заглушка; Trojan; VLESS; Vision; открытые порты; доступность панели. Исправления безопасные и обратимые; не закрывать админ-доступ; не обещать невозможность блокировки.

#### Mss Clamp

Проверка MTU/MSS; маршруты до Cloudflare, Яндекс DNS и контрольных адресов; расчёт; необходимость; применение; сохранение после reboot; проверка соединений; не перезапускать VPN без нужды.

#### Panel Node Access

SSH-порт; доступ только с IP панели; массовое применение; миграция панели; предварительное добавление нового IP; проверка доступности; автоматическая отмена правила при потере доступа; не блокировать SSH администратора.

#### Torrent Blocker

Обнаружение BitTorrent в логах Xray; временный бан IP; nftables/iptables; правила; журнал; автоматическое снятие; диагностика; предупреждение о влиянии на общие ноды; до перезапуска Xray показать последствия.

#### Panel Https

HTTPS по домену; ACME; Let's Encrypt; DNS; сертификат; продление; срок; reverse proxy; доступность. При конфликте 443 обнаружить и предложить порт; проверить 80 для ACME; не перезаписывать чужую конфигурацию.

#### Status Page

Публичная статус-страница; реальная доступность нод; тестовый трафик; online/latency; инциденты; состояние сервисов; домен; не раскрывать секреты и внутренние адреса. TCP-порт сам по себе не доказывает работоспособность.

#### Bbr

Определить ядро Linux, версию, виртуализацию, congestion control, права и совместимость; включать только поддерживаемый BBR/BBR3; проверить результат и rollback.

#### Backups

Ежедневные backup PostgreSQL Remnawave, конфигураций, необходимых файлов, метаданных и инфраструктуры; расписание; ротация; размер; шифрование; целостность; off-site; Telegram-уведомления; журнал; тест восстановления; срок хранения. Не хранить секреты в открытых архивах.

#### Snapshot Download

Экспорт дампа БД Remnawave, конфигураций и метаданных; защищённое скачивание на устройство; права; checksum; временное хранение; журнал; предупреждение о конфиденциальности.

#### Crowdsec

Установка; защита SSH/web от brute force; обнаружение сканирования; community blocklists при соблюдении условий; мониторинг; журнал; уведомления; firewall bouncer; снятие ложных блокировок.

#### Hubguard

Защита nftables; ограничение новых соединений; защита от сканирования и перебора; отдельная таблица; не ломать ufw/CrowdSec; whitelist SSH и необходимого CGNAT; сохранять действующие сессии; проверить доступность панели; rollback.

#### Danger Zone

##### Remove Component

Удалять только выбранный компонент: бот, ноду, status page, MTProto или другой модуль. Не затрагивать остальные сервисы.

##### Clean Server

Полное удаление Remnawave, нод, контейнеров, конфигураций и связанных компонентов. Необратимая операция: повторное подтверждение; точный сервер; список ресурсов; проверка backup; журнал; проверка полномочий.

##### Rule

Не путать удаление одного компонента с полной очисткой сервера.


#### Protocol Switch Repair

Последовательные этапы: чтение текущего транспорта; смена протокола inbound; обновление hosts; проверка реконнекта нод. Каждый этап показывает состояние, индикатор, журнал, ошибку, результат, время, диагностику. Определить inbound/profile; обновить и применить; обновить hosts; дождаться реконнекта; проверить все ноды; сохранить старый и новый транспорт. Не объявлять успех до проверок.

#### Node Reconnect

После смены протокола/массовой операции проверить все ноды: номер; страна; имя; online/offline; транспорт; время; ошибка; итог. Проверять не только SSH, но и реальный VPN-транспорт.

#### Common Acceptance

Для каждой операции: предварительная проверка; выбор серверов; совместимость; свободные порты и ресурсы; backup; план; последствия; прогресс; журнал; проверка результата; rollback; документация. Не допускать фиктивных кнопок.


### Auto Selection

#### Purpose

Полноценный пул автовыбора VPN-ноды.

#### Modes

##### server-side

Панель/сервер выбирает ноду и формирует подписку или отдельную плитку.

##### client-side

Ноду выбирает сам VPN-клиент.

##### Rule

Не смешивать серверный и клиентский автовыбор.


#### Delivery

##### separate-tile

Отдельная плитка «Автовыбор»; обычные ноды могут отображаться отдельно.

##### all-list

Старый режим «Весь список»; балансировка только при поддержке формата.


#### Algorithms

##### leastPing

По минимальной задержке.

##### leastLoad

По минимальной нагрузке.

##### roundRobin

По кругу.

##### random

Случайно.

##### Rule

Для каждого алгоритма определить входные данные, выбор, недоступность, обновление метрик, равные значения и fallback.


#### Management

Включение; отключение; обновление; сброс шаблона; удаление плитки; имя; алгоритм; выбор нод; массовое включение/исключение; скрытие; состав; доступность.

#### Hide Nodes

Опция «Скрыть узлы пула из списка приложения»: при включении клиент видит только плитку «Автовыбор»; при выключении узлы возвращаются после обновления подписки. Проверить Clash, sing-box, Base64 и другие клиенты. Если формат не поддерживает настоящий балансировщик, показать ограничение; не выдавать первую ноду за балансировщик.

#### Statistics

Количество нод в подписке и пуле; доступные; выдаваемые; online/offline; исключённые; последняя проверка; актуальность метрик. Только реальные данные.

#### Tile

Имя; иконка; алгоритм; ноды; видимость; состояние; отображение клиенту. Пример: ⚡ Автовыбор.

#### Failure

При недоступности выбранной ноды выбрать доступную; fallback; не выдавать недействительную конфигурацию; записать событие; обновить состояние.

#### Tests

Все четыре алгоритма; отключение ноды; изменение нагрузки/задержки; обновление подписки; скрытие/возврат; удаление плитки; изменение имени; отсутствие доступных нод; совместимость форматов; реконнект; fallback.

#### Documentation

docs/AUTO_SELECTION.md


### Additional Infrastructure

#### Items

swap; sysctl; HTTPS ports; auto-select; domain migration; SNI; repair blocked node; cascade; CDN diagnostics; MTProto; GEO; backup snapshots; CrowdSec; nftables; torrent-blocker; MSS clamp; anti-censorship; AdBlock; AdGuard; safe component removal.

#### Groups

O1–O14; N7; N10; N11; N12.

#### Rule

Найти точные исходные формулировки этих задач в backlog, документации, issues, исходных промптах и истории. Не угадывать содержание. Создать реестр с критериями, статусами и доказательствами.


### Backend Api Database

#### Scope

API; авторизация; RBAC; модели; схемы; миграции; транзакции; обработка ошибок; валидация; аудит; фоновые задачи; очереди; уведомления.

#### Rules

Не объединять бизнес-данные трёх продуктов в неразделённую модель. Общие библиотеки — общие, бизнес-логика сохраняет границы. Единые API-контракты; версионирование; обратная совместимость; документация; интеграционные тесты; контроль доступа; логирование; rate limiting.


### Ui Ux

#### Design

Material Design/Material 3; адаптивность; понятное боковое меню; современные кнопки; единые карточки; ясные статусы; мобильная совместимость; доступность; светлая/тёмная темы по необходимости.

#### Reference

Ориентироваться на функциональную ясность Support Pro, не копируя закрытые код и материалы.

#### Fix

Чёрные страницы; недоступные и пустые разделы; фиктивные кнопки; ошибки форм, модальных окон, таблиц, мобильных экранов и API. Показывать загрузку, успех и понятные ошибки.


### User Cabinet Telegram

#### Features

Регистрация; вход; профиль; устройства; покупка; продление; подписка; срок; тариф; трафик; конфигурация; QR; инструкции; поддержка; уведомления; история платежей.

#### Auth

Email; VK; Yandex при безопасной реализации.

#### Mini App

Использовать общий API, не дублировать бизнес-логику.


### Mobile

#### Android

Kotlin; Jetpack Compose; Material 3; VPNService; выбранный VPN-движок; GitHub Actions; APK/AAB. Сравнить sing-box и Xray по VLESS, REALITY, Hysteria 2, производительности, лицензиям, ограничениям, стабильности и интеграции.

#### Ios

Swift 6; SwiftUI; Network Extension; NEVPNManager; Packet Tunnel Provider; Keychain; Face ID; Touch ID; entitlements; Apple Developer requirements. Не обещать возможности, ограниченные iOS или правилами Apple.

#### Admin Mobile

Android/iOS Lucy Admin; функциональная совместимость с Web Admin; критические действия доступны согласно RBAC.

#### Rule

Все мобильные приложения находятся внутри shop-by-boo.


### Docker Installer Vps Termux

#### Checks

Dockerfile; Compose; volumes; networks; ports; health checks; restart policies; dependencies; environment; secrets; database; migrations; logs; доступность сервисов.

#### Installer

Чистая установка; обновление; повторный запуск; восстановление; backup; rollback; проверка конфигурации; доменов; диагностика.

#### Vps

Подробная инструкция установки на тестовый VPS.

#### Termux

Android/Termux: инструменты; подключение к VPS; Git; проверка репозитория; установка; запуск; обновление; логи; диагностика. Пошагово для новичка.


### Github Cicd

#### Workflows

Проверка кода; линтеры; тесты; backend/frontend builds; Android; iOS; Docker; security scanning; dependency checks; лицензии; audit; releases; документация.

#### Nightly

Проверка новых изменений; получение обновлений; анализ diff; dependency checks; backup; тестирование; сборка; совместимость; отчёт; rollback.

#### Production Rule

Не обновлять production автоматически без проверок и разрешений.

#### Runner Rule

Не обещать работу без реального runner или иной среды выполнения.

#### Admin Control

Lucy Admin показывает версии, изменения, проверки, дату, ошибки и rollback; может безопасно инициировать GitHub workflow. Не хранить токены открыто.


### Documentation

#### Readme

Назначение; архитектура; продукты; требования; установка; обновление; Docker; VPS; Termux; мобильные приложения; платежи; Remnawave; админка; диагностика; безопасность; ссылки.

#### Wiki Languages

Русский; English; Українська.

#### Guides

Архитектура; установка; администратор; пользователь; разработчик; платежи; Remnawave; VPN-ноды; MASQUE; мобильные приложения; восстановление; обновления; безопасность.

#### Rule

Не оставлять устаревшие инструкции и ненужные дубли.


### Screenshot Coverage

#### Purpose

Фактическая визуальная проверка всех продуктов, экранов, модулей и подразделов.

#### Coverage

##### VPN Shop

Главная; тарифы; покупка; оплата; подписка; история платежей; профиль; уведомления; ошибки; мобильная версия.

##### User Cabinet

Регистрация; авторизация; профиль; подписка; устройства; конфигурация; продление; платежи; поддержка; настройки.

##### Telegram Mini App

Все основные экраны; навигация; покупка; подписка; платежи; ошибки; загрузка.

##### Telegram Bot

Команды; меню; диалоги; покупка; оплата; подписка; уведомления; ошибки.

##### Lucy Admin Web

Dashboard; Users; Roles; Tariffs; Subscriptions; Payments; Payment Providers; Remnawave; VPN Nodes; Node Provisioning; MASQUE; Monitoring; Docker; Installer; Backup; Security; Logs; Automation; GitHub; Documentation и все дополнительные модули.

##### Lucy Admin Android/iOS

Основные экраны; меню; пользователи; ноды; платежи; обновления; безопасность; диагностика; операции.

##### VPN Client Android/iOS

Onboarding; импорт; подписки; серверы; подключение; настройки; PIN; биометрия; диагностика; Split Tunneling; Smart Routing; статистика; ошибки.

##### Installer and Node Maintenance

Каталог; MTProto; HAProxy cascade; live test; GeoAssets; Xray ad block; AdGuard Home; RKN diagnostics; MSS clamp; panel access; Torrent-blocker; HTTPS; Status Page; BBR/BBR3; backups; snapshots; CrowdSec; HUBGuard; danger zone; remove component; clean server; protocol repair; reconnect stages.

##### Auto-selection

Пул; состав; статистика; алгоритмы; настройки плитки; скрытие нод; выбор нод; обновление; ошибки; fallback.


#### Tools

Playwright; Android Emulator; XCTest и доступные инструменты автоматизации.

#### Rules

Скриншоты настоящие, из запущенного приложения, актуальные и привязанные к версии. Не генерировать фальшивые скриншоты и не использовать макеты как доказательство. Проверять desktop/mobile, адаптивность, loading, ошибки, успешные операции, доступность элементов, отсутствие чёрных и пустых экранов.

#### Document

docs/SCREENSHOT_COVERAGE.md

#### Metadata

Приложение; модуль; маршрут; версия; дата; сценарий; ожидаемый/фактический результат; путь к скриншоту; статус.


### Balanced Development

#### Rule

Все три продукта развиваются параллельно и имеют равную продуктовую значимость. P0–P5 обозначают только техническую срочность, риски и зависимости, не ценность продукта.

#### Documents

docs/PROJECT_BALANCED_DEVELOPMENT.md; docs/PROJECT_WORKLOAD_MATRIX.md; docs/PROJECT_COMPLETION_MATRIX.md.


### Acceptance Checklist

#### File

docs/AUTONOMOUS_ACCEPTANCE_CHECKLIST.md

#### Fields

Уникальный ID; исходная формулировка; описание; критерии; зависимости; статус; ссылка на код; тест; доказательство; дата; версия.

#### Statuses

PASS; FAIL; PARTIAL; NOT_IMPLEMENTED; BLOCKED_EXTERNAL; NOT_APPLICABLE; NOT_TESTED.

#### Rules

PASS только с реальным подтверждением; PARTIAL при частичной реализации; BLOCKED_EXTERNAL при внешней блокировке; NOT_TESTED если тест не выполнен; NOT_IMPLEMENTED если функции нет.


### Audit Automation

#### Directory

scripts/audit/

#### Scripts

run_full_audit.py; check_requirements.py; check_documentation.py; check_doc_links.py; check_screenshots.py; check_admin_parity.py; check_products_separation.py; check_api_contracts.py; check_runtime_placeholders.py; check_secrets.py; check_dependencies.py; check_licenses.py; check_docker.py; check_installation.py; check_mobile_builds.py; check_release_artifacts.py; check_tests.py; check_masque_support.py; check_vpn_protocols.py; check_node_provisioning.py; check_balanced_development.py; check_payments.py; check_remnawave.py; check_android_client.py; check_ios_client.py; generate_project_map.py; generate_audit_report.py; generate_checklist.py; check_auto_selection.py; check_node_maintenance.py; check_backup_restore.py; check_server_security.py; check_protocol_repair.py; check_status_page.py; check_mobile_ui.py; check_repository_monorepo.py; check_migration_integrity.py.

#### Workflow

.github/workflows/autonomous-audit.yml

#### Artifacts

artifacts/audit/checklist-results.json; artifacts/audit/FULL_AUDIT_REPORT.md.

#### Rule

Скрипты проверяют реальные условия, а не только наличие файлов.


### Autonomous Cycle

DISCOVER → AUDIT → BUILD CHECKLIST → VERIFY CAPABILITIES → ARCHITECT → PLAN → IMPLEMENT → TEST → SELF-CHECK → COLLECT EVIDENCE → FIX FAILURES → RE-RUN CHECKLIST → UPDATE DOCUMENTATION → CONTINUE. Не останавливаться на анализе; не повторять бесконечно неудачную команду; фиксировать внешние блокировки; продолжать независимые задачи; проверять исправления; сохранять результаты; обновлять документацию.

### State Tracking

#### Files

IMPLEMENTATION_STATUS.md; MASTER_ROADMAP.md; AUTOMATION_LOG.md; KNOWN_LIMITATIONS.md; docs/ADMIN_FEATURE_PARITY_MATRIX.md; docs/SCREENSHOT_COVERAGE.md; docs/AUTONOMOUS_ACCEPTANCE_CHECKLIST.md; docs/PROJECT_BALANCED_DEVELOPMENT.md; docs/PROJECT_WORKLOAD_MATRIX.md; docs/PROJECT_COMPLETION_MATRIX.md; docs/MASQUE_IMPLEMENTATION_REPORT.md; docs/CODE_REUSE_REGISTER.md; docs/REFERENCE_REPOSITORIES.md; docs/PAYMENT_TESTING.md; docs/AUTO_SELECTION.md.

#### Interim

PROMPT_VPN_SHOP_<DATE>_STAGE_<NUMBER>.md

#### Rule

Фиксировать каждую задачу и не терять состояние после перезапуска рабочего окружения.


### Final Reports

#### Required

FINAL_PROJECT_AUDIT.md; FINAL_IMPLEMENTATION_REPORT.md; FINAL_SECURITY_REPORT.md; FINAL_TEST_REPORT.md; FINAL_ACCEPTANCE.md.

#### Additional

Отчёт о миграции в монорепозиторий; сохранении функциональности; платежах; Remnawave; MASQUE; VPN-протоколах; Android; iOS; админке; скриншотах; installer; обслуживании нод; пуле автовыбора; backup/restore; CI/CD.

#### Fields

Что проверено; реализовано; исправлено; тесты выполнены/пройдены/не пройдены; оставшиеся проблемы; внешние блокировки; подтверждения.


### Git Security

#### Allowed

Feature branches; fix branches; pull requests; проверка изменений; CI; code review; безопасные релизы.

#### Forbidden

Force push; обход branch protection; переписывание чужой истории; удаление чужих изменений; удаление веток без разрешения; секреты в репозитории; публикация токенов; обход CAPTCHA/KYC/2FA; реальные платежи и возвраты без разрешения; удаление production-данных без разрешения; обновление production без проверок и разрешений.

#### External Blockers

При отсутствии доступа/секретов отметить BLOCKED_EXTERNAL или BLOCKED_SECRETS, подготовить безопасную конфигурацию, выполнить sandbox-тесты и продолжить независимые задачи.

#### Production Safety

Перед опасными действиями определить среду, сервер и права; сделать backup; подготовить rollback; показать последствия; получить разрешение. Не отключать защиту; не открывать лишние порты; не раскрывать токены, пароли, ключи, конфигурации пользователей, персональные данные и платёжные реквизиты. Вести audit log.


### First Execution Sequence

#### Inventory
<text>`n` = `1`</text>

Проверить shop-by-boo, Git и ветки; исходные репозитории; README; CODE_REUSE_REGISTER; REFERENCE_REPOSITORIES; структуру; карту архитектуры, технологий и зависимостей.

#### Feature inventory
<text>`n` = `2`</text>

Найти все функции; каталогизировать модули; выявить уникальное, дубли и неработающее; матрица требований; список того, что нельзя потерять.

#### Monorepo architecture
<text>`n` = `3`</text>

Сохранить имя shop-by-boo; подготовить структуру; границы трёх продуктов; общие библиотеки; API; БД; контракты; независимые сборки; план миграции и проверки сохранности.

#### Full audit
<text>`n` = `4`</text>

Backend; Frontend; Admin; Cabinet; Telegram; Payments; Remnawave; Android; iOS; Docker; Installer; Node Maintenance; Auto-selection; MASQUE; Security; CI/CD; Documentation; Screenshots; Tests; Licenses.

#### Migration
<text>`n` = `5`</text>

Переносить компоненты в shop-by-boo; проверить лицензии, зависимости, конфигурации, API, сборки, тесты, работу и документацию. Не удалять исходную реализацию до подтверждения переноса.

#### Fixes
<text>`n` = `6`</text>

Исправить подтверждённые ошибки и проверить, что функции не потеряны.

#### Products
<text>`n` = `7`</text>

Параллельно развивать VPN Client, VPN Shop и Lucy Admin. Не откладывать мобильные приложения, платежи, инфраструктуру и документацию.

#### Node operations
<text>`n` = `8`</text>

Реализовать операции установки, обслуживания и пула автовыбора; проверить на тестовых нодах.

#### Testing
<text>`n` = `9`</text>

Unit; integration; e2e; security; performance; Docker; installer; mobile; API; payments; node operations; backup/restore; visual screenshot coverage.

#### Docs and release
<text>`n` = `10`</text>

Обновить README, Wiki, документацию и отчёты. Подготовить релиз; публиковать только после проверки и в пределах прав.


### Acceptance Criteria

#### Criterion

Все целевые компоненты в одном shop-by-boo.

#### Criterion

Название репозитория не изменено.

#### Criterion

Уникальные функции исходных проектов сохранены или обоснованно отмечены как несовместимые/непереносимые.

#### Criterion

Дубли объединены без потери возможностей.

#### Criterion

Три продукта имеют чёткие границы.

#### Criterion

VPN Client работает как бесплатный универсальный клиент.

#### Criterion

VPN Shop работает как коммерческая платформа.

#### Criterion

Lucy Admin управляет экосистемой.

#### Criterion

Web/Android/iOS проходят проверку функциональной совместимости.

#### Criterion

Платёжные адаптеры имеют подтверждённые статусы.

#### Criterion

Remnawave интегрирован.

#### Criterion

MASQUE исследован по реальным возможностям движков.

#### Criterion

Установка и обслуживание нод проверены.

#### Criterion

Auto-selection проверен по всем алгоритмам.

#### Criterion

Backup/restore проверены.

#### Criterion

Installer и Docker работают.

#### Criterion

Известные ошибки исправлены.

#### Criterion

Telegram Bot и Mini App проверены.

#### Criterion

Документация обновлена на RU/EN/UK.

#### Criterion

Скриншоты покрывают необходимые экраны.

#### Criterion

Acceptance Checklist содержит доказательства.

#### Criterion

CI/CD работает.

#### Criterion

Безопасность проверена.

#### Criterion

Отчёты созданы.

#### Criterion

Внешние блокировки честно отражены.

#### Criterion

Неподтверждённые функции не объявлены готовыми.


### Non Loss Rule
<text>`priority` = `absolute`</text>

#### Rule

Не удалять ни одну ранее поставленную пользователем задачу.

#### Allowed

Объединять одинаковые задачи; устранять дублирование кода; объединять повторяющиеся требования, сохраняя критерии; уточнять формулировки; добавлять требования и проверки; улучшать архитектуру.

#### Forbidden

Удалять уникальные функции; исключать задачи; заменять конкретную задачу общей формулировкой, теряющей критерии; считать упоминание функции достаточным; объявлять задачу выполненной без доказательства; терять задачи при миграции; забывать известные ошибки; игнорировать скриншоты.

#### Reconciliation

Перед каждым крупным этапом сверять работу с AUTONOMOUS_ACCEPTANCE_CHECKLIST.md. Новые задачи добавлять. Дубликаты объединять только при сохранении всех исходных критериев и связей.


### Final Objective

Создать единую, полноценную, безопасную, автоматизированную и масштабируемую экосистему VPN Shop by Corgi Lucy в одном GitHub-репозитории shop-by-boo. Внутри: бесплатный универсальный VPN Client Android/iOS; коммерческий VPN Shop; User Cabinet; Telegram Bot; Telegram Mini App; Lucy Admin Web/Android/iOS; единый backend/API; Payment Orchestrator; Remnawave; VPN Node Manager; Node Provisioning; MASQUE; VLESS/REALITY; Hysteria 2; Auto-selection; Installer; Node Maintenance; Monitoring; Backup/Restore; Security; Docker; CI/CD; Documentation; Tests; Screenshot Coverage; Autonomous Audit. Все продукты равноправны. Сохранить и проверить все существующие функции; устранить дубли без потери возможностей; не потерять ни одной задачи. Не останавливаться на архитектуре: реализовать, протестировать, документировать и доказать работу каждого доступного компонента.

### Instruction To Claude

Полностью прочитай этот XML. Изучи целевой репозиторий и все источники. До изменений создай полный реестр требований с уникальными ID и трассировкой к XML-разделам. Не начинай миграцию без инвентаризации и плана сохранения функций. Не удаляй и не сокращай требования. Каждая задача в backlog должна ссылаться на исходный XML-раздел. При противоречии не удаляй ни одну задачу: зафиксируй конфликт, предложи безопасное разрешение и сохрани исходные требования. Работай автономно в пределах доступов; не обходи защиту; не заявляй результаты без доказательств.

### Completeness Supplement
<text>`version` = `3.0`</text>

#### Purpose

Дополнение к предыдущим разделам. Ничего из основного документа не отменяет и не заменяет. Все нижеследующие требования обязательны, должны получить отдельные IDs в общем acceptance checklist и трассировку к исходному разделу.

#### Autonomous Execution Strict

##### Rule

Все проверки, доступные в предоставленной среде, выполнять полностью автономно, без участия пользователя.

##### Rule

Не просить пользователя вручную запускать тесты, собирать логи или подтверждать рутинные безопасные действия, если это можно сделать доступными инструментами, CI, тестовым стендом или эмулятором.

##### Rule

Если требуется физическое устройство, закрытый аккаунт, production secret, платный внешний ресурс, Apple Developer entitlement или иное недоступное условие, выполнить максимально возможные автоматические проверки и точно обозначить BLOCKED_EXTERNAL/BLOCKED_SECRETS. Не подменять их фиктивным PASS.

##### Rule

Автоматически собирать evidence: логи, результаты команд, junit, screenshots, coverage, build artifacts, API traces с удалёнными секретами, версии и timestamps.

##### Rule

Для routine actions использовать автономный цикл. Для необратимых, финансовых, production и destructive действий действуют ограничения безопасности основного документа.


#### Repository Migration Expanded

##### Single Repository

Единственный целевой репозиторий: https://github.com/booarkz-cpu/shop-by-boo.git, имя shop-by-boo. Не создавать новые целевые репозитории. Ранее упомянутый lucy-vpn-android и другие репозитории — источники кода/истории для миграции в монорепозиторий.

##### Migration Inventory

###### Task

Зафиксировать исходные URL, default branch, commit SHA, теги, релизы, ветки и состояние каждого источника.

###### Task

Составить каталог всех экранов, API endpoints, фоновых задач, CLI-команд, скриптов, сервисов, конфигураций, миграций БД и пользовательских сценариев.

###### Task

Сопоставить одинаковые функции, определить каноническую реализацию, перечислить отличия и уникальные возможности каждой реализации.

###### Task

До удаления/замены дубликата доказать функциональную эквивалентность тестами и контрактами.

###### Task

Сохранить attribution, лицензии, copyright notices и обязательные файлы лицензий.

###### Task

Сохранить полезную историю изменений там, где это возможно и законно; не переписывать историю целевого репозитория.

###### Task

Проверить отсутствие секретов и персональных данных в переносимых commit, fixture, логах и артефактах.

###### Task

Создать отчёт mapping: source repository/path/commit → monorepo path → новая реализация → тесты → evidence.

###### Task

После миграции проверить отсутствие потерянных endpoints, экранов, команд бота, фоновых задач, конфигураций и пользовательских сценариев.



#### Vpn Shop Brand And Customer Content

##### Brand Name

Корги Люси — Свободный интернет без лишнего Гав.

##### Brand Variants

Корги Люси — «Свободный Гав!»; Корги Люси — Свободный интернет от Люси.

##### Tariff Copy

###### Max

Lucy Max: 2 устройства, безлимитный трафик.

###### Ultra

Lucy Ultra: 4 устройства, безлимитный трафик; показать очевидную выгоду относительно Max без изменения цены/условий без разрешения.

###### Mini

Lucy Mini — Test: 3 дня, 1 устройство, тестовый тариф.

###### Task

Подготовить описания каждого тарифа отдельно, единый сравнительный блок трёх тарифов и упрощённый текстовый вариант.


##### Service Descriptions

Подготовить русское и английское описание сервиса для .env и пользовательских интерфейсов.

##### Maintenance Message

Подготовить короткое уведомление о технических работах в фирменном стиле Lucy для .env/бота/кабинета.

##### Payment Copy

Текст для оплаты через YooKassa с упоминанием СБП и карт платёжной системы «Мир». Не упоминать Visa/Mastercard в данном тексте. Не заявлять методы, которые фактически не включены у мерчанта.

##### Visual Assets

###### Banner Size

1280×640 px, соотношение 2:1.

###### Format

JPEG, качество 90–95%, ориентир размера файла 200 KB, без прозрачности.

###### Layout

Текст не ближе 80 px от краёв; при необходимости уменьшить шрифт; проверить читаемость на мобильном экране.

###### Rule

Фирменные тексты и баннеры согласовать с брендингом. Не использовать ложные заявления о скорости, безопасности, доступности или безлимитности сверх фактических условий.



#### Server Maintenance Screenshot Acceptance

##### Note

Ниже зафиксированы требования, извлечённые из присланных пользователем скриншотов раздела «Установка». Они являются самостоятельными критериями приёмки.

##### Page Heading

«Обслуживание и защита» — поддержание сервера в рабочем состоянии и сохранение данных перед изменениями.

##### Intro Bullets

HTTPS и мониторинг; резервные копии; оптимизация и защита.

##### Server Context

Показывать, какой сервер выбран. Сертификаты, ускорение и защита должны настраиваться именно на выбранном сервере. У каждой операции отображать способ выполнения, например SSH, и реальный целевой сервер.

##### Cards

###### HTTPS для этой панели
<text>`id` = `panel-https`</text>

Перевод панели с http://IP:порт на HTTPS по домену. Установка на сервер панели. Если 443 занят нодой, selfsteal или другим web-сервером, предложить другой свободный порт; для ACME проверить требуемый свободный порт 80. Обнаружить конфликт, не перезаписывать чужой web server.

###### Статус-страница VPN
<text>`id` = `vpn-status-page`</text>

Публичная status page для клиентов; проверка каждого конфига реальным трафиком; online и latency; установка в один клик; собственный домен; безопасное публичное отображение без раскрытия внутренней информации.

###### Ускорение BBR / BBR3
<text>`id` = `bbr`</text>

Проверить ядро и виртуализацию до изменений; применить только поддерживаемую настройку TCP; не менять VPN-конфигурацию; показать фактический результат.

###### Настроить автобекапы
<text>`id` = `automatic-backups`</text>

Ежедневный дамп БД Remnawave (Postgres) плюс конфигурации, ротация, локальная копия и off-site копия в Telegram/поддерживаемом хранилище; расписание, журнал, уведомления и тест восстановления.

###### Снапшот сервера — скачать
<text>`id` = `snapshot-download`</text>

Архив дампа БД Remnawave и всех необходимых конфигураций; скачивание инициируется из панели на устройство пользователя; checksum, контроль доступа, срок хранения и безопасное удаление временного архива.

###### CrowdSec — защита от брутфорса
<text>`id` = `crowdsec`</text>

Установка CrowdSec; обнаружение brute force и сканеров SSH/web; community blocklist при соблюдении условий; bouncer; журнал, метрики, уведомления, защита от ложных блокировок.

###### HUBGuard — защита nftables
<text>`id` = `hubguard`</text>

Ограничение новых соединений на портах ноды; autoban сканеров и перебора; собственная таблица inet hubguard; не ломать ufw и CrowdSec; добавить SSH-адрес администратора и необходимые CGNAT-адреса в whitelist; не обрывать текущую сессию.


##### Danger Zone Exact

###### Remove Component

Снять с сервера ОДИН компонент (например, бот, ноду, status page, MTProto), не трогая остальные. Ясно объяснить, что это не полная очистка сервера.

###### Clean Server

Полностью удалить Remnawave, ноду, контейнеры и конфигурации. Необратимо. Требовать точный выбор сервера, перечень удаляемых ресурсов, проверку backup и повторное подтверждение.


##### Operation Ui

В карточке: категория/тип «Обслуживание сервера»; способ выполнения; иконка; заголовок; описание; кнопка «Установить»/«Скачать»; ход выполнения; журнал; результат; ошибка и диагностика. Кнопка должна вызывать реальную операцию и быть защищена от повторного нажатия.


#### Protocol Switch And Node Pool Screenshot Acceptance

##### Protocol Repair

###### Title

Починка блока: смена протокола

###### Stages

###### Stage

Чтение текущего транспорта.

###### Stage

Смена протокола inbound.

###### Stage

Обновление hosts.

###### Stage

Проверка реконнекта нод.


###### Example Observed State

В пользовательском интерфейсе отображался inbound STEAL-T12 в профиле узла; исходный транспорт gRPC, целевой xHTTP. Это пример диагностического сценария, а не фиксированное имя для всех серверов.

###### Stage Detail

Показать текущий профиль и inbound; прочитать фактический транспорт; обновить профиль Remnawave; инициировать корректное применение/перегенерацию конфигурации; обновить hosts; дождаться переподключения; проверить каждую ноду и итоговый транспорт.

###### Progress Ui

Общий статус; зелёные/ошибочные этапы; раскрываемый лог каждого этапа; временные метки; прогресс; ссылка «К списку»; возможность безопасного просмотра деталей.

###### Rollback

Сохранить старую конфигурацию и транспорт; при ошибке восстановить исходное состояние, если это безопасно; не оставлять часть нод на несовместимых параметрах.

###### Observed Result Example

В одном из показанных тестов обновился один hosts entry, а проверка сообщила об online-статусе 11 из 18 нод; это не считать универсальной нормой. Всегда показывать фактическое количество проверенных, online и offline нод.


##### Node Reconnect Matrix

Отображать порядковый номер; страну; название ноды; статус online/offline; транспорт; причину ошибки; время проверки. Проверять все ноды, а не только первые несколько.

##### Auto Selection Pool Ui

###### Heading

Пул автовыбора — «быстрейшая нода клиенту».

###### Actions

Сбросить шаблон; убрать плитку; включить leastPing; обновить пул.

###### Metrics

Видны в подписке X/Y; раздаются клиентам X/Y; у ноды есть открытая плитка; inbound входит в пул. Значения брать из реального состояния.

###### Mode

Отдельная плитка «Автовыбор» (новый режим) либо «Весь список» (старый режим). Обеспечить совместимость и не менять режим без явного действия администратора.

###### Algorithm Options

По задержке (leastPing); по нагрузке (leastLoad); по кругу (roundRobin); случайно (random).

###### Tile Name

Настраиваемое имя, пример «⚡ Автовыбор».

###### Hide Pool Nodes

Переключатель скрытия узлов пула из списка приложения. При включении клиенты видят только плитку; при выключении обычные узлы возвращаются после обновления подписки.

###### Client Compatibility Warning

В Clash/sing-box/Base64 и других форматах может отсутствовать поддержка настоящего балансировщика. В таком случае честно объяснить, что плитка может вести на первый узел пула; не заявлять полноценный клиентский балансировщик.

###### Explanation

Панельный автовыбор выбирает ноду на серверной стороне; «Автовыбор в приложении» выбирает клиент. Отдельная плитка означает, что клиент видит одну плитку «Автовыбор» плюс обычные ноды, если скрытие не включено.

###### Node Table

Чекбокс включения ноды в пул; флаг/страна; имя; статус online; признак «раздаётся»; число пользователей; доступность; задержка/нагрузка; последняя проверка.

###### Observed Example

В показанном интерфейсе было 11/11 видимых в подписке и 11/11 раздаваемых; пример пула включал Германию №1, Чехию №1 и Нидерланды №2. Эти числа и страны не являются константами — только динамические данные.

###### Retry

Повторный запуск обновляет пул по отмеченным галочкам; проверить идемпотентность и корректное сохранение настроек.



#### Network And Censorship Diagnostics

##### Rkn Context

Пользователь ранее описывал изменения фильтрации с 20.09.2026 и необходимость диагностировать адресные блокировки /32 и возможные блокировки подсетей /24. Проверять фактическую доступность из нескольких независимых сетей/регионов, SSH, ICMP, TCP и прохождение трафика; не делать вывод по одному ping.

##### Symptoms

Один IP может быть недоступен целиком; при других сценариях TCP может устанавливаться, но поток обрываться/дропаться после определённого объёма. Различать DNS, IP/route, TCP handshake, TLS, DPI/traffic filtering, firewall, MTU/MSS и проблемы самого узла.

##### Status Communications

Готовить уведомления клиентам только по подтверждённым данным. Если сервис не затронут — не заявлять о проблеме; техническое объяснение делать кратким и понятным. Не обещать обход любых блокировок.


#### Product And Service Reliability

##### Task

Проверить, что сервисы backend, admin, cabinet и bot, даже если Docker показывает UP, действительно отвечают по HTTP/API и выполняют пользовательские сценарии.

##### Task

Проверить все страницы админки и кабинета: проблема «чёрных страниц» и недоступных модулей ранее уже сообщалась.

##### Task

Проверить Telegram Bot отдельно от статуса контейнера: webhook/polling, токен в окружении без его вывода, команды, callback, платежные сценарии и доступность Telegram API.

##### Task

Проверить, что все ссылки на мобильные приложения в README ведут на реальные релизы/артефакты, а не на несуществующие файлы.

##### Task

Подготовить пошаговые инструкции для установки на тестовый VDS и управления с Android через Termux.

##### Task

Подготовить пошаговую инструкцию, как проверить git config user.name и user.email, в том числе с Android/Termux; не публиковать личный email без необходимости.

##### Task

Подготовить подробную инструкцию создания/включения GitHub Wiki и диагностики, если Wiki не открывается.

##### Task

Обновить README с мобильными ссылками, установкой, обновлением и восстановлением.


#### Expanded Test Matrix

##### Payments

Автоматические sandbox-сценарии для каждого доступного провайдера; positive/negative; duplicate webhook; invalid signature; wrong amount/currency/order; timeout; provider unavailable; retry; refund simulation; reconciliation; recurring renewal; notification retry; expired invoice; transaction replay; provider failover. Production tests только с разрешённым тестовым контуром и без несанкционированного списания.

##### Remnawave

Создание/изменение/удаление тестового пользователя; выдача и продление подписки; смена тарифа; лимит устройств; лимит трафика; expiry; отключённая нода; API timeout; повтор запроса; рассинхронизация; backup/restore; журнал.

##### Node Ops

Для каждой серверной операции: dry-run; совместимость; порт занят/свободен; SSH недоступен; sudo отсутствует; диск заполнен; DNS ошибка; ACME failure; частичная установка; повторный запуск; rollback; удаление только компонента; восстановление.

##### Auto Select

Проверить алгоритмы leastPing/leastLoad/roundRobin/random на детерминированных тестовых данных; равные метрики; устаревшие метрики; нода offline; все ноды offline; смена состава; скрытие; возвращение; подписка; разные клиентские форматы.

##### Mobile

Android lifecycle; разрешения; VPNService; сеть Wi-Fi/mobile switching; reconnect; sleep/wake; low battery; PIN; biometric unavailable; biometric cancelled; lock/unlock; обновление подписки; импорт повреждённого профиля; несколько профилей; split tunneling; app crash recovery.

##### Ui

Каждый экран desktop/mobile; все кнопки; формы; empty state; loading; error; success; permissions; RBAC; pagination; filters; dialogs; keyboard; safe areas; accessibility.


#### Expanded State Requirements

##### Requirement

Создать общий реестр требований, где у каждой задачи есть уникальный ID, дословная/смысловая исходная формулировка, источник (сообщение/скриншот/репозиторий/раздел XML), целевой продукт, модуль, критерии приёмки, зависимости, статус, evidence и история изменения.

##### Requirement

Не помечать задачу закрытой только потому, что создана документация, UI-кнопка или заглушка.

##### Requirement

Разделять IMPLEMENTED, BUILT, TESTED, VERIFIED и PRODUCTION_VERIFIED — это разные состояния.

##### Requirement

Для каждой функции фиксировать, на какой платформе она работает: Web, Android, iOS, Telegram Bot, Mini App, backend/API, server/node.

##### Requirement

При объединении дублей сохранять связи всех исходных task IDs с одной канонической задачей; не терять историю и критерии.

##### Requirement

В отчёте показывать процент покрытия требований и отдельный список требований без подтверждённого статуса.



## Часть II. Дополнительные требования из доступной истории переписки

> Эти пункты дополняют исходный XML и не заменяют его. Если конкретная формулировка ранее встречалась только в сводке или неполной истории, Claude должен найти её точный оригинал в доступном чате, issue, PR, исходнике или скриншоте. Не придумывать содержание отсутствующих пунктов.

### II.1. Дополнительные технические ошибки и проверки
- Проверить ранее упомянутую ошибку Python `ImportError: cannot import AsyncSessionLocal from app.db`; сообщение предлагало `SessionLocal`, но сначала изучить реальный session factory и импорты.
- Исправить JavaScript `Cannot read properties of undefined (reading 'trim')`.
- Исправить `(s || []).map is not a function`.
- Проверить ошибку установщика `ERROR: installation failed at line 427`.
- Проверить `docker compose config`, volumes, networks, ports, healthchecks, статусы backend/admin/cabinet/bot и реальные пользовательские сценарии, а не только состояние контейнеров.
- Проверить недоступные страницы и чёрные экраны админки и кабинета; проверить Telegram Bot end-to-end.

### II.2. Дополнительные серверные операции, которые нельзя потерять
- swap и sysctl;
- HTTPS ports;
- миграция домена и SNI;
- ремонт заблокированного узла;
- каскадирование HAProxy на 2–3 узла;
- CDN diagnostics;
- MTProto Proxy;
- GEO, geoip.dat и geosite.dat с checksum и rollback;
- Xray AdBlock и AdGuard Home;
- RKN diagnostics: 443, selfsteal, 80/301, TLS 1.2/1.3, HSTS, Trojan, VLESS/Vision;
- MSS clamp и MTU;
- ограничение SSH доступа к панели с безопасным rollback;
- временная блокировка torrent IP через nftables/iptables;
- CrowdSec, HUBGuard, nftables, backup snapshots;
- безопасное удаление отдельного компонента и отдельный сценарий полной очистки сервера;
- реальный тест трафика через клиентскую подписку.

### II.3. Автовыбор узлов — уточнения из скриншотов/описаний
- Пул должен показывать число узлов в подписке и пуле, доступные/выдаваемые, online/offline, исключённые, последнюю проверку и актуальность метрик.
- Плитка имеет имя, иконку, алгоритм, список узлов, видимость и состояние; пример имени — `⚡ Автовыбор`.
- При недоступности выбранной ноды выполнить fallback на доступную, не выдавать недействительную конфигурацию, записать событие.
- Проверить все алгоритмы: leastPing, leastLoad, roundRobin, random; отключение узла; изменение метрик; обновление подписки; скрытие/возврат; удаление плитки; переименование; отсутствие доступных узлов; совместимость форматов; reconnect и fallback.
- Если формат клиента не поддерживает настоящий балансировщик, честно показать ограничение; не выдавать первую ноду за полноценный балансировщик.

### II.4. Бренд и контент
- Название и стиль: «Корги Люси — Свободный интернет без лишнего Гав», «Корги Люси — Свободный Гав!», «Корги Люси — Свободный интернет от Люси».
- Слоган: «Твой интернет. Твои правила. Твоя Люси».
- Lucy Max: 2 устройства, безлимитный трафик; Lucy Ultra: 4 устройства, безлимитный трафик, выгоднее Max; Lucy Mini — Test: 3 дня, 1 устройство.
- Отдельные описания тарифов, единый тарифный блок и простой plain-text вариант; Ultra визуально выгоднее.
- Короткое сообщение о технических работах для `.env` в стиле Люси; описание сервиса в `.env` на русском и английском.
- Для YooKassa упоминать СБП и «Мир», не упоминать Visa/Mastercard в текстах, как просил пользователь, при условии фактической доступности метода.
- Telegram promo banner: 1280×640 px, 2:1, JPEG quality 90–95%, ориентир 200 KB, без прозрачности, текст отступает 80 px от краёв, уменьшенный шрифт.

### II.5. VPS, Termux, GitHub и документация
- Пошаговая установка на тестовый VDS.
- Пошаговая установка/управление через Android Termux.
- Инструкция по `git config user.name` и `git config user.email`, включая Android.
- Полный README с мобильными ссылками, установкой, обновлением и восстановлением.
- GitHub Wiki на русском, английском и украинском; инструкции включения/создания и диагностики.
- Обновить README, LICENSE, документацию, выпустить релиз и проверить ветки; удалять ветки только безопасно и с разрешением.
- Ночные GitHub Actions для аудита/обновлений только при наличии реального runner; не обещать непрерывную работу без runner.

### II.6. Восстановление недоступных task groups
В прежних запросах упоминались группы `A0–F`, `N1–N13`, `O1–O14`, а также `N7`, `N10`, `N11`, `N12` и этапы `1–20`. Доступная копия исходного промпта содержит часть инфраструктурных пунктов и ссылку на эти группы, но не содержит их полных исходных формулировок в раскрытом виде. Claude обязан искать точный текст в полной истории, backlog, документации, issues, PR, исходных XML/MD и скриншотах. Не выдумывать задачи по одним названиям групп. Каждую найденную задачу добавить в общий реестр с оригинальным ID и критериями.

### II.7. Обязательные проектные принципы
- Все три продукта равноправны по ценности.
- Один целевой монорепозиторий `shop-by-boo`, но чёткое разделение бизнес-доменов и независимые сборки/развёртывания.
- Общие библиотеки допустимы; не сливать бизнес-данные трёх продуктов в одну неразделённую модель.
- Весь доступный аудит/тестирование выполнять автономно, не просить пользователя запускать то, что можно сделать самому.
- PR → зелёный CI → review → squash merge, если политика репозитория это допускает; не обходить защиту.
- Не использовать mocks для выдачи ложного статуса готовности; тестовые mocks допустимы только как явно обозначенные тестовые двойники.
- Все отчёты пользователю — на русском.
- Ни одного фиктивного PASS, ложного production-ready или несуществующего релиза.

## Часть III. Неизменяемый оригинал XML (для точной сверки)

Ниже помещён исходный XML целиком без изменений. Он сохранён как приложение для Claude и как контрольный источник, чтобы при преобразовании в Markdown не потерять вложенные детали, атрибуты и формулировки.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<claude_master_prompt version="2.0" language="ru" project="VPN Shop by Corgi Lucy"
 target_repository="https://github.com/booarkz-cpu/shop-by-boo.git">
<document_purpose>Полный мастер-промпт Claude AI. Все задачи, требования и критерии сохраняются. Разрешено добавлять и объединять дубли только без потери уникальных требований.</document_purpose>
<critical_rule>Единственный целевой репозиторий всей экосистемы — shop-by-boo. Название не менять. Не создавать отдельные целевые репозитории для приложений, сервисов, API, мобильных клиентов, админки, платежей, инфраструктуры, документации или тестов. Всё находится в одном монорепозитории, но сохраняет логические границы, независимые сборки и возможность независимого развёртывания сервисов.</critical_rule>
<role>Действуй как автономная команда Principal Architect, Senior/Staff Engineers, DevOps, Security, QA, Mobile и Product Engineering. Не ограничивайся планом: анализируй, реализуй, тестируй, документируй и доказывай результат. Не заявляй о выполнении без доказательств. Не повторяй вопросы, ответы на которые уже есть в исходниках.</role>
<primary_repository>https://github.com/booarkz-cpu/shop-by-boo.git</primary_repository>
<source_repositories>
<repo>https://github.com/booarkz-cpu/VPN-Shop-by-CorgiLusi.git</repo>
<repo>https://github.com/booarkz-cpu/remnawave-manager</repo>
<repo>https://github.com/eGamesAPI/remnawave-reverse-proxy</repo>
<repo>https://github.com/Case211/remnawave-admin</repo>
<repo>https://github.com/BEDOLAGA-DEV/remnawave-bedolaga-telegram-bot</repo>
<repo>https://github.com/BEDOLAGA-DEV/bedolaga-cabinet</repo>
<repo>https://github.com/STEP-CORP/StepBot/tree/main</repo>
<repo>https://github.com/booarkz-cpu/lucy-vpn-android</repo>
<mandatory_read>docs/CODE_REUSE_REGISTER.md</mandatory_read>
<mandatory_read>docs/REFERENCE_REPOSITORIES.md</mandatory_read>
<rule>Исходные репозитории — источники аудита и миграции, а не отдельные целевые репозитории. Проверить лицензии, авторские права, историю, зависимости и происхождение кода. Не удалять исходные репозитории и ветки. Составить карту компонентов, API, уникальных и дублирующихся функций, ошибок, плана миграции и результатов тестов.</rule>
</source_repositories>
<monorepo>
<apps>vpn-client/android; vpn-client/ios; vpn-shop; user-cabinet; telegram-bot; telegram-mini-app; lucy-admin/web; lucy-admin/android; lucy-admin/ios; status-page.</apps>
<services>api; authentication; payment-orchestrator; subscription-manager; remnawave-integration; node-manager; node-provisioning; auto-selection; masque; notification-service; support.</services>
<packages>shared-ui; shared-api; shared-types; shared-config; localization; payment-contracts; security; testing.</packages>
<infrastructure>docker; installer; provisioning; vpn-nodes; reverse-proxy; monitoring; security; backup; deployment.</infrastructure>
<other>database/migrations; database/schemas; database/seeds; scripts/audit; scripts/build; scripts/migration; scripts/release; scripts/maintenance; tests/unit; tests/integration; tests/e2e; tests/security; tests/mobile; tests/infrastructure; docs/ru; docs/en; docs/uk; docs/architecture; docs/payments; docs/remnawave; docs/masque; docs/installation; docs/security; docs/screenshots; artifacts/audit; artifacts/builds; artifacts/screenshots; artifacts/reports; .github/workflows.</other>
<rule>Адаптируй структуру к фактическому стеку, не создавай фиктивных пустых модулей и не теряй самостоятельность сборок.</rule>
</monorepo>

<products equal_priority="true">
<product id="vpn-client" name="Корги Люси: Клиент">
<purpose>Полностью бесплатный универсальный VPN-клиент Android/iOS для совместимых сторонних VPN-подписок. Не зависит от коммерческого backend VPN Shop, не требует обязательной регистрации или покупки.</purpose>
<imports>URL; QR; файл; буфер обмена; ручное добавление; несколько подписок; обновление; редактирование; удаление; экспорт; диагностика конфигурации; проверка доступности серверов.</imports>
<protocols>VLESS; REALITY; Trojan; Shadowsocks; VMess; Hysteria 2; TUIC; MASQUE и другие — только если подтверждены движком и платформой.</protocols>
<features>Split Tunneling; Smart Routing; Live Traffic; LAN Proxy Share; Self-Healing; Battery Saver; Pet the Corgi; Haptic Feedback; авто-выбор сервера; проверка задержки; уведомления; PIN; биометрия; диагностика; профили; импорт/экспорт; восстановление подключения.</features>
<branding><banner>Свободный Гав в интернете!</banner><slogan>Твой интернет. Твои правила. Твоя Люси</slogan><style>Тёмная/космическая градиентная концепция; маскот корги; список серверов; цветной статус; задержка XX ms; SVG Add; заметные переключатели.</style><remove>Лишние счётчики дней; декоративный огонёк; баннер «ЗАЩИТА В ОДНО КАСАНИЕ»; маска; кнопка «Безлимит».</remove></branding>
<critical_bug>Приложение может падать при включении PIN/биометрии из настроек подключения. Получить Logcat/stack trace; найти первопричину; проверить Activity/Service lifecycle, VPNService, блокировку UI, разрешения и состояние подключения; исправить; блокировка UI не должна завершать VPNService или сессию; проверить минимум 15 сценариев.</critical_bug>
</product>
<product id="vpn-shop" name="VPN Shop by Corgi Lucy">
<scope>Backend; API; Telegram Bot; Telegram Mini App; кабинет; регистрация; авторизация; тарифы; подписки; платежи; Remnawave; VPN-ноды; статистика; пользователи; уведомления; поддержка; аналитика; автоматизация.</scope>
<tariff name="Lucy Max" devices="2" traffic="unlimited"/>
<tariff name="Lucy Ultra" devices="4" traffic="unlimited">Визуально и коммерчески выгоднее Lucy Max.</tariff>
<tariff name="Lucy Mini — Test" duration="3 days" devices="1">Для тестирования сервиса.</tariff>
<rule>Не менять цены и коммерческие условия без обоснования и разрешения.</rule>
<authentication>Email; VK; Yandex — если безопасно и технически подтверждено.</authentication>
<telegram>Проверить и исправить ранее сообщавшуюся проблему неработающего Telegram Bot. Проверить команды, меню, регистрацию, покупку, продление, оплату, выдачу подписки, уведомления, поддержку, Mini App, webhook, ошибки и восстановление после перезапуска.</telegram>
</product>
<product id="lucy-admin" name="Lucy Admin">
<interfaces>Web Admin; Android Admin; iOS Admin; единый API; RBAC; аудит.</interfaces>
<modules>Dashboard; Users; Roles; Tariffs; Subscriptions; Payments; Payment Providers; Remnawave; VPN Nodes; Node Provisioning; MASQUE; VLESS/REALITY; Hysteria 2; Server Monitoring; Network Monitoring; Telegram Bot; Telegram Mini App; User Cabinet; VPN Client Management; Commercial App Management; Android Builds; iOS Builds; GitHub; CI/CD; Pull Requests; Releases; Docker; Installer; Database; Backup/Restore/Rollback; Updates; Security Center; Audit Logs; API Management; Notifications; Support; Localization; Documentation; System Settings; Automation Center; Autonomous Audit; Checklist Dashboard; Screenshot Coverage; Admin Feature Parity; Payment Testing; Protocol Compatibility; Infrastructure Diagnostics; Node Installation and Maintenance; Auto-selection Management; Subscription Status Page; Server Protection; Dangerous Operations; Repair and Recovery; Migration Tools.</modules>
<parity_document>docs/ADMIN_FEATURE_PARITY_MATRIX.md</parity_document>
<parity_fields>Web; Android; iOS; API; статус; функциональность; тесты; ограничения; evidence.</parity_fields>
<rule>Ни одна кнопка не должна быть декоративной или фиктивной.</rule>
</product>
</products>

<full_audit>
<scope>Архитектура; backend; frontend; API; мобильные приложения; БД; миграции; Telegram; платежи; Remnawave; Docker; installer; инфраструктура; безопасность; CI/CD; документация; лицензии; тесты; зависимости; конфигурации; производительность.</scope>
<find>Критические ошибки; уязвимости; неработающие функции; чёрные/пустые страницы; недоступные модули; фиктивные кнопки; неиспользуемый код; дублирующиеся сервисы/API; конфликтующие схемы БД; несовместимые библиотеки; ошибки сборки и развёртывания.</find>
<known_error>ERROR: installation failed at line 427</known_error>
<known_error>ImportError: cannot import AsyncSessionLocal from app.db; suggested SessionLocal</known_error>
<known_error>Cannot read properties of undefined (reading 'trim')</known_error>
<known_error>(s || []).map is not a function</known_error>
<docker_checks>Dockerfile; Compose; volumes; networks; ports; health checks; restart policies; dependencies; environment; secrets; database; migrations; logs; доступность сервисов.</docker_checks>
<rule>Устранять первопричины, а не только симптомы.</rule>
</full_audit>

<payment_ecosystem>
<priority>Обязательная часть реализации, не отложенный backlog.</priority>
<architecture>Provider Registry; Adapter Interface; Capabilities Registry; Method Registry; Router; Priority Queue; Health Monitor; Circuit Breaker; Payment API; Webhook Router; Signature Validator; State Machine; Idempotency; Transaction Registry; Order Registry; Reconciliation; Refund Service; Recurring Payments; Risk Assessment; Chargeback Management; Tax/Fiscalization; Analytics; Audit Log.</architecture>
<providers>Telegram Stars; Tribute; CryptoBot; Heleket; YooKassa; MulenPay; Pal24; Platega; WATA; FreeKassa; FreeKassa SBP; FreeKassa Card; CloudPayments; Kassa AI; RioPay; SeverPay; RollyPay; Overpay; AuraPay; Etoplatezhi; Antilopay; Jupiter; Donut; Lava; CisPay; Anore; TabPay; ParityPay; Cashera; Stripe; PayPal; Apple StoreKit; Google Play Billing; Crypto Gateway; Sandbox.</providers>
<configuration_ids>telegram_stars; tribute; cryptobot; heleket; yookassa; mulenpay; pal24; platega; wata; freekassa; freekassa_sbp; freekassa_card; cloudpayments; kassa_ai; riopay; severpay; rollypay; overpay; aurapay; etoplatezhi; antilopay; jupiter; donut; lava; cispay; anore; tabpay; paritypay; cashera.</configuration_ids>
<classification>Не путать провайдера, метод оплаты, конфигурационный ID, платформенный платёж и sandbox. Наличие адаптера/ID не означает работоспособность.</classification>
<methods>Банковские карты; СБП; QR СБП; SberPay; YooMoney; криптовалюта; встроенные методы платформ; иные методы только при подтверждении API.</methods>
<known_capabilities>
<provider name="YooKassa">card; sbp</provider><provider name="Pal24">sbp; card</provider>
<provider name="Platega">Динамические методы — проверить.</provider><provider name="FreeKassa">sbp; card</provider>
<provider name="Kassa AI">sbp; card; sberpay</provider><provider name="RollyPay">sbp; card; crypto</provider>
<provider name="Overpay">Динамические методы — проверить.</provider><provider name="AuraPay">card; sbp</provider>
<provider name="Etoplatezhi">card; sbp</provider><provider name="Antilopay">card; sbp; sberpay</provider>
<provider name="Jupiter">sbp</provider><provider name="Donut">card; sbp; sbp_qr</provider>
<provider name="Lava">card; sbp</provider><provider name="CisPay">card; sbp; crypto</provider>
<provider name="Anore">sbp; card; yoomoney; crypto</provider><provider name="TabPay">card; sbp</provider>
<provider name="ParityPay">card; sbp</provider><provider name="Cashera">Динамические методы — проверить.</provider>
<provider name="CloudPayments">Проверить выбор метода на странице провайдера.</provider>
</known_capabilities>
<verify>Для Telegram Stars, Tribute, CryptoBot, Heleket, MulenPay, WATA, RioPay, SeverPay проверить адаптеры и официальные возможности. Не выдумывать методы. Mir Pay, T-Pay, Alfa Pay исследовать только при подтверждённой технической возможности.</verify>
<statuses>IMPLEMENTED; CONFIGURED; SANDBOX_VERIFIED; PRODUCTION_VERIFIED; BLOCKED_SECRETS; BLOCKED_PROVIDER; NOT_SUPPORTED; RETIRED.</statuses>
<scenarios>Покупка; продление; автопродление; возврат; частичный возврат; повторная оплата; отмена; истечение; неуспешная оплата; сверка; chargeback; повторная проверка статуса; webhook; проверка суммы/валюты/заказа; защита от повторной обработки; восстановление; failover; sandbox; финансовый журнал; аналитика.</scenarios>
<platforms>Apple StoreKit и Google Play Billing: серверная проверка транзакций, статусы, отмены, истечения, восстановление. Telegram Stars: invoice, pre-checkout, successful_payment. Tribute: проверить фактические механизмы.</platforms>
<security>Подписи webhook; replay protection; idempotency; проверка суммы, валюты, заказа; защита от подмены статуса; проверка через API провайдера; журнал; защита секретов; RBAC.</security>
<docs>docs/PAYMENT_PROVIDER_INVENTORY.md; docs/PAYMENT_METHODS_MATRIX.md; docs/PAYMENT_CAPABILITIES_MATRIX.md; docs/PAYMENT_TESTING.md; docs/PAYMENT_SECURITY_REPORT.md; docs/PAYMENT_RECONCILIATION.md; docs/PAYMENT_PROVIDER_ONBOARDING.md.</docs>
<audit_scripts>scripts/audit/check_payments.py; check_payment_provider_registry.py; check_payment_capabilities.py; check_payment_webhooks.py; check_payment_methods_ui.py; check_payment_contracts.py; check_payment_reconciliation.py.</audit_scripts>
<rule>Не выполнять реальные платежи/возвраты без разрешения. Не выдумывать production secrets.</rule>
</payment_ecosystem>

<remnawave>
<goal>Полная интеграция Remnawave в экосистему и Lucy Admin.</goal>
<capabilities>Пользователи; подписки; тарифы; устройства; трафик; сроки; ноды; конфигурации; статусы; подключения; статистика; блокировки; продление; выдача подписок.</capabilities>
<requirements>Проверить реальные API, модели, ограничения и версии; синхронизация; обработка ошибок; повторы; журнал; мониторинг; восстановление; контроль панели; миграция; backup. Продажа подписок через Remnawave через единый backend и платежи.</requirements>
</remnawave>

<masque>
<goal>Максимально автоматизированный Zero-Touch Provisioning MASQUE.</goal>
<version_claim>Xray-core v26.10.10+</version_claim>
<verification>Проверить существование версии и реальную поддержку MASQUE по официальным источникам. Не утверждать поддержку без подтверждения.</verification>
<node_provisioning>Python/Next.js; Bash; SSH; Docker; установка на чистую ноду; проверка портов; ACME/Let's Encrypt; TLS; безопасная передача сертификатов и ключей.</node_provisioning>
<multiplexing>Исследовать MASQUE HTTP/3 UDP; MASQUE HTTP/2 TCP; Hysteria 2 UDP; VLESS+REALITY TCP/UDP; конфликты 443; разные порты; ALPN; SNI; routing; listener; reverse proxy; ограничения REALITY; QUIC/TCP. Подготовить проверенные inbounds/routing.</multiplexing>
<grpc>Проверить HandlerService, AddInbound, StatsService и необходимые методы. Реализовать hot reload без неоправданного прерывания соединений, точную статистику и синхронизацию лимитов.</grpc>
<subscriptions>VLESS Reality; Hysteria 2; MASQUE; JSON/Base64 bundle; v2rayNG; NekoBox. Неподдерживаемый MASQUE не должен ломать остальные конфигурации.</subscriptions>
<admin_ui>Переключатели MASQUE; проверка совместимости; скрытие дублирующих настроек; fallback domain; мониторинг установки; прогресс; диагностика.</admin_ui>
<anti_dpi>Исследовать unauthorized requests; probing; fallback; легитимный веб-сервер; ограничения защиты. Не обещать гарантированную защиту от DPI.</anti_dpi>
<alternative_engine>Если Xray не поддерживает нужное, исследовать sing-box и другие движки.</alternative_engine>
<deliverables>Архитектура; официальное подтверждение; код; конфигурации; тесты; ограничения; безопасность; документация.</deliverables>
<report>docs/MASQUE_IMPLEMENTATION_REPORT.md</report>
</masque>

<node_manager>
<features>Добавление; удаление; изменение параметров; доступность; SSH; управление сервисами; мониторинг; диагностика; установка; обновление; восстановление; backup; проверка конфигураций; безопасность.</features>
<bulk>Массовые операции показывают выбранные ноды, компоненты, последствия, rollback и backup до выполнения.</bulk>
</node_manager>

<server_installation_maintenance>
<rule>Восстановить и полноценно реализовать функциональность «Установка» и «Обслуживание и защита», показанную на скриншотах. Скриншоты — требования, не доказательство реализации. Проверить исходный код; отсутствующее реализовать; существующее проверить.</rule>
<catalog>Каталог карточек: название; описание; категория; тип подключения; целевые ноды; требования; кнопка; прогресс; результат; журнал; диагностика.</catalog>
<mtproto>Установка MTProto Proxy на выбранную ноду; автоматическая настройка; корректная ссылка; показ ссылки; проверка доступности; журнал; удаление без влияния на другие сервисы.</mtproto>
<haproxy_cascade>Каскад HAProxy через 2–3 ноды; выбор транзитных и конечной; настройка маршрута; проверка каждого звена и TCP; диагностика; без ненужного второго шифрования; безопасное применение; rollback.</haproxy_cascade>
<live_traffic_test>Проверка реальным трафиком через подписку живого клиента; тестовый запрос; фактический маршрут и внешний адрес; результат; журнал; диагностика DNS, маршрутизации и подключения. Не подменять статической проверкой.</live_traffic_test>
<geoassets>Обновление geoip.dat, geosite.dat и других GeoAssets; версия; источник; целостность; checksum; хранение; backup; применение; проверка конфигурации; минимальный перезапуск; rollback. Для нод без Docker Compose — безопасный поддерживаемый способ. Ориентир около 10 секунд только измерять, не гарантировать.</geoassets>
<xray_adblock>Отдельная блокировка рекламы/трекеров через DNS/geosite и подтверждённые возможности Xray; выбор нод; пользовательские домены; проверка DNS; rollback.</xray_adblock>
<adguard_home>Отдельная установка AdGuard Home; выбор нод; DNS; интеграция с Xray; списки; статистика; мониторинг; резервный DNS; диагностика; учитывать ресурсы. Не устанавливать конкурирующие механизмы без проверки.</adguard_home>
<rkn_diagnostics>Проверка 443; selfsteal; порт 80; редирект 301; TLS 1.2/1.3; HSTS; заглушка; Trojan; VLESS; Vision; открытые порты; доступность панели. Исправления безопасные и обратимые; не закрывать админ-доступ; не обещать невозможность блокировки.</rkn_diagnostics>
<mss_clamp>Проверка MTU/MSS; маршруты до Cloudflare, Яндекс DNS и контрольных адресов; расчёт; необходимость; применение; сохранение после reboot; проверка соединений; не перезапускать VPN без нужды.</mss_clamp>
<panel_node_access>SSH-порт; доступ только с IP панели; массовое применение; миграция панели; предварительное добавление нового IP; проверка доступности; автоматическая отмена правила при потере доступа; не блокировать SSH администратора.</panel_node_access>
<torrent_blocker>Обнаружение BitTorrent в логах Xray; временный бан IP; nftables/iptables; правила; журнал; автоматическое снятие; диагностика; предупреждение о влиянии на общие ноды; до перезапуска Xray показать последствия.</torrent_blocker>
<panel_https>HTTPS по домену; ACME; Let's Encrypt; DNS; сертификат; продление; срок; reverse proxy; доступность. При конфликте 443 обнаружить и предложить порт; проверить 80 для ACME; не перезаписывать чужую конфигурацию.</panel_https>
<status_page>Публичная статус-страница; реальная доступность нод; тестовый трафик; online/latency; инциденты; состояние сервисов; домен; не раскрывать секреты и внутренние адреса. TCP-порт сам по себе не доказывает работоспособность.</status_page>
<bbr>Определить ядро Linux, версию, виртуализацию, congestion control, права и совместимость; включать только поддерживаемый BBR/BBR3; проверить результат и rollback.</bbr>
<backups>Ежедневные backup PostgreSQL Remnawave, конфигураций, необходимых файлов, метаданных и инфраструктуры; расписание; ротация; размер; шифрование; целостность; off-site; Telegram-уведомления; журнал; тест восстановления; срок хранения. Не хранить секреты в открытых архивах.</backups>
<snapshot_download>Экспорт дампа БД Remnawave, конфигураций и метаданных; защищённое скачивание на устройство; права; checksum; временное хранение; журнал; предупреждение о конфиденциальности.</snapshot_download>
<crowdsec>Установка; защита SSH/web от brute force; обнаружение сканирования; community blocklists при соблюдении условий; мониторинг; журнал; уведомления; firewall bouncer; снятие ложных блокировок.</crowdsec>
<hubguard>Защита nftables; ограничение новых соединений; защита от сканирования и перебора; отдельная таблица; не ломать ufw/CrowdSec; whitelist SSH и необходимого CGNAT; сохранять действующие сессии; проверить доступность панели; rollback.</hubguard>
<danger_zone>
<remove_component>Удалять только выбранный компонент: бот, ноду, status page, MTProto или другой модуль. Не затрагивать остальные сервисы.</remove_component>
<clean_server>Полное удаление Remnawave, нод, контейнеров, конфигураций и связанных компонентов. Необратимая операция: повторное подтверждение; точный сервер; список ресурсов; проверка backup; журнал; проверка полномочий.</clean_server>
<rule>Не путать удаление одного компонента с полной очисткой сервера.</rule>
</danger_zone>
<protocol_switch_repair>Последовательные этапы: чтение текущего транспорта; смена протокола inbound; обновление hosts; проверка реконнекта нод. Каждый этап показывает состояние, индикатор, журнал, ошибку, результат, время, диагностику. Определить inbound/profile; обновить и применить; обновить hosts; дождаться реконнекта; проверить все ноды; сохранить старый и новый транспорт. Не объявлять успех до проверок.</protocol_switch_repair>
<node_reconnect>После смены протокола/массовой операции проверить все ноды: номер; страна; имя; online/offline; транспорт; время; ошибка; итог. Проверять не только SSH, но и реальный VPN-транспорт.</node_reconnect>
<common_acceptance>Для каждой операции: предварительная проверка; выбор серверов; совместимость; свободные порты и ресурсы; backup; план; последствия; прогресс; журнал; проверка результата; rollback; документация. Не допускать фиктивных кнопок.</common_acceptance>
</server_installation_maintenance>

<auto_selection>
<purpose>Полноценный пул автовыбора VPN-ноды.</purpose>
<modes><mode id="server-side">Панель/сервер выбирает ноду и формирует подписку или отдельную плитку.</mode><mode id="client-side">Ноду выбирает сам VPN-клиент.</mode><rule>Не смешивать серверный и клиентский автовыбор.</rule></modes>
<delivery><mode id="separate-tile">Отдельная плитка «Автовыбор»; обычные ноды могут отображаться отдельно.</mode><mode id="all-list">Старый режим «Весь список»; балансировка только при поддержке формата.</mode></delivery>
<algorithms><algorithm id="leastPing">По минимальной задержке.</algorithm><algorithm id="leastLoad">По минимальной нагрузке.</algorithm><algorithm id="roundRobin">По кругу.</algorithm><algorithm id="random">Случайно.</algorithm><rule>Для каждого алгоритма определить входные данные, выбор, недоступность, обновление метрик, равные значения и fallback.</rule></algorithms>
<management>Включение; отключение; обновление; сброс шаблона; удаление плитки; имя; алгоритм; выбор нод; массовое включение/исключение; скрытие; состав; доступность.</management>
<hide_nodes>Опция «Скрыть узлы пула из списка приложения»: при включении клиент видит только плитку «Автовыбор»; при выключении узлы возвращаются после обновления подписки. Проверить Clash, sing-box, Base64 и другие клиенты. Если формат не поддерживает настоящий балансировщик, показать ограничение; не выдавать первую ноду за балансировщик.</hide_nodes>
<statistics>Количество нод в подписке и пуле; доступные; выдаваемые; online/offline; исключённые; последняя проверка; актуальность метрик. Только реальные данные.</statistics>
<tile>Имя; иконка; алгоритм; ноды; видимость; состояние; отображение клиенту. Пример: ⚡ Автовыбор.</tile>
<failure>При недоступности выбранной ноды выбрать доступную; fallback; не выдавать недействительную конфигурацию; записать событие; обновить состояние.</failure>
<tests>Все четыре алгоритма; отключение ноды; изменение нагрузки/задержки; обновление подписки; скрытие/возврат; удаление плитки; изменение имени; отсутствие доступных нод; совместимость форматов; реконнект; fallback.</tests>
<documentation>docs/AUTO_SELECTION.md</documentation>
</auto_selection>

<additional_infrastructure>
<items>swap; sysctl; HTTPS ports; auto-select; domain migration; SNI; repair blocked node; cascade; CDN diagnostics; MTProto; GEO; backup snapshots; CrowdSec; nftables; torrent-blocker; MSS clamp; anti-censorship; AdBlock; AdGuard; safe component removal.</items>
<groups>O1–O14; N7; N10; N11; N12.</groups>
<rule>Найти точные исходные формулировки этих задач в backlog, документации, issues, исходных промптах и истории. Не угадывать содержание. Создать реестр с критериями, статусами и доказательствами.</rule>
</additional_infrastructure>

<backend_api_database>
<scope>API; авторизация; RBAC; модели; схемы; миграции; транзакции; обработка ошибок; валидация; аудит; фоновые задачи; очереди; уведомления.</scope>
<rules>Не объединять бизнес-данные трёх продуктов в неразделённую модель. Общие библиотеки — общие, бизнес-логика сохраняет границы. Единые API-контракты; версионирование; обратная совместимость; документация; интеграционные тесты; контроль доступа; логирование; rate limiting.</rules>
</backend_api_database>

<ui_ux>
<design>Material Design/Material 3; адаптивность; понятное боковое меню; современные кнопки; единые карточки; ясные статусы; мобильная совместимость; доступность; светлая/тёмная темы по необходимости.</design>
<reference>Ориентироваться на функциональную ясность Support Pro, не копируя закрытые код и материалы.</reference>
<fix>Чёрные страницы; недоступные и пустые разделы; фиктивные кнопки; ошибки форм, модальных окон, таблиц, мобильных экранов и API. Показывать загрузку, успех и понятные ошибки.</fix>
</ui_ux>

<user_cabinet_telegram>
<features>Регистрация; вход; профиль; устройства; покупка; продление; подписка; срок; тариф; трафик; конфигурация; QR; инструкции; поддержка; уведомления; история платежей.</features>
<auth>Email; VK; Yandex при безопасной реализации.</auth>
<mini_app>Использовать общий API, не дублировать бизнес-логику.</mini_app>
</user_cabinet_telegram>

<mobile>
<android>Kotlin; Jetpack Compose; Material 3; VPNService; выбранный VPN-движок; GitHub Actions; APK/AAB. Сравнить sing-box и Xray по VLESS, REALITY, Hysteria 2, производительности, лицензиям, ограничениям, стабильности и интеграции.</android>
<ios>Swift 6; SwiftUI; Network Extension; NEVPNManager; Packet Tunnel Provider; Keychain; Face ID; Touch ID; entitlements; Apple Developer requirements. Не обещать возможности, ограниченные iOS или правилами Apple.</ios>
<admin_mobile>Android/iOS Lucy Admin; функциональная совместимость с Web Admin; критические действия доступны согласно RBAC.</admin_mobile>
<rule>Все мобильные приложения находятся внутри shop-by-boo.</rule>
</mobile>

<docker_installer_vps_termux>
<checks>Dockerfile; Compose; volumes; networks; ports; health checks; restart policies; dependencies; environment; secrets; database; migrations; logs; доступность сервисов.</checks>
<installer>Чистая установка; обновление; повторный запуск; восстановление; backup; rollback; проверка конфигурации; доменов; диагностика.</installer>
<vps>Подробная инструкция установки на тестовый VPS.</vps>
<termux>Android/Termux: инструменты; подключение к VPS; Git; проверка репозитория; установка; запуск; обновление; логи; диагностика. Пошагово для новичка.</termux>
</docker_installer_vps_termux>

<github_cicd>
<workflows>Проверка кода; линтеры; тесты; backend/frontend builds; Android; iOS; Docker; security scanning; dependency checks; лицензии; audit; releases; документация.</workflows>
<nightly>Проверка новых изменений; получение обновлений; анализ diff; dependency checks; backup; тестирование; сборка; совместимость; отчёт; rollback.</nightly>
<production_rule>Не обновлять production автоматически без проверок и разрешений.</production_rule>
<runner_rule>Не обещать работу без реального runner или иной среды выполнения.</runner_rule>
<admin_control>Lucy Admin показывает версии, изменения, проверки, дату, ошибки и rollback; может безопасно инициировать GitHub workflow. Не хранить токены открыто.</admin_control>
</github_cicd>

<documentation>
<readme>Назначение; архитектура; продукты; требования; установка; обновление; Docker; VPS; Termux; мобильные приложения; платежи; Remnawave; админка; диагностика; безопасность; ссылки.</readme>
<wiki_languages>Русский; English; Українська.</wiki_languages>
<guides>Архитектура; установка; администратор; пользователь; разработчик; платежи; Remnawave; VPN-ноды; MASQUE; мобильные приложения; восстановление; обновления; безопасность.</guides>
<rule>Не оставлять устаревшие инструкции и ненужные дубли.</rule>
</documentation>

<screenshot_coverage>
<purpose>Фактическая визуальная проверка всех продуктов, экранов, модулей и подразделов.</purpose>
<coverage>
<app name="VPN Shop">Главная; тарифы; покупка; оплата; подписка; история платежей; профиль; уведомления; ошибки; мобильная версия.</app>
<app name="User Cabinet">Регистрация; авторизация; профиль; подписка; устройства; конфигурация; продление; платежи; поддержка; настройки.</app>
<app name="Telegram Mini App">Все основные экраны; навигация; покупка; подписка; платежи; ошибки; загрузка.</app>
<app name="Telegram Bot">Команды; меню; диалоги; покупка; оплата; подписка; уведомления; ошибки.</app>
<app name="Lucy Admin Web">Dashboard; Users; Roles; Tariffs; Subscriptions; Payments; Payment Providers; Remnawave; VPN Nodes; Node Provisioning; MASQUE; Monitoring; Docker; Installer; Backup; Security; Logs; Automation; GitHub; Documentation и все дополнительные модули.</app>
<app name="Lucy Admin Android/iOS">Основные экраны; меню; пользователи; ноды; платежи; обновления; безопасность; диагностика; операции.</app>
<app name="VPN Client Android/iOS">Onboarding; импорт; подписки; серверы; подключение; настройки; PIN; биометрия; диагностика; Split Tunneling; Smart Routing; статистика; ошибки.</app>
<app name="Installer and Node Maintenance">Каталог; MTProto; HAProxy cascade; live test; GeoAssets; Xray ad block; AdGuard Home; RKN diagnostics; MSS clamp; panel access; Torrent-blocker; HTTPS; Status Page; BBR/BBR3; backups; snapshots; CrowdSec; HUBGuard; danger zone; remove component; clean server; protocol repair; reconnect stages.</app>
<app name="Auto-selection">Пул; состав; статистика; алгоритмы; настройки плитки; скрытие нод; выбор нод; обновление; ошибки; fallback.</app>
</coverage>
<tools>Playwright; Android Emulator; XCTest и доступные инструменты автоматизации.</tools>
<rules>Скриншоты настоящие, из запущенного приложения, актуальные и привязанные к версии. Не генерировать фальшивые скриншоты и не использовать макеты как доказательство. Проверять desktop/mobile, адаптивность, loading, ошибки, успешные операции, доступность элементов, отсутствие чёрных и пустых экранов.</rules>
<document>docs/SCREENSHOT_COVERAGE.md</document>
<metadata>Приложение; модуль; маршрут; версия; дата; сценарий; ожидаемый/фактический результат; путь к скриншоту; статус.</metadata>
</screenshot_coverage>

<balanced_development>
<rule>Все три продукта развиваются параллельно и имеют равную продуктовую значимость. P0–P5 обозначают только техническую срочность, риски и зависимости, не ценность продукта.</rule>
<documents>docs/PROJECT_BALANCED_DEVELOPMENT.md; docs/PROJECT_WORKLOAD_MATRIX.md; docs/PROJECT_COMPLETION_MATRIX.md.</documents>
</balanced_development>

<acceptance_checklist>
<file>docs/AUTONOMOUS_ACCEPTANCE_CHECKLIST.md</file>
<fields>Уникальный ID; исходная формулировка; описание; критерии; зависимости; статус; ссылка на код; тест; доказательство; дата; версия.</fields>
<statuses>PASS; FAIL; PARTIAL; NOT_IMPLEMENTED; BLOCKED_EXTERNAL; NOT_APPLICABLE; NOT_TESTED.</statuses>
<rules>PASS только с реальным подтверждением; PARTIAL при частичной реализации; BLOCKED_EXTERNAL при внешней блокировке; NOT_TESTED если тест не выполнен; NOT_IMPLEMENTED если функции нет.</rules>
</acceptance_checklist>

<audit_automation>
<directory>scripts/audit/</directory>
<scripts>run_full_audit.py; check_requirements.py; check_documentation.py; check_doc_links.py; check_screenshots.py; check_admin_parity.py; check_products_separation.py; check_api_contracts.py; check_runtime_placeholders.py; check_secrets.py; check_dependencies.py; check_licenses.py; check_docker.py; check_installation.py; check_mobile_builds.py; check_release_artifacts.py; check_tests.py; check_masque_support.py; check_vpn_protocols.py; check_node_provisioning.py; check_balanced_development.py; check_payments.py; check_remnawave.py; check_android_client.py; check_ios_client.py; generate_project_map.py; generate_audit_report.py; generate_checklist.py; check_auto_selection.py; check_node_maintenance.py; check_backup_restore.py; check_server_security.py; check_protocol_repair.py; check_status_page.py; check_mobile_ui.py; check_repository_monorepo.py; check_migration_integrity.py.</scripts>
<workflow>.github/workflows/autonomous-audit.yml</workflow>
<artifacts>artifacts/audit/checklist-results.json; artifacts/audit/FULL_AUDIT_REPORT.md.</artifacts>
<rule>Скрипты проверяют реальные условия, а не только наличие файлов.</rule>
</audit_automation>

<autonomous_cycle>DISCOVER → AUDIT → BUILD CHECKLIST → VERIFY CAPABILITIES → ARCHITECT → PLAN → IMPLEMENT → TEST → SELF-CHECK → COLLECT EVIDENCE → FIX FAILURES → RE-RUN CHECKLIST → UPDATE DOCUMENTATION → CONTINUE. Не останавливаться на анализе; не повторять бесконечно неудачную команду; фиксировать внешние блокировки; продолжать независимые задачи; проверять исправления; сохранять результаты; обновлять документацию.</autonomous_cycle>

<state_tracking>
<files>IMPLEMENTATION_STATUS.md; MASTER_ROADMAP.md; AUTOMATION_LOG.md; KNOWN_LIMITATIONS.md; docs/ADMIN_FEATURE_PARITY_MATRIX.md; docs/SCREENSHOT_COVERAGE.md; docs/AUTONOMOUS_ACCEPTANCE_CHECKLIST.md; docs/PROJECT_BALANCED_DEVELOPMENT.md; docs/PROJECT_WORKLOAD_MATRIX.md; docs/PROJECT_COMPLETION_MATRIX.md; docs/MASQUE_IMPLEMENTATION_REPORT.md; docs/CODE_REUSE_REGISTER.md; docs/REFERENCE_REPOSITORIES.md; docs/PAYMENT_TESTING.md; docs/AUTO_SELECTION.md.</files>
<interim>PROMPT_VPN_SHOP_&lt;DATE&gt;_STAGE_&lt;NUMBER&gt;.md</interim>
<rule>Фиксировать каждую задачу и не терять состояние после перезапуска рабочего окружения.</rule>
</state_tracking>

<final_reports>
<required>FINAL_PROJECT_AUDIT.md; FINAL_IMPLEMENTATION_REPORT.md; FINAL_SECURITY_REPORT.md; FINAL_TEST_REPORT.md; FINAL_ACCEPTANCE.md.</required>
<additional>Отчёт о миграции в монорепозиторий; сохранении функциональности; платежах; Remnawave; MASQUE; VPN-протоколах; Android; iOS; админке; скриншотах; installer; обслуживании нод; пуле автовыбора; backup/restore; CI/CD.</additional>
<fields>Что проверено; реализовано; исправлено; тесты выполнены/пройдены/не пройдены; оставшиеся проблемы; внешние блокировки; подтверждения.</fields>
</final_reports>

<git_security>
<allowed>Feature branches; fix branches; pull requests; проверка изменений; CI; code review; безопасные релизы.</allowed>
<forbidden>Force push; обход branch protection; переписывание чужой истории; удаление чужих изменений; удаление веток без разрешения; секреты в репозитории; публикация токенов; обход CAPTCHA/KYC/2FA; реальные платежи и возвраты без разрешения; удаление production-данных без разрешения; обновление production без проверок и разрешений.</forbidden>
<external_blockers>При отсутствии доступа/секретов отметить BLOCKED_EXTERNAL или BLOCKED_SECRETS, подготовить безопасную конфигурацию, выполнить sandbox-тесты и продолжить независимые задачи.</external_blockers>
<production_safety>Перед опасными действиями определить среду, сервер и права; сделать backup; подготовить rollback; показать последствия; получить разрешение. Не отключать защиту; не открывать лишние порты; не раскрывать токены, пароли, ключи, конфигурации пользователей, персональные данные и платёжные реквизиты. Вести audit log.</production_safety>
</git_security>

<first_execution_sequence>
<stage n="1" name="Inventory">Проверить shop-by-boo, Git и ветки; исходные репозитории; README; CODE_REUSE_REGISTER; REFERENCE_REPOSITORIES; структуру; карту архитектуры, технологий и зависимостей.</stage>
<stage n="2" name="Feature inventory">Найти все функции; каталогизировать модули; выявить уникальное, дубли и неработающее; матрица требований; список того, что нельзя потерять.</stage>
<stage n="3" name="Monorepo architecture">Сохранить имя shop-by-boo; подготовить структуру; границы трёх продуктов; общие библиотеки; API; БД; контракты; независимые сборки; план миграции и проверки сохранности.</stage>
<stage n="4" name="Full audit">Backend; Frontend; Admin; Cabinet; Telegram; Payments; Remnawave; Android; iOS; Docker; Installer; Node Maintenance; Auto-selection; MASQUE; Security; CI/CD; Documentation; Screenshots; Tests; Licenses.</stage>
<stage n="5" name="Migration">Переносить компоненты в shop-by-boo; проверить лицензии, зависимости, конфигурации, API, сборки, тесты, работу и документацию. Не удалять исходную реализацию до подтверждения переноса.</stage>
<stage n="6" name="Fixes">Исправить подтверждённые ошибки и проверить, что функции не потеряны.</stage>
<stage n="7" name="Products">Параллельно развивать VPN Client, VPN Shop и Lucy Admin. Не откладывать мобильные приложения, платежи, инфраструктуру и документацию.</stage>
<stage n="8" name="Node operations">Реализовать операции установки, обслуживания и пула автовыбора; проверить на тестовых нодах.</stage>
<stage n="9" name="Testing">Unit; integration; e2e; security; performance; Docker; installer; mobile; API; payments; node operations; backup/restore; visual screenshot coverage.</stage>
<stage n="10" name="Docs and release">Обновить README, Wiki, документацию и отчёты. Подготовить релиз; публиковать только после проверки и в пределах прав.</stage>
</first_execution_sequence>

<acceptance_criteria>
<criterion>Все целевые компоненты в одном shop-by-boo.</criterion>
<criterion>Название репозитория не изменено.</criterion>
<criterion>Уникальные функции исходных проектов сохранены или обоснованно отмечены как несовместимые/непереносимые.</criterion>
<criterion>Дубли объединены без потери возможностей.</criterion>
<criterion>Три продукта имеют чёткие границы.</criterion>
<criterion>VPN Client работает как бесплатный универсальный клиент.</criterion>
<criterion>VPN Shop работает как коммерческая платформа.</criterion>
<criterion>Lucy Admin управляет экосистемой.</criterion>
<criterion>Web/Android/iOS проходят проверку функциональной совместимости.</criterion>
<criterion>Платёжные адаптеры имеют подтверждённые статусы.</criterion>
<criterion>Remnawave интегрирован.</criterion>
<criterion>MASQUE исследован по реальным возможностям движков.</criterion>
<criterion>Установка и обслуживание нод проверены.</criterion>
<criterion>Auto-selection проверен по всем алгоритмам.</criterion>
<criterion>Backup/restore проверены.</criterion>
<criterion>Installer и Docker работают.</criterion>
<criterion>Известные ошибки исправлены.</criterion>
<criterion>Telegram Bot и Mini App проверены.</criterion>
<criterion>Документация обновлена на RU/EN/UK.</criterion>
<criterion>Скриншоты покрывают необходимые экраны.</criterion>
<criterion>Acceptance Checklist содержит доказательства.</criterion>
<criterion>CI/CD работает.</criterion>
<criterion>Безопасность проверена.</criterion>
<criterion>Отчёты созданы.</criterion>
<criterion>Внешние блокировки честно отражены.</criterion>
<criterion>Неподтверждённые функции не объявлены готовыми.</criterion>
</acceptance_criteria>

<non_loss_rule priority="absolute">
<rule>Не удалять ни одну ранее поставленную пользователем задачу.</rule>
<allowed>Объединять одинаковые задачи; устранять дублирование кода; объединять повторяющиеся требования, сохраняя критерии; уточнять формулировки; добавлять требования и проверки; улучшать архитектуру.</allowed>
<forbidden>Удалять уникальные функции; исключать задачи; заменять конкретную задачу общей формулировкой, теряющей критерии; считать упоминание функции достаточным; объявлять задачу выполненной без доказательства; терять задачи при миграции; забывать известные ошибки; игнорировать скриншоты.</forbidden>
<reconciliation>Перед каждым крупным этапом сверять работу с AUTONOMOUS_ACCEPTANCE_CHECKLIST.md. Новые задачи добавлять. Дубликаты объединять только при сохранении всех исходных критериев и связей.</reconciliation>
</non_loss_rule>

<final_objective>Создать единую, полноценную, безопасную, автоматизированную и масштабируемую экосистему VPN Shop by Corgi Lucy в одном GitHub-репозитории shop-by-boo. Внутри: бесплатный универсальный VPN Client Android/iOS; коммерческий VPN Shop; User Cabinet; Telegram Bot; Telegram Mini App; Lucy Admin Web/Android/iOS; единый backend/API; Payment Orchestrator; Remnawave; VPN Node Manager; Node Provisioning; MASQUE; VLESS/REALITY; Hysteria 2; Auto-selection; Installer; Node Maintenance; Monitoring; Backup/Restore; Security; Docker; CI/CD; Documentation; Tests; Screenshot Coverage; Autonomous Audit. Все продукты равноправны. Сохранить и проверить все существующие функции; устранить дубли без потери возможностей; не потерять ни одной задачи. Не останавливаться на архитектуре: реализовать, протестировать, документировать и доказать работу каждого доступного компонента.</final_objective>

<instruction_to_claude>Полностью прочитай этот XML. Изучи целевой репозиторий и все источники. До изменений создай полный реестр требований с уникальными ID и трассировкой к XML-разделам. Не начинай миграцию без инвентаризации и плана сохранения функций. Не удаляй и не сокращай требования. Каждая задача в backlog должна ссылаться на исходный XML-раздел. При противоречии не удаляй ни одну задачу: зафиксируй конфликт, предложи безопасное разрешение и сохрани исходные требования. Работай автономно в пределах доступов; не обходи защиту; не заявляй результаты без доказательств.</instruction_to_claude>
<completeness_supplement version="3.0">
  <purpose>Дополнение к предыдущим разделам. Ничего из основного документа не отменяет и не заменяет. Все нижеследующие требования обязательны, должны получить отдельные IDs в общем acceptance checklist и трассировку к исходному разделу.</purpose>

  <autonomous_execution_strict>
    <rule>Все проверки, доступные в предоставленной среде, выполнять полностью автономно, без участия пользователя.</rule>
    <rule>Не просить пользователя вручную запускать тесты, собирать логи или подтверждать рутинные безопасные действия, если это можно сделать доступными инструментами, CI, тестовым стендом или эмулятором.</rule>
    <rule>Если требуется физическое устройство, закрытый аккаунт, production secret, платный внешний ресурс, Apple Developer entitlement или иное недоступное условие, выполнить максимально возможные автоматические проверки и точно обозначить BLOCKED_EXTERNAL/BLOCKED_SECRETS. Не подменять их фиктивным PASS.</rule>
    <rule>Автоматически собирать evidence: логи, результаты команд, junit, screenshots, coverage, build artifacts, API traces с удалёнными секретами, версии и timestamps.</rule>
    <rule>Для routine actions использовать автономный цикл. Для необратимых, финансовых, production и destructive действий действуют ограничения безопасности основного документа.</rule>
  </autonomous_execution_strict>

  <repository_migration_expanded>
    <single_repository>Единственный целевой репозиторий: https://github.com/booarkz-cpu/shop-by-boo.git, имя shop-by-boo. Не создавать новые целевые репозитории. Ранее упомянутый lucy-vpn-android и другие репозитории — источники кода/истории для миграции в монорепозиторий.</single_repository>
    <migration_inventory>
      <task>Зафиксировать исходные URL, default branch, commit SHA, теги, релизы, ветки и состояние каждого источника.</task>
      <task>Составить каталог всех экранов, API endpoints, фоновых задач, CLI-команд, скриптов, сервисов, конфигураций, миграций БД и пользовательских сценариев.</task>
      <task>Сопоставить одинаковые функции, определить каноническую реализацию, перечислить отличия и уникальные возможности каждой реализации.</task>
      <task>До удаления/замены дубликата доказать функциональную эквивалентность тестами и контрактами.</task>
      <task>Сохранить attribution, лицензии, copyright notices и обязательные файлы лицензий.</task>
      <task>Сохранить полезную историю изменений там, где это возможно и законно; не переписывать историю целевого репозитория.</task>
      <task>Проверить отсутствие секретов и персональных данных в переносимых commit, fixture, логах и артефактах.</task>
      <task>Создать отчёт mapping: source repository/path/commit → monorepo path → новая реализация → тесты → evidence.</task>
      <task>После миграции проверить отсутствие потерянных endpoints, экранов, команд бота, фоновых задач, конфигураций и пользовательских сценариев.</task>
    </migration_inventory>
  </repository_migration_expanded>

  <vpn_shop_brand_and_customer_content>
    <brand_name>Корги Люси — Свободный интернет без лишнего Гав.</brand_name>
    <brand_variants>Корги Люси — «Свободный Гав!»; Корги Люси — Свободный интернет от Люси.</brand_variants>
    <tariff_copy>
      <max>Lucy Max: 2 устройства, безлимитный трафик.</max>
      <ultra>Lucy Ultra: 4 устройства, безлимитный трафик; показать очевидную выгоду относительно Max без изменения цены/условий без разрешения.</ultra>
      <mini>Lucy Mini — Test: 3 дня, 1 устройство, тестовый тариф.</mini>
      <task>Подготовить описания каждого тарифа отдельно, единый сравнительный блок трёх тарифов и упрощённый текстовый вариант.</task>
    </tariff_copy>
    <service_descriptions>Подготовить русское и английское описание сервиса для .env и пользовательских интерфейсов.</service_descriptions>
    <maintenance_message>Подготовить короткое уведомление о технических работах в фирменном стиле Lucy для .env/бота/кабинета.</maintenance_message>
    <payment_copy>Текст для оплаты через YooKassa с упоминанием СБП и карт платёжной системы «Мир». Не упоминать Visa/Mastercard в данном тексте. Не заявлять методы, которые фактически не включены у мерчанта.</payment_copy>
    <visual_assets>
      <banner_size>1280×640 px, соотношение 2:1.</banner_size>
      <format>JPEG, качество 90–95%, ориентир размера файла 200 KB, без прозрачности.</format>
      <layout>Текст не ближе 80 px от краёв; при необходимости уменьшить шрифт; проверить читаемость на мобильном экране.</layout>
      <rule>Фирменные тексты и баннеры согласовать с брендингом. Не использовать ложные заявления о скорости, безопасности, доступности или безлимитности сверх фактических условий.</rule>
    </visual_assets>
  </vpn_shop_brand_and_customer_content>

  <server_maintenance_screenshot_acceptance>
    <note>Ниже зафиксированы требования, извлечённые из присланных пользователем скриншотов раздела «Установка». Они являются самостоятельными критериями приёмки.</note>
    <page_heading>«Обслуживание и защита» — поддержание сервера в рабочем состоянии и сохранение данных перед изменениями.</page_heading>
    <intro_bullets>HTTPS и мониторинг; резервные копии; оптимизация и защита.</intro_bullets>
    <server_context>Показывать, какой сервер выбран. Сертификаты, ускорение и защита должны настраиваться именно на выбранном сервере. У каждой операции отображать способ выполнения, например SSH, и реальный целевой сервер.</server_context>
    <cards>
      <card id="panel-https" title="HTTPS для этой панели">Перевод панели с http://IP:порт на HTTPS по домену. Установка на сервер панели. Если 443 занят нодой, selfsteal или другим web-сервером, предложить другой свободный порт; для ACME проверить требуемый свободный порт 80. Обнаружить конфликт, не перезаписывать чужой web server.</card>
      <card id="vpn-status-page" title="Статус-страница VPN">Публичная status page для клиентов; проверка каждого конфига реальным трафиком; online и latency; установка в один клик; собственный домен; безопасное публичное отображение без раскрытия внутренней информации.</card>
      <card id="bbr" title="Ускорение BBR / BBR3">Проверить ядро и виртуализацию до изменений; применить только поддерживаемую настройку TCP; не менять VPN-конфигурацию; показать фактический результат.</card>
      <card id="automatic-backups" title="Настроить автобекапы">Ежедневный дамп БД Remnawave (Postgres) плюс конфигурации, ротация, локальная копия и off-site копия в Telegram/поддерживаемом хранилище; расписание, журнал, уведомления и тест восстановления.</card>
      <card id="snapshot-download" title="Снапшот сервера — скачать">Архив дампа БД Remnawave и всех необходимых конфигураций; скачивание инициируется из панели на устройство пользователя; checksum, контроль доступа, срок хранения и безопасное удаление временного архива.</card>
      <card id="crowdsec" title="CrowdSec — защита от брутфорса">Установка CrowdSec; обнаружение brute force и сканеров SSH/web; community blocklist при соблюдении условий; bouncer; журнал, метрики, уведомления, защита от ложных блокировок.</card>
      <card id="hubguard" title="HUBGuard — защита nftables">Ограничение новых соединений на портах ноды; autoban сканеров и перебора; собственная таблица inet hubguard; не ломать ufw и CrowdSec; добавить SSH-адрес администратора и необходимые CGNAT-адреса в whitelist; не обрывать текущую сессию.</card>
    </cards>
    <danger_zone_exact>
      <remove_component>Снять с сервера ОДИН компонент (например, бот, ноду, status page, MTProto), не трогая остальные. Ясно объяснить, что это не полная очистка сервера.</remove_component>
      <clean_server>Полностью удалить Remnawave, ноду, контейнеры и конфигурации. Необратимо. Требовать точный выбор сервера, перечень удаляемых ресурсов, проверку backup и повторное подтверждение.</clean_server>
    </danger_zone_exact>
    <operation_ui>В карточке: категория/тип «Обслуживание сервера»; способ выполнения; иконка; заголовок; описание; кнопка «Установить»/«Скачать»; ход выполнения; журнал; результат; ошибка и диагностика. Кнопка должна вызывать реальную операцию и быть защищена от повторного нажатия.</operation_ui>
  </server_maintenance_screenshot_acceptance>

  <protocol_switch_and_node_pool_screenshot_acceptance>
    <protocol_repair>
      <title>Починка блока: смена протокола</title>
      <stages>
        <stage>Чтение текущего транспорта.</stage>
        <stage>Смена протокола inbound.</stage>
        <stage>Обновление hosts.</stage>
        <stage>Проверка реконнекта нод.</stage>
      </stages>
      <example_observed_state>В пользовательском интерфейсе отображался inbound STEAL-T12 в профиле узла; исходный транспорт gRPC, целевой xHTTP. Это пример диагностического сценария, а не фиксированное имя для всех серверов.</example_observed_state>
      <stage_detail>Показать текущий профиль и inbound; прочитать фактический транспорт; обновить профиль Remnawave; инициировать корректное применение/перегенерацию конфигурации; обновить hosts; дождаться переподключения; проверить каждую ноду и итоговый транспорт.</stage_detail>
      <progress_ui>Общий статус; зелёные/ошибочные этапы; раскрываемый лог каждого этапа; временные метки; прогресс; ссылка «К списку»; возможность безопасного просмотра деталей.</progress_ui>
      <rollback>Сохранить старую конфигурацию и транспорт; при ошибке восстановить исходное состояние, если это безопасно; не оставлять часть нод на несовместимых параметрах.</rollback>
      <observed_result_example>В одном из показанных тестов обновился один hosts entry, а проверка сообщила об online-статусе 11 из 18 нод; это не считать универсальной нормой. Всегда показывать фактическое количество проверенных, online и offline нод.</observed_result_example>
    </protocol_repair>
    <node_reconnect_matrix>Отображать порядковый номер; страну; название ноды; статус online/offline; транспорт; причину ошибки; время проверки. Проверять все ноды, а не только первые несколько.</node_reconnect_matrix>
    <auto_selection_pool_ui>
      <heading>Пул автовыбора — «быстрейшая нода клиенту».</heading>
      <actions>Сбросить шаблон; убрать плитку; включить leastPing; обновить пул.</actions>
      <metrics>Видны в подписке X/Y; раздаются клиентам X/Y; у ноды есть открытая плитка; inbound входит в пул. Значения брать из реального состояния.</metrics>
      <mode>Отдельная плитка «Автовыбор» (новый режим) либо «Весь список» (старый режим). Обеспечить совместимость и не менять режим без явного действия администратора.</mode>
      <algorithm_options>По задержке (leastPing); по нагрузке (leastLoad); по кругу (roundRobin); случайно (random).</algorithm_options>
      <tile_name>Настраиваемое имя, пример «⚡ Автовыбор».</tile_name>
      <hide_pool_nodes>Переключатель скрытия узлов пула из списка приложения. При включении клиенты видят только плитку; при выключении обычные узлы возвращаются после обновления подписки.</hide_pool_nodes>
      <client_compatibility_warning>В Clash/sing-box/Base64 и других форматах может отсутствовать поддержка настоящего балансировщика. В таком случае честно объяснить, что плитка может вести на первый узел пула; не заявлять полноценный клиентский балансировщик.</client_compatibility_warning>
      <explanation>Панельный автовыбор выбирает ноду на серверной стороне; «Автовыбор в приложении» выбирает клиент. Отдельная плитка означает, что клиент видит одну плитку «Автовыбор» плюс обычные ноды, если скрытие не включено.</explanation>
      <node_table>Чекбокс включения ноды в пул; флаг/страна; имя; статус online; признак «раздаётся»; число пользователей; доступность; задержка/нагрузка; последняя проверка.</node_table>
      <observed_example>В показанном интерфейсе было 11/11 видимых в подписке и 11/11 раздаваемых; пример пула включал Германию №1, Чехию №1 и Нидерланды №2. Эти числа и страны не являются константами — только динамические данные.</observed_example>
      <retry>Повторный запуск обновляет пул по отмеченным галочкам; проверить идемпотентность и корректное сохранение настроек.</retry>
    </auto_selection_pool_ui>
  </protocol_switch_and_node_pool_screenshot_acceptance>

  <network_and_censorship_diagnostics>
    <rkn_context>Пользователь ранее описывал изменения фильтрации с 20.09.2026 и необходимость диагностировать адресные блокировки /32 и возможные блокировки подсетей /24. Проверять фактическую доступность из нескольких независимых сетей/регионов, SSH, ICMP, TCP и прохождение трафика; не делать вывод по одному ping.</rkn_context>
    <symptoms>Один IP может быть недоступен целиком; при других сценариях TCP может устанавливаться, но поток обрываться/дропаться после определённого объёма. Различать DNS, IP/route, TCP handshake, TLS, DPI/traffic filtering, firewall, MTU/MSS и проблемы самого узла.</symptoms>
    <status_communications>Готовить уведомления клиентам только по подтверждённым данным. Если сервис не затронут — не заявлять о проблеме; техническое объяснение делать кратким и понятным. Не обещать обход любых блокировок.</status_communications>
  </network_and_censorship_diagnostics>

  <product_and_service_reliability>
    <task>Проверить, что сервисы backend, admin, cabinet и bot, даже если Docker показывает UP, действительно отвечают по HTTP/API и выполняют пользовательские сценарии.</task>
    <task>Проверить все страницы админки и кабинета: проблема «чёрных страниц» и недоступных модулей ранее уже сообщалась.</task>
    <task>Проверить Telegram Bot отдельно от статуса контейнера: webhook/polling, токен в окружении без его вывода, команды, callback, платежные сценарии и доступность Telegram API.</task>
    <task>Проверить, что все ссылки на мобильные приложения в README ведут на реальные релизы/артефакты, а не на несуществующие файлы.</task>
    <task>Подготовить пошаговые инструкции для установки на тестовый VDS и управления с Android через Termux.</task>
    <task>Подготовить пошаговую инструкцию, как проверить git config user.name и user.email, в том числе с Android/Termux; не публиковать личный email без необходимости.</task>
    <task>Подготовить подробную инструкцию создания/включения GitHub Wiki и диагностики, если Wiki не открывается.</task>
    <task>Обновить README с мобильными ссылками, установкой, обновлением и восстановлением.</task>
  </product_and_service_reliability>

  <expanded_test_matrix>
    <payments>Автоматические sandbox-сценарии для каждого доступного провайдера; positive/negative; duplicate webhook; invalid signature; wrong amount/currency/order; timeout; provider unavailable; retry; refund simulation; reconciliation; recurring renewal; notification retry; expired invoice; transaction replay; provider failover. Production tests только с разрешённым тестовым контуром и без несанкционированного списания.</payments>
    <remnawave>Создание/изменение/удаление тестового пользователя; выдача и продление подписки; смена тарифа; лимит устройств; лимит трафика; expiry; отключённая нода; API timeout; повтор запроса; рассинхронизация; backup/restore; журнал.</remnawave>
    <node_ops>Для каждой серверной операции: dry-run; совместимость; порт занят/свободен; SSH недоступен; sudo отсутствует; диск заполнен; DNS ошибка; ACME failure; частичная установка; повторный запуск; rollback; удаление только компонента; восстановление.</node_ops>
    <auto_select>Проверить алгоритмы leastPing/leastLoad/roundRobin/random на детерминированных тестовых данных; равные метрики; устаревшие метрики; нода offline; все ноды offline; смена состава; скрытие; возвращение; подписка; разные клиентские форматы.</auto_select>
    <mobile>Android lifecycle; разрешения; VPNService; сеть Wi-Fi/mobile switching; reconnect; sleep/wake; low battery; PIN; biometric unavailable; biometric cancelled; lock/unlock; обновление подписки; импорт повреждённого профиля; несколько профилей; split tunneling; app crash recovery.</mobile>
    <ui>Каждый экран desktop/mobile; все кнопки; формы; empty state; loading; error; success; permissions; RBAC; pagination; filters; dialogs; keyboard; safe areas; accessibility.</ui>
  </expanded_test_matrix>

  <expanded_state_requirements>
    <requirement>Создать общий реестр требований, где у каждой задачи есть уникальный ID, дословная/смысловая исходная формулировка, источник (сообщение/скриншот/репозиторий/раздел XML), целевой продукт, модуль, критерии приёмки, зависимости, статус, evidence и история изменения.</requirement>
    <requirement>Не помечать задачу закрытой только потому, что создана документация, UI-кнопка или заглушка.</requirement>
    <requirement>Разделять IMPLEMENTED, BUILT, TESTED, VERIFIED и PRODUCTION_VERIFIED — это разные состояния.</requirement>
    <requirement>Для каждой функции фиксировать, на какой платформе она работает: Web, Android, iOS, Telegram Bot, Mini App, backend/API, server/node.</requirement>
    <requirement>При объединении дублей сохранять связи всех исходных task IDs с одной канонической задачей; не терять историю и критерии.</requirement>
    <requirement>В отчёте показывать процент покрытия требований и отдельный список требований без подтверждённого статуса.</requirement>
  </expanded_state_requirements>
</completeness_supplement>
</claude_master_prompt>
```


---

# ЧАСТЬ IV. РАСШИРЕНИЕ МАСТЕР-ПРОМПТА — ДОПОЛНИТЕЛЬНЫЕ ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ

> Это расширение добавляется к предыдущим частям и не заменяет их. Все требования Частей I–III остаются обязательными. Если новое требование пересекается со старым, сохранить оба источника и объединить только критерии, не удаляя смысл, ограничения, платформы или примеры.

## 23. Протокол сохранения требований и управления изменениями

1. Создать `docs/REQUIREMENTS_MASTER_REGISTER.md` как единый реестр всех требований из:
   - полного диалога и доступной истории сообщений;
   - исходных XML/MD мастер-промптов и их версий;
   - пользовательских скриншотов и описаний изображений;
   - всех перечисленных исходных репозиториев;
   - README, Wiki, docs, issues, pull requests, commits, tags, releases;
   - backlog, TODO, комментариев в коде, CI и installer;
   - найденных во время аудита скрытых, недокументированных и частично реализованных функций.
2. Для каждого требования завести стабильный ID, например `REQ-CLIENT-0001`, `REQ-SHOP-0001`, `REQ-ADMIN-0001`, `REQ-PAY-0001`, `REQ-NODE-0001`, `REQ-INFRA-0001`, `REQ-DOC-0001`.
3. Каждая запись содержит: исходную формулировку; источник и точную ссылку/путь/номер строки/commit/screenshot ID; продукт; домен; компонент; платформы; acceptance criteria; зависимости; риск; приоритет технической срочности; статус; тест; evidence; дату проверки; версию; историю изменений.
4. При объединении дублей создать canonical ID, но сохранить все исходные IDs и все критерии. Не объединять требования, которые только похожи по названию, но различаются поведением, платформой, ограничениями или результатом.
5. Вести `docs/REQUIREMENTS_CHANGELOG.md`. Запрещено физически удалять требования из реестра. Отменённые требования помечать `RETIRED_BY_OWNER` с причиной и ссылкой на решение владельца.
6. Вести `docs/SOURCE_TRACEABILITY_MATRIX.md`: источник → требования → код → тесты → evidence → релиз.
7. При недоступной истории/изображении/репозитории фиксировать `SOURCE_UNAVAILABLE`, а не восстанавливать точный текст догадкой. Продолжать работу по доступным задачам.
8. В конце каждого этапа сверять количество требований: найдено, импортировано, объединено без потери критериев, реализовано, протестировано, заблокировано, осталось без проверки.
9. Ни одна задача не считается закрытой по факту создания файла, интерфейса, API-заглушки, mock, TODO или описания в документации.
10. До любых крупных миграций создать baseline-функциональности и план доказуемого сохранения поведения.

## 24. Продуктовая архитектура и границы доменов

Все три продукта имеют равную продуктовую значимость. При этом единый монорепозиторий не означает общую неразделённую бизнес-модель.

### 24.1. Общие доменные принципы

- Разделить bounded contexts: `vpn_client`, `shop`, `identity`, `billing`, `subscriptions`, `remnawave`, `nodes`, `admin`, `support`, `notifications`, `analytics`, `infrastructure`.
- Общими могут быть UI primitives, дизайн-токены, API-клиенты, схемы DTO, localization utilities, telemetry abstractions, test helpers и security utilities.
- Разделить данные, права, бизнес-процессы и жизненные циклы самостоятельных продуктов.
- Определить владельца каждого домена, публичные контракты, события, таблицы БД и разрешённые зависимости.
- Не допускать циклических зависимостей и прямого доступа одного сервиса к внутренним таблицам другого домена.
- Интеграции должны идти через API, события или документированные application services.
- Для каждого сервиса определить: назначение, входы/выходы, зависимости, health/readiness, конфигурацию, секреты, миграции, логирование, метрики, backup, deploy и rollback.

### 24.2. Архитектурные документы

Создать и поддерживать:
- `docs/architecture/SYSTEM_OVERVIEW.md`
- `docs/architecture/CONTEXT_MAP.md`
- `docs/architecture/CONTAINER_DIAGRAM.md`
- `docs/architecture/DATA_FLOW.md`
- `docs/architecture/DOMAIN_BOUNDARIES.md`
- `docs/architecture/API_CATALOG.md`
- `docs/architecture/EVENT_CATALOG.md`
- `docs/architecture/ADR/`
- `docs/architecture/THREAT_MODEL.md`
- `docs/architecture/DEPLOYMENT_TOPOLOGY.md`

Для значимых решений оформлять ADR: контекст, варианты, решение, последствия, риски, обратимость, дата и статус.

## 25. VPN-клиент — расширенные требования

### 25.1. Управление профилями и подписками

- Поддерживать несколько независимых подписок и локальных профилей.
- Отображать источник, дату последнего обновления, дату следующего обновления, срок действия, количество конфигураций и ошибки.
- Поддерживать обновление вручную и по расписанию с разумными ограничениями, backoff и защитой от одновременных обновлений.
- Не перезаписывать рабочий профиль невалидным ответом сервера.
- При ошибке обновления сохранять последнюю рабочую конфигурацию и показывать понятную диагностику.
- Обрабатывать истёкшую подписку, пустой список, некорректный формат, неизвестный протокол, дубли, недоступный URL, redirect, TLS error и oversized response.
- Импортировать только разрешённые схемы; проверять URL, redirects, сертификаты, размер и содержимое; не допускать SSRF через произвольные внутренние адреса.
- Поддерживать резервное копирование и перенос профилей с защитой приватных данных.
- Экспортировать конфигурации только после явного действия пользователя и предупреждать о чувствительных ключах/UUID.

### 25.2. Подключение и стабильность

- Реализовать корректные состояния: disconnected, preparing, connecting, connected, reconnecting, stopping, permission_required, error.
- Исключить гонки при быстрых нажатиях connect/disconnect и смене профиля.
- Сохранять состояние VPN при смене Activity/Scene, повороте экрана, сворачивании приложения и блокировке устройства.
- Отдельно тестировать переход Wi-Fi ↔ mobile data, captive portal, потерю сети, смену IP, DNS failure, sleep/wake, Doze, low-memory и reboot.
- Не показывать connected до подтверждения работающего tunnel/data path.
- Обеспечить корректное завершение соединения, освобождение ресурсов и защиту от zombie service.
- Реализовать диагностический экспорт без секретов и персональных данных по умолчанию.

### 25.3. Приватность и разрешения

- Объяснять назначение VPN permission, локального VPN API, уведомлений и иных разрешений.
- Не собирать историю трафика, содержимое пакетов или browsing history без необходимости и явного основания.
- Не передавать диагностические данные без согласия пользователя.
- Документировать, что VPN не гарантирует анонимность, защиту от всех угроз или обход всех блокировок.
- PIN/биометрия защищают интерфейс и локальные действия, но не должны неожиданно останавливать активный VPN tunnel.
- Секреты профилей хранить в защищённом хранилище платформы, где это применимо.

### 25.4. Производительность

Измерять cold start, warm start, connect time, reconnect time, CPU, RAM, battery impact, app size, crash-free sessions и throughput на сопоставимых тестовых условиях. Не заявлять численные улучшения без baseline и повторяемых измерений.

## 26. VPN Shop, пользовательский кабинет и Telegram — расширение

### 26.1. Жизненный цикл пользователя

- Единая модель account, profile, credentials, linked identities, devices, subscriptions, orders, payments, invoices, support tickets и notification preferences.
- Поддерживать безопасную привязку/отвязку email, VK, Yandex и Telegram identity.
- Защитить account linking от takeover и подмены identity.
- Реализовать восстановление доступа, смену пароля, logout all sessions, revoke sessions и подтверждение критичных действий.
- Не раскрывать существование аккаунта в ответах восстановления пароля.
- Предусмотреть удаление/экспорт данных в пределах применимого законодательства и политики сервиса.

### 26.2. Подписки и entitlement

- Разделить тарифный план, заказ, платёж, entitlement, активную подписку и техническую конфигурацию VPN.
- Определить единственный авторитетный источник состояния подписки.
- Обработать pending, active, grace period, past_due, expired, canceled, suspended, refunded, chargeback и migration states.
- Синхронизировать entitlement после подтверждённого платежа; повторный webhook не должен создавать повторную подписку или повторное начисление.
- Правильно обрабатывать timezone, даты окончания, продление до окончания, продление после окончания и смену тарифов.
- Изменение числа устройств должно отражаться в Remnawave и пользовательском кабинете согласованно.
- При частичной недоступности Remnawave применять retry/outbox и reconciliation, а не терять оплаченный заказ.

### 26.3. Telegram Bot и Mini App

- Проверить webhook secret token, обработку update ID, повторов, out-of-order events, timeout и Telegram API rate limits.
- Поддерживать идемпотентную обработку команд и callback queries.
- Не выполнять финансовую операцию только по данным клиента или тексту callback.
- Проверять Telegram Mini App `initData` на сервере, timestamp и подпись; не доверять присланному `user` JSON без валидации.
- Проверять домен, HTTPS, allowed origins, session binding и срок жизни сессии.
- Корректно обрабатывать повторный вход, несколько устройств, закрытие Mini App и возврат после оплаты.
- Все тексты и кнопки локализовать RU/EN/UK.
- Создать E2E сценарии: start → register/login → choose tariff → create order → payment → entitlement → subscription/config → support → renewal.

## 27. Lucy Admin — расширение требований

### 27.1. RBAC и аудит

- Определить роли и permissions по ресурсам и операциям, включая read/create/update/delete/execute/export/refund/deploy.
- Применять авторизацию на backend, а не только скрывать UI.
- Поддерживать принцип наименьших привилегий, разделение обязанностей и доступ по окружениям.
- Критические операции требовать повторной аутентификации или дополнительного подтверждения в соответствии с риском.
- Audit log должен содержать actor, action, resource, timestamp, result, correlation ID и безопасный diff без секретов.
- Логи аудита должны быть защищены от незаметного изменения и доступны для расследования.

### 27.2. Административные списки и операции

Для таблиц Users, Nodes, Payments, Subscriptions, Orders, Tickets и Audit Logs реализовать поиск, фильтры, сортировку, пагинацию, сохранённые представления, экспорт с RBAC, bulk actions с preview, подтверждением и журналом. Обеспечить серверную пагинацию и устойчивость к большим наборам данных.

### 27.3. Dashboard и мониторинг

Показывать только реальные метрики с указанием источника, периода и времени последнего обновления: revenue, paid orders, conversion, active/expired subscriptions, churn, node health, latency, traffic, service health, payment provider health, queue lag, failed jobs, webhook failures и incidents. Не подменять отсутствующие данные нулями или фиктивными графиками.

### 27.4. Операционный центр

- Объединить статус сервисов, нод, интеграций, платежей, бота, Mini App, кабинета, мобильных сборок, backup jobs и CI/CD.
- Ввести incident lifecycle: detected, acknowledged, investigating, mitigated, resolved, postmortem.
- Показывать владельца инцидента, severity, impact, timeline, связанные alerts, действия и postmortem.
- Опасные действия выполнять через backend jobs с idempotency key, progress, logs, timeout, cancellation policy и rollback strategy.
- UI не должен утверждать, что операция выполнена, пока backend не вернул подтверждённый результат.

## 28. Платежи — дополнительная строгая спецификация

### 28.1. Модель транзакций

Разделить сущности `Order`, `PaymentAttempt`, `ProviderTransaction`, `WebhookEvent`, `Refund`, `SubscriptionEntitlement`, `ReconciliationRecord`. Один заказ может иметь несколько попыток, но не должен приводить к двойному начислению. Уникальные ключи должны быть определены для order, provider transaction и webhook event.

### 28.2. Надёжность

- Использовать transactional outbox/inbox там, где это оправдано архитектурой.
- Обрабатывать повторные, задержанные и пришедшие не по порядку webhook.
- Периодически сверять локальные статусы с API провайдера.
- Предусмотреть timeout, retry with backoff, circuit breaker, provider degradation и безопасный failover.
- Не переключать пользователя на другого провайдера после неопределённого результата первой попытки без проверки, не прошёл ли первый платёж.
- Хранить минимально необходимые данные; не хранить PAN/CVV и иные запрещённые платёжные данные.
- Разделять test и live credentials, sandbox и production endpoints.
- Не писать секреты и полные webhook payload с персональными/платёжными данными в обычные логи.

### 28.3. Проверка провайдера

Для каждого провайдера из исходного списка отдельно проверить: официальный API, документацию, доступность в стране/для юридического лица пользователя, методы, валюты, комиссии, recurring/refund/partial refund, webhook signing, test mode, ограничения, SDK, сроки и статус интеграции. Не удалять провайдер только потому, что документация или credentials сейчас недоступны; отметить blocker и оставить адаптер/контракт только если это оправдано архитектурой.

### 28.4. Отображение методов

Список методов оплаты строить из подтверждённых capabilities и настроек merchant account. Не показывать метод, если он не активирован, не доступен для валюты/суммы/страны/платформы. Не смешивать `provider_id`, `method_id`, `config_id`, `payment_system` и `platform_billing`.

## 29. Remnawave и управление нодами — расширение

- Создать единый Remnawave adapter с versioned API contract и capability detection.
- Разделить desired state и observed state для нод, inbounds, пользователей, подписок и конфигураций.
- Реализовать reconciliation loop с ограничением частоты, retries, jitter и dead-letter handling.
- Сохранять состояние последней успешной синхронизации и выявлять drift.
- Не удалять и не перезаписывать существующие inbounds без инвентаризации и backup.
- Поддерживать безопасные операции create/update/disable/enable/delete с dry-run, preview и rollback.
- Для bulk actions выводить список целевых узлов, итоговые изменения, зависимые сервисы и оценку влияния.
- Учитывать разные версии панели, API, Xray/sing-box и типы серверов; не считать одинаковую конфигурацию совместимой со всеми узлами.
- Проверять SSH host key, не отключать host key checking ради удобства.
- Использовать ограниченные сервисные учётные записи и минимальные права.
- Ограничивать параллелизм SSH операций и иметь rate limits.
- Перед обновлением/сменой протокола проверять backup, доступность out-of-band восстановления и способ rollback.
- После операции проверять не только process status, но и реальное подключение клиентом.

## 30. Установка, обновления и миграции — расширение

### 30.1. Установщик

Поддерживать идемпотентные этапы: preflight → environment validation → DNS/ports → secrets → dependencies → database → migrations → services → health checks → admin bootstrap → final report. Каждый этап должен иметь машинно-читаемый статус, лог, понятную ошибку и безопасный повтор.

### 30.2. Обновление

- Проверять совместимость текущей и целевой версии.
- Создавать backup до миграции.
- Проверять свободное место и доступность внешних зависимостей.
- Выполнять миграции с блокировкой конкурентного запуска.
- Поддерживать rolling/blue-green подход, если он совместим с фактической архитектурой.
- При неуспехе останавливать rollout и выполнять документированный rollback.
- Не откатывать базу данных автоматически, если миграция необратима или rollback не проверен.
- Проверять post-deploy health и ключевые E2E сценарии.

### 30.3. Миграция в монорепозиторий

- Создать inventory файлов, модулей, конфигураций, таблиц, endpoints, background jobs, webhooks, cron jobs, secrets references, workflows и deploy targets каждого исходного проекта.
- Для каждого компонента зафиксировать source repo/branch/commit, license, destination path, адаптации, тесты и результат.
- Сохранять Git history, если это возможно и не создаёт конфликтов/рисков.
- Сравнить поведение до и после миграции.
- Проверить отсутствие случайного попадания `.env`, токенов, приватных ключей, дампов и пользовательских конфигураций.
- Не удалять старые проекты/ветки/артефакты без отдельного разрешения.

## 31. Инфраструктура, наблюдаемость и SRE

### 31.1. Health и observability

- Разделить liveness, readiness и dependency health.
- Добавить structured logs, metrics, traces и correlation IDs.
- Отслеживать error rate, latency percentiles, throughput, saturation, queue depth, failed jobs, webhook lag, DB pool, disk, memory, CPU, node availability и certificate expiry.
- Определить SLI/SLO только после измерения baseline и согласования целей; не придумывать SLA.
- Уведомлять о backup failures, certificate expiry, payment provider outage, node degradation, failed migrations и security incidents.
- Учитывать timezone и clock drift для cron, webhook signature и сертификатов.

### 31.2. Backup и disaster recovery

- Классифицировать данные по критичности и допустимой потере.
- Установить RPO/RTO только после согласования и тестирования.
- Защищать backup шифрованием, ограничением доступа и отдельными credentials.
- Хранить копии отдельно от production host.
- Проверять checksum, полноту, срок хранения и доступность.
- Выполнять регулярный restore drill в изолированной среде.
- Документировать восстановление БД, конфигураций, секретов, панели, нод и DNS.
- Снапшоты сервера не считать полноценной заменой согласованной стратегии backup.
- Не удалять последний проверенный backup автоматически.

### 31.3. Сертификаты и DNS

- Контролировать DNS records, TTL, ACME challenge, certificate chain, expiry, SAN, renewal и port conflicts.
- Перед изменением DNS или TLS проверять доступность панели и способ восстановления.
- Не перезаписывать существующие reverse proxy/server blocks без backup.
- Поддерживать безопасное хранение приватных ключей и ограничение доступа.

## 32. Безопасность и privacy — расширение

- Создать threat model для трёх продуктов и отдельно для payment, admin, node provisioning и mobile VPN client.
- Провести STRIDE или эквивалентный threat analysis для доверительных границ.
- Проверять OWASP ASVS/API/MASVS применительно к фактическому стеку.
- Проверять IDOR/BOLA, SSRF, SQLi, XSS, CSRF, path traversal, command injection, template injection, deserialization, open redirect, privilege escalation, race conditions и insecure direct object access.
- Проверять CORS, CSP, cookie flags, session rotation, refresh token rotation, password reset, MFA support, rate limits и brute force protection.
- Использовать secret scanning, dependency scanning, SAST, DAST и container scanning там, где доступны инструменты.
- Проверять SBOM, лицензии, уязвимые зависимости и происхождение бинарных артефактов.
- Не логировать токены, пароли, private keys, VPN credentials, payment secrets и полные персональные данные.
- Проверять экспорт/импорт данных, права на скачивание, временные ссылки и срок действия.
- Для мобильных приложений проверить secure storage, deep links, exported components, backup rules, network security config, certificate validation и jailbreak/root limitations без ложных гарантий.
- Security findings классифицировать по severity, exploitability, impact, affected version, remediation и retest evidence.

## 33. Локализация, доступность и качество интерфейсов

- Полностью поддерживать русский, английский и украинский языки во всех трёх продуктах, включая ошибки, уведомления, письма, bot, Mini App, installer и документацию.
- Не смешивать локализованные строки с бизнес-логикой.
- Проверять длинные строки, pluralization, даты, валюты, timezone, RTL readiness при необходимости и отсутствие обрезания.
- Проверять keyboard navigation, focus management, labels, contrast, touch target sizes, screen readers, semantic headings и reduced motion.
- Проверять responsive layouts на реальных viewport widths, safe areas, virtual keyboard и длинных таблицах.
- Для каждой формы проверять client-side и server-side validation, field-level errors, submit loading, duplicate submit и сохранение данных при ошибке.
- Для каждой операции иметь понятные confirmation, progress, success/failure и recovery states.

## 34. Полная стратегия тестирования

### 34.1. Уровни тестов

- Unit tests для доменной логики и edge cases.
- Contract tests для API, webhook, Remnawave и payment adapters.
- Integration tests для БД, очередей, фоновых задач и сервисных взаимодействий.
- E2E tests для критических пользовательских и административных сценариев.
- Security tests и regression tests для известных ошибок.
- Load/soak tests для критичных API, платежей, очередей и VPN-node orchestration.
- Mobile UI/instrumentation tests на Android и доступные iOS simulator tests.
- Installer/upgrade/restore tests на чистых и обновляемых окружениях.
- Chaos/failure injection только на изолированном тестовом контуре.

### 34.2. Обязательные проверки регрессии

- Покупка/продление не создаёт дубли.
- Повтор webhook безопасен.
- Ошибка Remnawave не теряет подтверждённый платёж.
- Недоступность одной ноды не ломает остальные.
- Неудачный импорт не повреждает действующий профиль.
- PIN/биометрия не останавливают VPNService.
- Изменение протокола имеет rollback.
- Backup восстанавливается.
- Удаление одного компонента не затрагивает соседние сервисы.
- Изменение локали не ломает layout и валидацию.
- Пользователь без нужных прав не может выполнить операцию через прямой API.
- Повторное нажатие опасной кнопки не запускает дублирующую операцию.

### 34.3. Test evidence

Каждый отчёт содержит commit SHA, branch, environment, tool versions, commands, exit codes, test counts, skipped tests, logs, screenshots, artifact links и known limitations. Redact secrets. Не заявлять coverage или pass rate без отчёта инструмента.

## 35. CI/CD, релизы и управление версиями

- Установить единые правила versioning и changelog для каждого независимо выпускаемого приложения/сервиса.
- Проверять lint, format, typecheck, unit, integration, contract, security, build, Docker, installer и mobile build jobs.
- Кэшировать зависимости безопасно и фиксировать lockfiles.
- Использовать минимальные GitHub Actions permissions, pin action versions и защищать secrets/environments.
- Разделить preview, staging и production.
- Создавать release notes с breaking changes, migrations, rollback, known issues и checksum artifacts.
- Проверять подпись/происхождение релизных артефактов, где поддерживается.
- Не публиковать release, пока критические проверки не прошли или не зафиксированы явно разрешённые исключения.
- Nightly jobs не должны автоматически внедрять непроверенные изменения в production.
- Не обещать автоматическое выполнение задач, если runner отключён или не настроен.

## 36. Управление производительностью и стоимостью

- Измерить baseline API latency, DB query performance, memory, CPU, startup, build times, image sizes и mobile app size.
- Найти N+1 queries, неоптимальные индексы, неограниченные выборки, большие payloads и ненужные polling loops.
- Добавить pagination и bounded queries.
- Определить лимиты на uploads, request bodies, subscription refresh, webhook concurrency, SSH jobs и bulk actions.
- Контролировать стоимость внешних API, SMS/email, платежных провайдеров, storage, monitoring и CI.
- Не вводить платные сервисы и recurring расходы без согласования владельца.
- Оптимизации подтверждать benchmark до/после.

## 37. Полный каталог документов и артефактов

Помимо файлов, уже перечисленных в Частях I–III, создать при необходимости:
- `docs/REQUIREMENTS_MASTER_REGISTER.md`
- `docs/REQUIREMENTS_CHANGELOG.md`
- `docs/SOURCE_TRACEABILITY_MATRIX.md`
- `docs/architecture/SYSTEM_OVERVIEW.md`
- `docs/architecture/CONTEXT_MAP.md`
- `docs/architecture/CONTAINER_DIAGRAM.md`
- `docs/architecture/DATA_FLOW.md`
- `docs/architecture/DOMAIN_BOUNDARIES.md`
- `docs/architecture/API_CATALOG.md`
- `docs/architecture/EVENT_CATALOG.md`
- `docs/architecture/THREAT_MODEL.md`
- `docs/architecture/DEPLOYMENT_TOPOLOGY.md`
- `docs/SECURITY_BASELINE.md`
- `docs/PRIVACY_DATA_MAP.md`
- `docs/DISASTER_RECOVERY.md`
- `docs/OBSERVABILITY.md`
- `docs/SLO_BASELINE.md`
- `docs/RELEASE_PROCESS.md`
- `docs/UPGRADE_ROLLBACK.md`
- `docs/MOBILE_RELEASE_GUIDE.md`
- `docs/INCIDENT_RESPONSE.md`
- `docs/ACCESSIBILITY_AUDIT.md`
- `docs/PERFORMANCE_BASELINE.md`
- `docs/SBOM_AND_LICENSES.md`

Не создавать фиктивные пустые документы ради наличия файла. Документ должен содержать проверенное содержание и соответствовать фактическому коду.

## 38. Расширенный критерий готовности к эксплуатации

Экосистема может быть названа production-ready только при наличии доказательств по всем применимым пунктам:

1. Все три продукта имеют работающие основные сценарии и согласованные API-контракты.
2. Все существующие функции исходных репозиториев инвентаризированы и либо сохранены, либо явно согласованы к выводу из эксплуатации.
3. Кабинет, бот, Mini App, админка и VPN-клиент работают на целевых платформах.
4. Платёжные интеграции разделены по статусам и проверены в sandbox; live доступность не выдумана.
5. Remnawave sync и recovery протестированы.
6. Нодовые операции имеют dry-run, журнал, backup и безопасный rollback в применимых случаях.
7. Installer, fresh install, upgrade и restore воспроизводимы.
8. Security review не содержит неустранённых критических/высоких рисков без документированного принятия риска владельцем.
9. CI/CD и релизные артефакты проверены.
10. Мониторинг, алерты, backup и restore drill работают.
11. Документация соответствует реальному поведению.
12. Все требования имеют статусы и доказательства или конкретный blocker.
13. Все скриншоты — реальные, привязанные к версии и тестовому сценарию.
14. Нет фиктивных экранов, кнопок, данных, метрик или отчётов.
15. Известные ограничения, внешние зависимости, расходы и операционные обязанности явно перечислены.

## 39. Правило автономного исполнения

После инвентаризации Claude должен сразу начинать практическую реализацию доступных задач. Не ограничиваться аудитом и планом. Выполнять независимые безопасные задачи параллельно, но не запускать конфликтующие миграции и destructive operations одновременно. Не повторять одну и ту же неудачную команду бесконечно: диагностировать причину, изменить подход, зафиксировать blocker и двигаться дальше. После каждого логического блока обновлять реестр, документацию, тесты и evidence.

## 40. Обязательный финальный ответ владельцу

Финальный отчёт должен содержать:
- краткий итог по каждому из трёх продуктов;
- сколько требований найдено и сколько имеют source trace;
- сколько реализовано, собрано, протестировано, подтверждено и production-verified;
- сколько FAIL, PARTIAL, NOT_IMPLEMENTED, NOT_TESTED и BLOCKED_EXTERNAL;
- конкретные исправленные ошибки;
- результаты тестов с командами и exit codes;
- ссылки на PR/commit/release только если они действительно существуют;
- список релизных артефактов;
- как установить, обновить и восстановить систему;
- нерешённые задачи с ID и причиной;
- какие действия требуют внешних credentials, физического устройства, merchant approval или явного разрешения владельца;
- подтверждение, что исходные требования не были удалены, и отчёт о сверке реестра с источниками.

**Запрещено писать «всё готово», «всё исправлено», «100% выполнено» или «ничего не потеряно», если это не подтверждено полным реестром, тестами и evidence.**
