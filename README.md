# VPN Shop by Corgi

[![CI](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/ci.yml)
[![Docker](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/docker.yml/badge.svg?branch=main)](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/docker.yml)
[![Release](https://img.shields.io/github/v/release/booarkz-cpu/shop-by-boo?display_name=tag)](https://github.com/booarkz-cpu/shop-by-boo/releases/latest)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178C6)
![License](https://img.shields.io/badge/license-2.8-FF8A1F)

Актуальная схема каталогов, функциональных границ и визуальной системы собрана в [карте проекта](docs/PROJECT_MAP_RU.md). Полное дерево каталогов и правила границ модулей: [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md).

Единый магазин VPN-подписок: админ-панель, веб кабинет пользователя, Telegram-бот и Mini App, приложения Android и iOS. Админка, кабинет и Mini App построены на Next.js и используют единую тёмную систему Remna Dark (светлая тема сохранена) с контекстными подсказками у всех редактируемых полей.

**v28.9.0 — текущий стабильный тег дистрибутива.** Он содержит runtime/API `21.5.1`, head магазина `0068_network_intel` и Support Pro `0007` / 3.7. Разделение тега и версии API намеренное: оператор устанавливает `v28.9.0`, а health/API возвращает `21.5.1`. Полная фактическая матрица и критерии закрытия опубликованы отдельно: [карта покрытия](docs/ru/WORKSPACE_COVERAGE.md), [критерии завершения](docs/ru/MATRIX_COMPLETION_21_5_1.md).

В alpha.7 добавлен [вход администратора по passkey](docs/ru/ADMIN_PASSKEYS.md), [операционный dashboard и alerts](docs/ru/OPERATIONS_MONITORING.md). Исправлена привязка публикации мобильных пакетов к актуальному тегу; подписи владельца по-прежнему нужны.

Текущий стабильный выпуск: [v28.9.0](https://github.com/booarkz-cpu/shop-by-boo/releases/tag/v28.9.0). Точный commit и результаты CI указаны на странице релиза. Production-платежи остаются закрытыми: application E2E v2 не завершён. Подписанные APK/IPA требуют ключей владельца. Изменения рабочего пространства описаны в [CHANGELOG.md](CHANGELOG.md). Актуальные инструкции: [DOCUMENTATION.md](DOCUMENTATION.md), [INSTALL_STEPS.md](INSTALL_STEPS.md), [FUNCTIONS.md](FUNCTIONS.md), [SECURITY.md](SECURITY.md). Исторические редакции не являются текущим руководством.

Сведение поддержки и перенос старой истории: [отдельная инструкция](docs/ru/WORKSPACE_SUPPORT_BRIDGE.md).

## Обновление v28.9.0

Админ-панель, личный кабинет и Telegram Mini App переведены на **Next.js** (static export, прежние nginx-образы и Caddy) и получили единый дизайн **Remna Dark**: сворачиваемый sidebar и выдвижное меню на телефонах, дашборд с плашкой состояния, плитками метрик 2×2/4×1, поиском и сегментированным фильтром серверов, skeleton-загрузку. Mini App использует Telegram WebApp SDK: тема и safe area из клиента, haptic feedback, нативные BackButton/MainButton, подтверждение закрытия во время оплаты. Кабинет показывает статус, остаток трафика и срок подписки, QR и копирование ссылки, пошаговую инструкцию, карточки тарифов, профиль и историю платежей. Новый [перенос истории](docs/ru/HISTORY_IMPORT_CURRENT.md) подписок и платежей сверяет контрольные итоги, не дублирует строки при повторе и откатывается журналом. Production CSP (`script-src 'self'`) соблюдается: inline-скрипты Next.js выносятся в файлы при сборке.

Настройки без перезапуска из v28.3.0 (96 live-параметров, зашифрованные секреты, staged apply и откат) сохранены.

Обновление существующей установки с тегов `v26`–`v28.7.0` выполняется проверяющим скриптом: [инструкция обновления дистрибутива](docs/ru/DISTRIBUTION_UPGRADE_CURRENT.md). Версия API остаётся `21.5.1`; перед применением новой миграции `0068_network_intel` обязателен согласованный backup.

## Что входит в проект

| Компонент | Возможности |
| --- | --- |
| Админ-панель | Поиск разделов, таблицы с поиском и страницами, типизированные live-настройки с шифрованием/историей/откатом, тарифы и конструктор, платежи и возвраты, поиск клиента по ID/Telegram/email/имени, читаемая карточка клиента, обращения и ответы, реферальные выплаты, маркетинг, серверы, агенты, антиабуз, роли и 2FA, резервные копии |
| Кабинет | Регистрация и вход, безопасное объединение аккаунтов, подписка, смена тарифа, докупка трафика, тарифы, кошелёк и история, подарки и подарочные карты, история платежей и PDF-квитанции, управление автопродлением, подключение по ссылке/QR, устройства, рефералы и заявки на выплаты, уведомления, обращения с перепиской |
| Telegram Mini App | Тот же кабинет и API; настраиваемые изображение, инструкции и кнопки бота; авторизация Telegram |
| Бот | `/start`, `/buy`, `/subscription`, `/promo`, `/account`, `/balance`, `/payments`, `/gifts`, `/referral`, `/support`, `/devices`, `/ops`; рассылки и переходы в нужные страницы кабинета |
| Android и iOS | Сохранены приложения клиента и администратора, мобильная авторизация и VPN-компоненты; обновлены цвета |
| Ядро | PostgreSQL, Redis, очередь фоновых задач, Remnawave, проверка платежей, финансовый журнал, идемпотентность, аудит |

**Платёжные агенты для новых покупок: YooKassa, RollyPay, Platega.** Внутренний кошелёк — способ оплаты имеющимся балансом. Sandbox — тестовый режим, запрещённый в production. Покупки через Apple/Google отключены; наличие Android/iOS-приложений от этого не зависит. Старые платёжные записи сохранены, прежние адаптеры используются только для сверки и возвратов исторических операций.

## Скриншоты

Снимки всех разделов админ-панели и личного кабинета пользователя (Remna Dark, 1440×900). Сняты на локальном тестовом стенде v28.9.0 по профилю `.env.test.example`: sandbox-платежи, без Telegram и Remnawave, данные созданы `scripts/sandbox-e2e.sh`. Поэтому серверы Remnawave на снимках недоступны, а суммы и клиенты тестовые. Файлы лежат в [`screenshots/admin_panel/`](screenshots/admin_panel/) (60 шт.) и [`screenshots/storefront_user/`](screenshots/storefront_user/) (20 шт.).

| Админ-панель | Личный кабинет |
| --- | --- |
| ![Главная админ-панели](screenshots/admin_panel/02_dashboard.png) | ![Обзор кабинета](screenshots/storefront_user/03_overview.png) |
| ![Платежи](screenshots/admin_panel/10_payments.png) | ![Тарифы](screenshots/storefront_user/04_plans.png) |

### Админ-панель

Порядок совпадает с боковым меню панели. Разверните группу, чтобы увидеть снимки.

<details>
<summary><b>Вход</b> (1)</summary>

**Вход в панель** — Форма входа администратора: email и пароль, вход по ключу доступа (passkey), переключатели темы и языка.

![Вход в панель](screenshots/admin_panel/01_login.png)

</details>

<details>
<summary><b>Обзор</b> (4)</summary>

**Главная** — Сводка магазина: плашка состояния, плитки «Пользователи», «Активные подписки», «Выручка · 30 дней», «Ошибки выдачи», строка ключевых метрик, список серверов с поиском и фильтром, состояние API, PostgreSQL, Redis и Remnawave.

![Главная](screenshots/admin_panel/02_dashboard.png)

**Аналитика продаж** — Выручка и количество оплат за периоды, конверсия и распределение по тарифам.

![Аналитика продаж](screenshots/admin_panel/03_analytics.png)

**Состояние системы** — Проверки компонентов платформы: API, база данных, Redis, очереди, внешние интеграции.

![Состояние системы](screenshots/admin_panel/04_health.png)

**Инциденты** — Журнал инцидентов с уровнем важности и статусом обработки.

![Инциденты](screenshots/admin_panel/05_incidents.png)

</details>

<details>
<summary><b>Продажи</b> (10)</summary>

**Тарифы** — Список тарифов с ценой, сроком, лимитами трафика и устройств; создание и редактирование.

![Тарифы](screenshots/admin_panel/06_plans.png)

**Конструктор тарифов** — Сборка тарифа из параметров: устройства, трафик, срок, серверы; правила расчёта цены.

![Конструктор тарифов](screenshots/admin_panel/07_constructor.png)

**Пакеты трафика** — Создание пакетов докупки трафика к действующей подписке.

![Пакеты трафика](screenshots/admin_panel/08_traffic_packages.png)

**Изменения подписок** — Смена тарифов и докупка трафика, правила возврата при изменении подписки.

![Изменения подписок](screenshots/admin_panel/09_subscription_operations.png)

**Платежи** — Таблица платежей с провайдером, суммой, статусом оплаты и выдачи, поиском и страницами.

![Платежи](screenshots/admin_panel/10_payments.png)

**Платёжные агенты** — Подключённые провайдеры (YooKassa, RollyPay, Platega, sandbox), их состояние и метрики попыток и успешных оплат.

![Платёжные агенты](screenshots/admin_panel/11_providers.png)

**Финансовый журнал** — Двойная запись операций: оплаты, возвраты, движения кошелька с датой и суммой.

![Финансовый журнал](screenshots/admin_panel/12_financial.png)

**Возвраты** — Очередь возвратов и их статусы.

![Возвраты](screenshots/admin_panel/13_refunds.png)

**Реферальные выплаты** — Заявки на выплату реферального вознаграждения, подтверждение и отклонение.

![Реферальные выплаты](screenshots/admin_panel/14_payouts.png)

**Подарки** — Подарочные коды и подарочные подписки: выпуск и список.

![Подарки](screenshots/admin_panel/15_gifts.png)

</details>

<details>
<summary><b>Клиенты</b> (5)</summary>

**Клиенты магазина** — Поиск клиента по ID, Telegram, email или имени; таблица клиентов с переходом в карточку.

![Клиенты магазина](screenshots/admin_panel/16_crm.png)

**Импорт и массовые операции** — Перенос клиентов из users.db с маппингом и предпросмотром, массовые действия с предпросмотром.

![Импорт и массовые операции](screenshots/admin_panel/17_customer_operations.png)

**Пользователи VPN** — Пользователи на стороне Remnawave. На локальном стенде без Remnawave раздел показывает ошибку загрузки — это ожидаемо.

![Пользователи VPN](screenshots/admin_panel/18_users.png)

**Устройства** — Устройства клиентов, привязанные к подпискам.

![Устройства](screenshots/admin_panel/19_devices.png)

**Обращения клиентов** — Тикеты поддержки с перепиской и ответами операторов.

![Обращения клиентов](screenshots/admin_panel/20_support.png)

</details>

<details>
<summary><b>Инфраструктура</b> (8)</summary>

**Серверы** — Мониторинг узлов Remnawave: статус, нагрузка, онлайн.

![Серверы](screenshots/admin_panel/21_nodes.png)

**Сеть узлов: ASN и репутация** — ASN, владелец сети, префикс, страна RIR и репутация IP узлов с отметкой свежести кэша.

![Сеть узлов: ASN и репутация](screenshots/admin_panel/22_network_intel.png)

**Маршрутизация** — Smart Routing: правила выбора сервера и проверка маршрутизации.

![Маршрутизация](screenshots/admin_panel/23_routing.png)

**Антиабуз и агенты** — Модули платформы, правила антиабуза и агенты на узлах.

![Антиабуз и агенты](screenshots/admin_panel/24_platform.png)

**Автоматизация** — Automation Center и менеджер кампаний.

![Автоматизация](screenshots/admin_panel/25_automation.png)

**Мониторинг** — Состояние мониторинга и рабочих процессов платформы.

![Мониторинг](screenshots/admin_panel/26_monitoring.png)

**Фоновые процессы** — Воркеры, их роль, последний heartbeat и статус.

![Фоновые процессы](screenshots/admin_panel/27_workers.png)

**Очередь задач** — Фоновые задачи с типом, статусом и временем выполнения.

![Очередь задач](screenshots/admin_panel/28_jobs.png)

</details>

<details>
<summary><b>Настройка магазина</b> (11)</summary>

**Новости и страницы** — Редактор новостей, лендингов и юридических страниц с версиями, предпросмотром и публикацией.

![Новости и страницы](screenshots/admin_panel/29_pages.png)

**Меню бота и Mini App** — Брендинг бота, изображение /start, меню Telegram, изображения меню и настройки Mini App.

![Меню бота и Mini App](screenshots/admin_panel/30_content.png)

**Дерево кнопок** — Вложенные меню Telegram и Mini App до четырёх уровней со стилями и custom emoji.

![Дерево кнопок](screenshots/admin_panel/31_menu_tree.png)

**Личный кабинет** — Вкладки кабинета пользователя и инструкции подключения для Android, iOS, TV и компьютеров.

![Личный кабинет](screenshots/admin_panel/32_cabinet.png)

**Android и iOS** — Мобильные приложения клиента и администратора: сборки и параметры распространения.

![Android и iOS](screenshots/admin_panel/33_apps.png)

**Акции и рассылки** — Акции, промокоды и рассылки.

![Акции и рассылки](screenshots/admin_panel/34_marketing.png)

**Группы и предложения** — Промогруппы и персональные предложения для выбранных клиентов.

![Группы и предложения](screenshots/admin_panel/35_offers.png)

**Опросы** — Создание опросов с вопросами, вознаграждением и сроками.

![Опросы](screenshots/admin_panel/36_surveys.png)

**Конкурсы и призы** — Конкурсы и колесо призов: правила, бюджет, розыгрыш.

![Конкурсы и призы](screenshots/admin_panel/37_giveaways.png)

**Уведомления** — Каналы уведомлений, push-провайдеры и журнал доставки.

![Уведомления](screenshots/admin_panel/38_notifications.png)

**Оформление** — Название, логотип, цвета и тема интерфейсов.

![Оформление](screenshots/admin_panel/39_branding.png)

</details>

<details>
<summary><b>Безопасность</b> (8)</summary>

**Защита и 2FA** — Двухфакторная аутентификация и параметры защиты панели.

![Защита и 2FA](screenshots/admin_panel/40_security.png)

**Ключи доступа** — Регистрация и список passkey администратора.

![Ключи доступа](screenshots/admin_panel/41_passkeys.png)

**Сессии** — Активные сессии администраторов с возможностью отзыва.

![Сессии](screenshots/admin_panel/42_sessions.png)

**Роли и администраторы** — Добавление администраторов и назначение ролей.

![Роли и администраторы](screenshots/admin_panel/43_admins.png)

**Антифрод** — Сигналы риска по платежам и решения проверки.

![Антифрод](screenshots/admin_panel/44_fraud.png)

**Журнал действий** — Аудит действий администраторов.

![Журнал действий](screenshots/admin_panel/45_audit.png)

**Резервные копии** — Расписание и хранение резервных копий, создание копии вручную.

![Резервные копии](screenshots/admin_panel/46_backups.png)

**Восстановление** — Центр восстановления и аварийный режим.

![Восстановление](screenshots/admin_panel/47_recovery.png)

</details>

<details>
<summary><b>Обслуживание</b> (13)</summary>

**Диагностика** — Проверка готовности к production и диагностика компонентов.

![Диагностика](screenshots/admin_panel/48_operations.png)

**Настройки без перезапуска** — Live-параметры с шифрованием, историей и откатом. На локальном стенде с http-адресом раздел показывает ошибку валидации public_base_url — это ожидаемо.

![Настройки без перезапуска](screenshots/admin_panel/49_runtime_settings.png)

**Плагины** — Доверенные издатели, установка подписанных пакетов плагинов и права.

![Плагины](screenshots/admin_panel/50_plugins.png)

**Обновления** — Текущая версия и история релизов, проверка обновлений.

![Обновления](screenshots/admin_panel/51_releases.png)

**Функции и модули** — Включение и отключение функций магазина.

![Функции и модули](screenshots/admin_panel/52_features.png)

**Проверка платежей** — Настройки staging E2E и проверка платёжного контура.

![Проверка платежей](screenshots/admin_panel/53_staging.png)

**Развёртывания** — История развёртываний.

![Развёртывания](screenshots/admin_panel/54_deployments.png)

**Корпоративный контур** — Мониторинг 24/7, кампании и правила корпоративного контура.

![Корпоративный контур](screenshots/admin_panel/55_enterprise.png)

**Планирование мощности** — Прогноз нагрузки и рекомендации по узлам.

![Планирование мощности](screenshots/admin_panel/56_capacity.png)

**Оркестратор** — Конфигурация оркестратора узлов.

![Оркестратор](screenshots/admin_panel/57_orchestrator.png)

**Рекомендации** — Автоматические рекомендации по магазину.

![Рекомендации](screenshots/admin_panel/58_intelligence.png)

**Support Pro** — Интеграция с центром поддержки Support Pro.

![Support Pro](screenshots/admin_panel/59_support_pro.png)

**Быстрый поиск** — Командная палитра из верхней панели (⌘K) для перехода к любому разделу.

![Быстрый поиск](screenshots/admin_panel/60_top_command_search.png)

</details>

### Личный кабинет пользователя

Вход, регистрация, оформление заказа и все разделы бокового меню кабинета.

<details>
<summary><b>Все разделы кабинета</b> (20)</summary>

**Вход** — Главная страница кабинета: блок приложений Android и iOS, вход по email и паролю, вход через Telegram.

![Вход](screenshots/storefront_user/01_login.png)

**Регистрация** — Регистрация нового пользователя: имя, email и пароль.

![Регистрация](screenshots/storefront_user/02_register.png)

**Обзор** — Статус подписки, срок действия, остаток трафика и устройства, QR-код и ссылка быстрого подключения, кошелёк, реферальный баланс и код приглашения.

![Обзор](screenshots/storefront_user/03_overview.png)

**Тарифы** — Карточки тарифов, выбор подписки для продления, промокод и провайдер оплаты, оплата картой или с баланса.

![Тарифы](screenshots/storefront_user/04_plans.png)

**Оформление заказа** — Результат тестовой оплаты: подписка активирована и продлена, кабинет показывает новый срок.

![Оформление заказа](screenshots/storefront_user/05_checkout_success.png)

**Пробный период** — Активация бесплатного пробного периода.

![Пробный период](screenshots/storefront_user/06_trial.png)

**Подключение** — Ссылка подписки и QR-код, пошаговые инструкции для Android, iOS, TV, Windows, macOS и Linux.

![Подключение](screenshots/storefront_user/07_connection.png)

**Серверы** — Статус серверов. На стенде без Remnawave список пуст.

![Серверы](screenshots/storefront_user/08_servers.png)

**Поддержка** — Создание обращения и список своих обращений.

![Поддержка](screenshots/storefront_user/09_support.png)

**Устройства** — Устройства, подключённые к подписке, и рекомендуемый сервер.

![Устройства](screenshots/storefront_user/10_devices.png)

**Партнёрский кабинет** — Раздел для партнёров магазина.

![Партнёрский кабинет](screenshots/storefront_user/11_partner.png)

**Кошелёк** — Баланс, пополнение, активация подарочной карты и история операций кошелька.

![Кошелёк](screenshots/storefront_user/12_wallet.png)

**Моя подписка** — Подписки пользователя, статус, автопродление, смена тарифа и дополнительный трафик.

![Моя подписка](screenshots/storefront_user/13_subscription.png)

**Платежи** — История платежей и PDF-квитанции.

![Платежи](screenshots/storefront_user/14_payments.png)

**Подарки** — Активация подарочного кода и покупка подписки в подарок.

![Подарки](screenshots/storefront_user/15_gifts.png)

**Реферальная программа** — Начисления, код приглашения, реферальная сеть по уровням и заявка на выплату.

![Реферальная программа](screenshots/storefront_user/16_referral.png)

**Уведомления** — Уведомления об оплатах и активации подписки.

![Уведомления](screenshots/storefront_user/17_notifications.png)

**Безопасность** — Профиль, привязанные способы входа, подтверждение email, смена пароля, ключи доступа, объединение аккаунтов и сессии.

![Безопасность](screenshots/storefront_user/18_security.png)

**Опросы** — Опубликованные опросы для пользователя.

![Опросы](screenshots/storefront_user/19_surveys.png)

**Конкурсы и призы** — Участие в конкурсах и результаты.

![Конкурсы и призы](screenshots/storefront_user/20_giveaways.png)

</details>

## Начать работу

Для проверки без настоящих касс, Telegram и Remnawave нужны Docker Engine, Compose и Python 3:

```bash
git clone --branch v28.9.0 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
bash scripts/test-up.sh
```

Скрипт создаст `.env.test`, покажет параметры входа и адреса тестовых интерфейсов. Пароли не публикуйте. [Подробная проверка](docs/ru/TESTING.md).

Установка на VDS через SSH или Termius:

```bash
git clone --branch v28.9.0 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
sudo bash deploy/install-vps.sh
```

Сначала прочитайте [установку на VDS](docs/ru/DEPLOYMENT_CURRENT.md). Нужны DNS-записи для выбранных доменов, открытые 80/443, токен Telegram и доступ к Remnawave. Установщик запрашивает значения интерактивно. Перед эксплуатацией проверьте выпуск на отдельном стенде; стабильный канал не означает допуск production-платежей. Автообновление существующего production-сервера остаётся на стабильных выпусках.

## Руководства по каждой функции

| Задача | Руководство |
| --- | --- |
| Создать конкурс или колесо призов | [Правила, бюджет, розыгрыш и приватность](docs/ru/WORKSPACE_GIVEAWAYS.md) |
| Прочитать результаты текущего выпуска | [Отчёт v28.9.0](docs/ru/RELEASE_V28_9_0.md) |
| Изменить операционные параметры без restart | [Live-config, секреты, откат и deployment-границы](docs/ru/RUNTIME_SETTINGS_CURRENT.md) |
| Объединить два своих аккаунта | [Подтверждение, конфликты, перенос и диагностика](docs/ru/ACCOUNT_MERGE_CURRENT.md) |
| Восстановить пароль и подтвердить email | [Почта и безопасность аккаунта](docs/ru/WORKSPACE_ACCOUNT_SECURITY.md) |
| Создать изолированный стенд через Termius | [Проверка перед финальным релизом](docs/ru/FINAL_RELEASE_READINESS.md) |
| Пользоваться всеми страницами кабинета | [Кабинет пользователя: пошагово](docs/ru/WORKSPACE_USER_GUIDE.md) |
| Настроить магазин, тарифы и продажи | [Администратор: по каждому разделу](docs/ru/WORKSPACE_ADMIN_GUIDE.md) |
| Сменить тариф, докупить трафик или вернуть заказ | [Изменения подписки](docs/ru/WORKSPACE_COMMERCE.md) |
| Подключить три платёжных агента | [Оплата](docs/ru/WORKSPACE_PAYMENTS.md) |
| Обновить существующий сервер и миграции | [Обновление и проверка](docs/ru/WORKSPACE_UPGRADE.md) |
| Посмотреть точные API и права | [Каталог API](docs/API_ENDPOINTS.md), [архитектура](docs/ru/WORKSPACE_ARCHITECTURE.md) |
| Проверить полноту переноса функций | [Карта покрытия](docs/ru/WORKSPACE_COVERAGE.md), [критерии завершения](docs/ru/MATRIX_COMPLETION_21_5_1.md) |
| Собрать Android/iOS | [Мобильные приложения](docs/ru/MOBILE_GUIDE.md), [мобильный выпуск](docs/ru/MOBILE_RELEASE_2_14_1.md) |
| Настроить Telegram-бот | [Инструкция администратора](docs/ru/WORKSPACE_ADMIN_GUIDE.md#telegram-бот) |
| Найти инструкции по эксплуатации | [Указатель](docs/INDEX.md), [операционный регламент](OPERATIONS_RUNBOOK_RU.md) |

## Как устроена оплата

Создание счёта, подтверждение оплаты и выдача VPN — три отдельных состояния. Переход браузера после оплаты не подтверждает платёж. Сервер проверяет сумму, валюту и заказ через провайдера, а повтор запроса или вебхука не должен повторно списывать деньги или выдавать доступ.

Список доступных касс зависит от настроенных ключей, включения агента и его состояния. Полный staging E2E v2 ещё не реализован в прежнем ядре: реальные платежи остаются закрытыми. Эта переработка не обходит production gate. [Точные ограничения](docs/ru/WORKSPACE_PAYMENTS.md).

## Проверка исходников

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-test.txt
APP_ENV=test APP_SECRET=test-only-secret PYTHONPATH=backend .venv/bin/python -m pytest -q tests
cd admin
npm ci
npm run typecheck
npm run build
cd ../cabinet
npm ci
npm run typecheck
npm test
npm run build
cd ../miniapp
npm run build          # кабинет с NEXT_PUBLIC_SURFACE=miniapp
cd ../admin
NEXT_BASE_PATH=/cabinet npm run build --prefix ../cabinet
npx playwright test    # Chromium под production CSP
```

Интерфейсы — Next.js (static export в `dist/`). Mini App — это кабинет, собранный с `NEXT_PUBLIC_SURFACE=miniapp`: `miniapp/` делегирует сборку в `cabinet`, в контейнере Mini App собирается из `cabinet`. Для разработки: `npm run dev` в `admin` (порт 5173) или `cabinet` (порт 5174), API — через `NEXT_PUBLIC_API_URL`. Полная проверка Docker, PostgreSQL и мобильных сборок выполняется CI; локальные сборки интерфейса и тесты не заменяют платёжный E2E на сервере.

## Лицензия 2.8

[LICENSE](LICENSE) разрешает бесплатное использование и изменение проекта для собственного магазина, включая коммерческую работу и сборку мобильных клиентов. Соблюдайте условия распространения, изложенные в лицензии. Код запрошенных сторонних проектов в этой переработке не включён; функции реализуются в существующем ядре. Рекламных ссылок на эти проекты в интерфейсах нет. [Сторонние компоненты и уведомления](THIRD_PARTY_NOTICES.md).

Подробные правила новых подписок и подарков: [инструкция](docs/ru/WORKSPACE_SUBSCRIPTIONS.md).

## Выпуск v28.9.0

Релиз v28.9.0 добавляет сетевую аналитику узлов (миграция `0068_network_intel`): для адресов узлов Remnawave показываются ASN, владелец сети, префикс и страна RIR (RIPEstat) и репутация IP (AbuseIPDB при наличии ключа) с кэшем, отметкой свежести, учётом лимитов источников и предупреждениями; внутренние адреса наружу не отправляются, IPv6 поддерживается — строка матрицы «Расширенная DNS/ASN/reputation карта» закрыта ([регламент](docs/ru/NETWORK_INTEL_CURRENT.md)). Релиз v28.8.0 добавил среду плагинов (миграция `0067_plugin_runtime`): плагин — внешний HTTPS-сервис с подписанным пакетом-манифестом; администратор доверяет ключу издателя и подтверждает права, плагин получает подписанные события и API только с разрешёнными правами, версии обновляются и откатываются без перезапуска, при сбоях плагин останавливается автоматически — строка матрицы «Plugin runtime/hotload» закрыта ([регламент](docs/ru/PLUGINS_CURRENT.md)). Релиз v28.7.0 добавил email-канал поддержки (Support Pro 3.7, миграция `0007`): письма клиентов по IMAP становятся обращениями без дублей, ответы операторов уходят письмом с сохранением цепочки, автоответы и возвраты не открывают обращений, есть удаление данных клиента и срок хранения — строка матрицы «Внешние helpdesk/email каналы» закрыта для email ([регламент](docs/ru/SUPPORT_EMAIL_CHANNEL_CURRENT.md)). Релиз v28.6.0 добавил виджет подписки на рабочий стол Android и несколько профилей магазинов в админ-приложениях Android и iOS — строка матрицы «Native push/widget/multiprofile» закрыта ([регламент](docs/ru/WIDGET_AND_PROFILES_CURRENT.md)). Релиз v28.5.0 добавил нативные push-уведомления в приложения Android (FCM) и iOS (APNs): включение по согласию клиента, токен привязан к сессии входа и отзывается при выходе, потерянные токены отключаются автоматически, в админке — состояние провайдеров и доставки ([регламент](docs/ru/PUSH_NOTIFICATIONS_CURRENT.md)). Релиз v28.4.0 перевёл админ-панель, кабинет и Mini App на Next.js (static export, прежние nginx-образы) в дизайне Remna Dark и закрыл строку матрицы «Исторический импорт VPN/платежей»: версионированный адаптер, preview без записи, сверка с контрольными итогами, повтор без дублей и журнал отката ([регламент](docs/ru/HISTORY_IMPORT_CURRENT.md)). Runtime/API остаётся `21.5.1`, схема магазина обновляется до `0067_plugin_runtime`. Релиз v28.3.0 закрыл «70+ настроек с hot-reload и шифрованием». Внешние проверки и production gate остаются открытыми. [Заметки выпуска v28.9.0](docs/ru/RELEASE_V28_9_0.md).

Импорт users.db и массовые операции доступны роли admin в «Клиенты → Импорт и массовые операции». Порядок mapping, preview, применения и границы переноса: [инструкция](docs/ru/CUSTOMER_OPERATIONS_CURRENT.md).

В v21.3.0 добавлены [редакторы новостей, лендингов и юридических страниц](docs/ru/CONTENT_PUBLISHING_CURRENT.md), [промогруппы и персональные офферы](docs/ru/PERSONAL_OFFERS_CURRENT.md), пять previewed массовых действий включая ограничение/восстановление доступа в магазин.

В v21.4.0 добавлены [вложенные меню Telegram и Mini App](docs/ru/MENU_TREE_CURRENT.md): папки до четырёх уровней, стили, custom emoji, безопасные миниатюры и предпросмотр.

В v21.5.0 исправлена [синхронизация истории Support Pro после merge/split](docs/ru/SUPPORT_REMOTE_HISTORY_CURRENT.md): сообщения и файлы сохраняют идентичность, исходная очередь блокируется, внутренние заметки остаются на месте.
