<div align="center">

# 🐶 VPN Shop by Corgi

**Магазин VPN-подписок под ключ для собственной панели Remnawave:**
Telegram-бот и Mini App, личный кабинет, админ-панель, поддержка, приложения Android и iOS.

[![CI](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/ci.yml)
[![Docker](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/docker.yml/badge.svg?branch=main)](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/docker.yml)
[![Release](https://img.shields.io/github/v/release/booarkz-cpu/shop-by-boo?display_name=tag&color=3b82f6)](https://github.com/booarkz-cpu/shop-by-boo/releases/latest)
[![License](https://img.shields.io/badge/license-Corgi%20Lusi%202.8-FF8A1F)](LICENSE)

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?logo=fastapi&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3.31-2CA5E0?logo=telegram&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5.9%20strict-3178C6?logo=typescript&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18.6-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7.4-DC382D?logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker%20Compose-ready-2496ED?logo=docker&logoColor=white)
![Remnawave](https://img.shields.io/badge/Remnawave-3.x-7c3aed)

[🚀 Быстрый старт](#-быстрый-старт) · [🏗 Архитектура](#-архитектура) · [⚙️ Переменные окружения](#️-переменные-окружения) · [📸 Скриншоты](#-скриншоты) · [📚 Документация](#-документация)

</div>

---

> **v28.23.0** — текущий стабильный выпуск. Runtime/API `21.5.1`, миграция магазина `0075_app_config`, Support Pro `0008` / 3.8.
> Тег выпуска и версия API — разные числа намеренно: устанавливается `v28.23.0`, `/health` отвечает `21.5.1`.
> Точная карта готовности: [покрытие](docs/ru/WORKSPACE_COVERAGE.md) · [критерии завершения](docs/ru/MATRIX_COMPLETION_21_5_1.md) · [CHANGELOG](CHANGELOG.md).

**Начните здесь:** [руководство по запуску](docs/ru/LAUNCH_GUIDE.md) (от сервера до первой продажи) и [инструкции по 30 модулям](docs/ru/modules/README.md).

## ✨ Возможности

| | |
| --- | --- |
| 🤖 **Telegram-бот** | `/start` с меню из конструктора кнопок, `/buy`, `/subscription`, `/promo`, `/account`, `/balance`, `/payments`, `/gifts`, `/referral`, `/support`, `/devices`; баннеры разделов с корги Люси или свои; рассылки с учётом лимитов Telegram |
| 📱 **Mini App** | Строится из данных `GET /api/app-config`: тема, меню, баннеры с корги Люси, акции с таймером, серверы по категориям с флагами, пополнение (СБП, карта, крипта, Telegram Stars), рефералы, поддержка, документы и согласие с офертой. Скелетоны при загрузке, работа без сети на сохранённом конфиге |
| 🧑‍💻 **Личный кабинет** | Вход по email, Telegram, OAuth и passkey; несколько подписок, смена тарифа, докупка трафика, кошелёк, подарки, рефералы, устройства, обращения |
| 🛠 **Админ-панель** | 60+ разделов: клиенты, тарифы и конструктор, платежи и возвраты, маркетинг, автоматизация, узлы и антиабуз, почта, плагины, 2FA и роли, копии |
| 💳 **Оплата** | ЮKassa, Platega, RollyPay и внутренний кошелёк. Подтверждение только после сверки с провайдером, идемпотентные webhook, финансовый журнал, возвраты с отзывом доступа |
| 🛰 **Remnawave** | Выдача, продление, смена тарифа, трафик, Internal Squads, лимит устройств HWID, отзыв доступа; совместимо с API 3.x |
| ⚡ **Автоматизация** | Правила «событие → условие → действие» (уведомления, Telegram, бонус на баланс) и кампании по расписанию |
| 🛡 **Защита** | Антифрод платежей, антиабуз подключений с агентами узлов, распознавание торрентов и DPI, 2FA, passkeys, аудит, CSP |
| 💬 **Поддержка** | Встроенный Support Pro: обращения из бота, кабинета и email, мост Zendesk/Freshdesk |
| 📈 **Эксплуатация** | Prometheus-метрики, состояние системы, фоновые процессы, резервные копии с двойным подтверждением восстановления, обновление из GitHub |

## 🏗 Архитектура

```mermaid
flowchart LR
    U["👤 Клиент"] --> TG["Telegram"]
    TG -->|"long polling"| BOT["🤖 bot<br/>aiogram 3"]
    TG -->|"WebApp initData"| MA["📱 miniapp<br/>Next.js"]
    U --> CAB["🧑‍💻 cabinet<br/>Next.js"]
    ADM["🛠 admin<br/>Next.js"] --> CADDY
    MA --> CADDY["🔒 Caddy<br/>TLS, 5 доменов"]
    CAB --> CADDY
    CADDY --> API["⚙️ backend<br/>FastAPI"]
    BOT --> DB
    API --> DB[("PostgreSQL 18")]
    API --> R[("Redis 7")]
    W["🔁 worker<br/>выдача, автопродление,<br/>автоматизация, копии"] --> DB
    W --> R
    API <-->|"REST API"| RW["🛰 Remnawave"]
    W <-->|"REST API"| RW
    PAY["💳 ЮKassa · Platega · RollyPay"] -->|"webhook"| CADDY
    API --> PAY
    AG["🖥 node-agent<br/>на VPN-узлах"] -->|"метрики, наблюдения"| CADDY
    CADDY --> SP["💬 Support Pro"]
```

| Сервис (`docker-compose.yml`) | Что делает |
| --- | --- |
| `backend` | API магазина: авторизация, кабинет, админка, платежи и webhook, выдача в Remnawave |
| `worker` | Тот же код в роли фоновых процессов: очередь выдачи, повторы, автопродление, напоминания, автоматизация и кампании, сверка возвратов, копии, мониторинг |
| `bot` | Telegram-бот на aiogram 3 (long polling) и очередь рассылок с соблюдением flood control |
| `admin`, `cabinet`, `miniapp` | Статические сборки Next.js за nginx |
| `db`, `redis` | PostgreSQL 18 и Redis 7.4 магазина |
| `support_pro`, `support_worker`, `support_db`, `support_redis` | Встроенная служба поддержки |
| `caddy` | HTTPS для API, админки, кабинета, Mini App и Support Pro |
| `mail_receiver` (профиль `mail`) | Необязательный приём почты для служебных адресов |

**Стек.**
- Backend: Python 3.12, FastAPI 0.141, SQLAlchemy 2.0 (async, asyncpg), Alembic 1.18, Pydantic 2, httpx, aiogram 3.31.
- Frontend: Next.js 16, React 19, TypeScript 5.9 strict, Tailwind CSS 4, shadcn/Radix.
- Мобильные приложения: Kotlin (Android) и Swift (iOS).
- База данных: PostgreSQL 18.6 (магазин и Support Pro), Redis 7.4.
- Инфраструктура: Docker Compose, Caddy, GitHub Actions (CI, Docker, выпуски, мобильные сборки).

### 📱 Mini App на данных

Mini App не содержит зашитых текстов, цветов, меню и картинок разделов: всё приходит одним JSON.

```mermaid
flowchart LR
    TG["Telegram.WebApp.initData"] --> HOOK["useAppConfig()<br/>AppConfigProvider"]
    HOOK -->|"GET /api/app-config<br/>X-Telegram-Init-Data"| API["backend<br/>app_config.py"]
    API --> SRC["тарифы, акции, реклама,<br/>меню кабинета, страницы,<br/>платёжные агенты, баннеры"]
    ADMIN["Админка → Конфигурация Mini App"] -->|"PUT /api/admin/app-config"| API
    HOOK -. "нет сети" .-> CACHE["последний конфиг<br/>(localStorage)"]
    CACHE -. "пусто" .-> MOCK["mock-config.json"]
```

| Часть конфига | Что задаёт | Где меняется |
| --- | --- | --- |
| `theme.vars` | Неоновый акцент, фон, карточки, текст, скругления (CSS-переменные) | Конфигурация Mini App → Тема |
| `navigation`, `banners` | Разделы, иконки и баннер каждого раздела | Личный кабинет, Баннеры бота |
| `promos` | Карточки акций: текст, скидка, таймер, кнопка | Акции на тарифы, реклама, свои карточки |
| `servers.categories` | Группы серверов по странам или словам в имени, флаги | Конфигурация Mini App → Категории |
| `wallet` | Кнопки сумм, способы оплаты (СБП, карта, крипта, Stars), курс Stars | Конфигурация Mini App → Кошелёк |
| `referral`, `support` | Условия программы, вывод средств, кнопки связи, форма обращения | Конфигурация Mini App |
| `info`, `consent` | FAQ, правила, конфиденциальность, оферта; согласие перед оплатой | Публикации + Конфигурация Mini App |
| `texts` | Все подписи интерфейса | Конфигурация Mini App → Тексты |

Загрузка: сначала последний сохранённый конфиг (мгновенный показ), затем сеть; пока конфига нет — скелетоны; без сети — плашка «Нет связи» и кнопка «Повторить». Подробно — [модуль 14](docs/ru/modules/14-bot-miniapp.md#mini-app-на-данных).

## 🚀 Быстрый старт

### Установка на VDS одной командой

Нужен чистый сервер на Ubuntu 24.04 или Debian 12: 4 vCPU, 8 ГБ RAM, 40 ГБ диска. Нужны и DNS-записи A для пяти доменов: `api`, `admin`, `app`, `cabinet`, `support`.

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v28.23.0/install.sh -o /root/shop-install.sh \
  && BRANCH=v28.23.0 bash /root/shop-install.sh
```

Установщик сам ставит Docker, спрашивает домены, токены и цены, создаёт `.env` со случайными секретами, собирает и запускает сервисы. После установки:

```bash
cd /opt/vpn-shop
docker compose ps                         # все сервисы running/healthy
curl -fsS https://api.ДОМЕН/health/ready  # {"ok": true, ...}
bash scripts/doctor.sh                    # сводная проверка
```

Дальше откройте `https://admin.ДОМЕН`, включите 2FA и пройдите шаги [руководства по запуску](docs/ru/LAUNCH_GUIDE.md).

### Ручная установка через Docker Compose

```bash
git clone --branch v28.23.0 https://github.com/booarkz-cpu/shop-by-boo.git /opt/vpn-shop
cd /opt/vpn-shop
cp .env.example .env
# Заполните .env: секреты, домены, BOT_TOKEN, REMNAWAVE_*, ключи провайдеров (см. таблицу ниже)
docker compose up -d --build
docker compose exec -T backend alembic upgrade head
docker compose ps
```

### Переход на PostgreSQL 18

Начиная с v28.23.0 магазин и Support Pro работают на PostgreSQL 18. Обычное обновление (`scripts/update-from-github.sh`) само переносит данные: `scripts/upgrade-postgres.sh` останавливает сервисы, снимает дамп со старой базы PostgreSQL 16, восстанавливает его в PostgreSQL 18 на новом томе и сверяет количество строк в каждой таблице. Старый том `postgres_data` не удаляется — он нужен для отката. Перед обновлением сделайте резервную копию: `bash scripts/backup.sh`.

### Локальный стенд без касс, Telegram и Remnawave

```bash
git clone --branch v28.23.0 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
bash scripts/test-up.sh   # создаст .env.test, покажет адреса и вход
```

Обновление существующей установки: `bash scripts/backup.sh`, затем `sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.23.0 bash /opt/vpn-shop/scripts/update-from-github.sh` ([регламент](docs/ru/DISTRIBUTION_UPGRADE_CURRENT.md)).

## ⚙️ Переменные окружения

Полный список с комментариями — [`.env.example`](.env.example). Большинство операционных параметров меняются без перезапуска в **Система → Настройки без перезапуска** ([реестр](docs/ru/RUNTIME_SETTINGS_CURRENT.md)).

| Переменная | Зачем | Пример |
| --- | --- | --- |
| `APP_ENV` | `production`, `staging` или `test` | `production` |
| `APP_SECRET` | Подпись сессий и шифрование секретов в базе, не меньше 32 символов | `openssl rand -hex 32` |
| `DB_PASSWORD`, `POSTGRES_PASSWORD`, `DATABASE_URL` | Доступ к PostgreSQL магазина | `postgresql+asyncpg://vpnshop:…@db:5432/vpnshop` |
| `REDIS_PASSWORD`, `REDIS_URL` | Redis: блокировки, ограничение запросов, circuit breaker | `redis://:…@redis:6379/0` |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Первый администратор (создаётся при запуске) | `owner@example.com` |
| `API_DOMAIN`, `ADMIN_DOMAIN`, `APP_DOMAIN`, `CABINET_DOMAIN`, `SUPPORT_PRO_DOMAIN` | Домены Caddy | `api.vpn.example.com` |
| `PUBLIC_BASE_URL`, `MINI_APP_URL`, `CABINET_URL` | Публичные адреса API, Mini App и кабинета | `https://app.vpn.example.com` |
| `CADDY_EMAIL` | Почта для сертификатов Let's Encrypt | `owner@example.com` |
| `BOT_TOKEN`, `BOT_USERNAME`, `ADMIN_TELEGRAM_ID` | Telegram-бот и владелец для `/ops` | `123456:ABC…` |
| `REMNAWAVE_URL`, `REMNAWAVE_TOKEN` | Панель Remnawave и её API-токен | `https://panel.example.com` |
| `DEFAULT_CURRENCY`, `PRICE_1/3/6/12` | Валюта и цены стартовых тарифов (создаются выключенными на пустой базе) | `RUB`, `199` |
| `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_WEBHOOK_IP_ALLOWLIST` | ЮKassa | IP-адреса уведомлений ЮKassa |
| `PLATEGA_MERCHANT_ID`, `PLATEGA_SECRET` | Platega | |
| `ROLLYPAY_API_KEY`, `ROLLYPAY_SIGNING_SECRET` | RollyPay | |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Письма: подтверждение email, восстановление пароля | `smtp.provider.example`, `587` |
| `ALERT_TELEGRAM_CHAT_ID` | Куда слать оповещения о сбоях | `-100…` |

Адреса уведомлений у провайдеров: `https://api.ДОМЕН/api/webhooks/yookassa`, `…/platega`, `…/rollypay`. В ЮKassa включите события `payment.succeeded` и `refund.succeeded`: тогда возврат, оформленный в кабинете ЮKassa, тоже отзывает доступ.

## 📸 Скриншоты

### Баннеры разделов бота

Каждый раздел бота приходит с баннером: стандартная картинка с корги Люси или ваша из **Бот и кабинет → Баннеры бота** ([как настроить](docs/ru/modules/14-bot-miniapp.md#баннеры-бота)).

![Стандартные баннеры бота с корги Люси](docs/img/bot-banners-all.jpg)

### Mini App

Настоящие снимки собранного Mini App (390×844) со стандартными баннерами. Обновить: `(cd cabinet && npm run build:miniapp) && node scripts/screenshots/miniapp.mjs`.

| Главная | Пополнение | Рефералы | Поддержка |
| :---: | :---: | :---: | :---: |
| ![Mini App: главная, акции и подписка](docs/img/miniapp-overview.png) | ![Mini App: пополнение баланса](docs/img/miniapp-wallet.png) | ![Mini App: пригласи друзей](docs/img/miniapp-referral.png) | ![Mini App: поддержка](docs/img/miniapp-support.png) |
| **Серверы** | **Информация** | **Тарифы** | |
| ![Mini App: серверы по категориям](docs/img/miniapp-servers.png) | ![Mini App: документы и оферта](docs/img/miniapp-info.png) | ![Mini App: тарифы](docs/img/miniapp-plans.png) | |

### Telegram-бот

Это макеты в SVG, а не снимки экрана. Чтобы заменить макет настоящим скриншотом, положите PNG в [`docs/img/`](docs/img/) и укажите его вместо `.svg`.

| Бот: `/start` и меню | Бот: подписка и промокод |
| :---: | :---: |
| ![Telegram-бот: приветствие и меню](docs/img/bot-start.svg) | ![Telegram-бот: подписка, промокод, поддержка](docs/img/bot-commands.svg) |

Куда класть настоящие скриншоты (имя файла → какая строка таблицы):

| Файл в `docs/img/` | Что снять |
| --- | --- |
| `bot-start.png` | `/start` в Telegram: приветствие и кнопки меню |
| `bot-commands.png` | `/subscription`, `/promo` или `/support` в личном чате |

Положите файл и замените в таблице выше расширение `.svg` на `.png` в пути к картинке.

### Админ-панель и личный кабинет

Ниже настоящие снимки всех разделов админ-панели и кабинета (Remna Dark, 1440×900). Их снимает скрипт [`admin/scripts/screenshots-catalog.mjs`](admin/scripts/screenshots-catalog.mjs) на изолированном тестовом стенде с тестовыми тарифами и sandbox-оплатами. Поэтому серверы Remnawave на снимках недоступны, а суммы и клиенты тестовые. Описание каждого раздела — в [руководстве по админ-панели](docs/ru/ADMIN_PANEL_CURRENT.md).

| Админ-панель | Личный кабинет |
| --- | --- |
| ![Все разделы админ-панели](screenshots/admin_panel/00_all_sections.png) | ![Обзор кабинета](screenshots/storefront_user/03_overview.png) |
| ![Конструктор тарифов](screenshots/admin_panel/14_constructor.png) | ![Тарифы](screenshots/storefront_user/04_plans.png) |

#### Админ-панель

Порядок совпадает с боковым меню панели. Разверните группу, чтобы увидеть снимки.

<details>
<summary><b>Все разделы</b> (1)</summary>

**Все разделы** — Стартовая страница: ключевые показатели и все функции панели по группам с описанием и поиском по задаче.

![Все разделы](screenshots/admin_panel/00_all_sections.png)

</details>

<details>
<summary><b>Вход</b> (1)</summary>

**Вход в панель** — Email и пароль администратора, вход по ключу доступа (passkey), выбор темы и языка.

![Вход в панель](screenshots/admin_panel/01_login.png)

</details>

<details>
<summary><b>Аналитика</b> (5)</summary>

**Главная** — Сводка за сутки и месяц: клиенты, подписки, выручка, серверы и то, что требует внимания.

![Главная](screenshots/admin_panel/02_dashboard.png)

**Аналитика продаж** — Выручка, конверсия, средний чек и динамика продаж по периодам.

![Аналитика продаж](screenshots/admin_panel/03_analytics.png)

**Финансовый журнал** — Неизменяемый журнал всех денежных операций: оплаты, возвраты, бонусы и выплаты.

![Финансовый журнал](screenshots/admin_panel/04_financial.png)

**Состояние системы** — Работают ли API, база данных, Redis, Remnawave и фоновые процессы.

![Состояние системы](screenshots/admin_panel/05_health.png)

**Инциденты** — Сбои и проблемы: открыть инцидент, отметить решение, посмотреть историю.

![Инциденты](screenshots/admin_panel/06_incidents.png)

</details>

<details>
<summary><b>Пользователи</b> (6)</summary>

**Клиенты магазина** — Поиск клиента по ID, Telegram, имени или email и полная карточка: подписка, баланс, платежи, действия.

![Клиенты магазина](screenshots/admin_panel/07_crm.png)

**Пользователи VPN** — Учётные записи в Remnawave: статус, имя пользователя и дата создания.

![Пользователи VPN](screenshots/admin_panel/08_users.png)

**Устройства** — Устройства клиентов (HWID): сколько подключено и какие можно отключить.

![Устройства](screenshots/admin_panel/09_devices.png)

**Импорт и массовые операции** — Перенос клиентов из другого бота и действия сразу над группой клиентов.

![Импорт и массовые операции](screenshots/admin_panel/10_customerOperations.png)

**Обращения клиентов** — Вопросы клиентов из бота и кабинета: ответить, назначить, закрыть.

![Обращения клиентов](screenshots/admin_panel/11_support.png)

**Support Pro** — Состояние отдельного центра поддержки: очереди, операторы, каналы и SLA.

![Support Pro](screenshots/admin_panel/12_supportPro.png)

</details>

<details>
<summary><b>Тарифы и оплата</b> (9)</summary>

**Тарифы** — Готовые тарифы: название, срок, цена, трафик и число устройств.

![Тарифы](screenshots/admin_panel/13_plans.png)

**Конструктор тарифов** — Тариф, который клиент собирает сам: устройства, трафик и срок с ценой за каждый пункт.

![Конструктор тарифов](screenshots/admin_panel/14_constructor.png)

**Пакеты трафика** — Дополнительные гигабайты, которые клиент докупает к действующей подписке.

![Пакеты трафика](screenshots/admin_panel/15_trafficPackages.png)

**Изменения подписок** — Продления, смены тарифа и докупки: что запросил клиент и чем закончилось.

![Изменения подписок](screenshots/admin_panel/16_subscriptionOperations.png)

**Платежи** — Все оплаты клиентов со статусом, суммой и платёжной системой.

![Платежи](screenshots/admin_panel/17_payments.png)

**Платёжные агенты** — Подключённые платёжные системы, их доступность и доля успешных оплат.

![Платёжные агенты](screenshots/admin_panel/18_providers.png)

**Возвраты** — Заявки на возврат денег: проверить, одобрить или отклонить.

![Возвраты](screenshots/admin_panel/19_refunds.png)

**Подарки** — Подарочные коды на подписку: создать код, задать срок и число активаций.

![Подарки](screenshots/admin_panel/20_gifts.png)

**Проверка платежей** — Тестовые оплаты в sandbox платёжных систем перед запуском магазина.

![Проверка платежей](screenshots/admin_panel/21_staging.png)

</details>

<details>
<summary><b>Маркетинг</b> (7)</summary>

**Акции и рассылки** — Скидочные акции, промокоды, рекламные блоки и рассылки в Telegram.

![Акции и рассылки](screenshots/admin_panel/22_marketing.png)

**Группы и предложения** — Группы клиентов по условиям и персональные предложения для каждой группы.

![Группы и предложения](screenshots/admin_panel/23_offers.png)

**Конкурсы и призы** — Розыгрыши и призы: условия участия, победители и выдача наград.

![Конкурсы и призы](screenshots/admin_panel/24_giveaways.png)

**Опросы** — Вопросы клиентам в боте и кабинете и сводка ответов.

![Опросы](screenshots/admin_panel/25_surveys.png)

**Реферальные выплаты** — Заявки партнёров на вывод реферального вознаграждения.

![Реферальные выплаты](screenshots/admin_panel/26_payouts.png)

**Уведомления** — Отправленные клиентам уведомления и состояние push для Android и iOS.

![Уведомления](screenshots/admin_panel/27_notifications.png)

**Новости и страницы** — Новости, инструкции и правовые страницы для бота и кабинета.

![Новости и страницы](screenshots/admin_panel/28_pages.png)

</details>

<details>
<summary><b>Бот и кабинет</b> (5)</summary>

**Меню бота и Mini App** — Тексты бота, кнопки главного меню, экран Mini App и инструкции по подключению.

![Меню бота и Mini App](screenshots/admin_panel/29_content.png)

**Дерево кнопок** — Вложенные меню бота: порядок кнопок, подменю и действия по нажатию.

![Дерево кнопок](screenshots/admin_panel/30_menuTree.png)

**Личный кабинет** — Вкладки веб-кабинета клиента: порядок, названия и собственные страницы.

![Личный кабинет](screenshots/admin_panel/31_cabinet.png)

**Android и iOS** — Приложения магазина: версии, файлы для загрузки и ссылки на сторы.

![Android и iOS](screenshots/admin_panel/32_apps.png)

**Оформление** — Название магазина, логотип, иконка сайта, цвета и тема по умолчанию.

![Оформление](screenshots/admin_panel/33_branding.png)

</details>

<details>
<summary><b>Серверы</b> (9)</summary>

**Серверы** — Узлы Remnawave: онлайн, нагрузка, трафик и число подключённых клиентов.

![Серверы](screenshots/admin_panel/34_nodes.png)

**Сеть узлов: ASN и репутация** — В чьих сетях стоят узлы и не попали ли их адреса в списки злоупотреблений.

![Сеть узлов: ASN и репутация](screenshots/admin_panel/35_networkIntel.png)

**Терминал узлов** — Командная оболочка на VPN-сервере через агент: с подтверждением 2FA и записью сессии.

![Терминал узлов](screenshots/admin_panel/36_nodeTerminal.png)

**Маршрутизация** — Выбор узла для клиента по задержке и нагрузке.

![Маршрутизация](screenshots/admin_panel/37_routing.png)

**Планирование мощности** — Прогноз нагрузки: когда узлам не хватит ресурсов и сколько добавить.

![Планирование мощности](screenshots/admin_panel/38_capacity.png)

**Оркестратор** — Автоматическое включение и вывод узлов по правилам нагрузки.

![Оркестратор](screenshots/admin_panel/39_orchestrator.png)

**Торренты на узлах** — Кто из клиентов качает торренты: счётчики срабатываний Xray без адресов, отметка в антиабузе и уведомление.

![Торренты на узлах](screenshots/admin_panel/40_torrents.png)

**Антиабуз и агенты** — Агенты на узлах, блокировка устройств-нарушителей и вебхуки событий.

![Антиабуз и агенты](screenshots/admin_panel/41_platform.png)

**Мониторинг** — Проверки доступности, версии компонентов и рабочие процессы.

![Мониторинг](screenshots/admin_panel/42_monitoring.png)

</details>

<details>
<summary><b>Система</b> (12)</summary>

**Настройки без перезапуска** — Параметры магазина, платёжных систем и интеграций, которые применяются сразу.

![Настройки без перезапуска](screenshots/admin_panel/43_runtimeSettings.png)

**Функции и модули** — Включение и выключение отдельных возможностей магазина.

![Функции и модули](screenshots/admin_panel/44_features.png)

**Плагины** — Установка подписанных плагинов, их права и журнал работы.

![Плагины](screenshots/admin_panel/45_plugins.png)

**Автоматизация** — Правила «событие → действие» и автоматические кампании.

![Автоматизация](screenshots/admin_panel/46_automation.png)

**Фоновые процессы** — Worker и планировщик: работают ли, когда последний раз отвечали.

![Фоновые процессы](screenshots/admin_panel/47_workers.png)

**Очередь задач** — Фоновые задачи: ожидают, выполняются, завершились ошибкой; повтор вручную.

![Очередь задач](screenshots/admin_panel/48_jobs.png)

**Почтовый домен: SPF, DKIM, DMARC** — Доходят ли письма магазина: DNS-записи домена и отчёты DMARC о том, кто отправляет почту от его имени.

![Почтовый домен: SPF, DKIM, DMARC](screenshots/admin_panel/49_mailDomain.png)

**Диагностика** — Проверка конфигурации, подключений и готовности к работе с подсказками по исправлению.

![Диагностика](screenshots/admin_panel/50_operations.png)

**Обновления** — Установленная версия, доступные выпуски и история обновлений.

![Обновления](screenshots/admin_panel/51_releases.png)

**Развёртывания** — Постепенный выпуск новой версии: доля трафика и ошибки.

![Развёртывания](screenshots/admin_panel/52_deployments.png)

**Корпоративный контур** — Проверки, кампании и правила автоматизации для крупных установок.

![Корпоративный контур](screenshots/admin_panel/53_enterprise.png)

**Рекомендации** — Подсказки по росту продаж и снижению нагрузки на основе данных магазина.

![Рекомендации](screenshots/admin_panel/54_intelligence.png)

</details>

<details>
<summary><b>Безопасность</b> (8)</summary>

**Защита и 2FA** — Двухфакторный вход, смена пароля и правила доступа к панели.

![Защита и 2FA](screenshots/admin_panel/55_security.png)

**Ключи доступа** — Вход в панель по ключу доступа (passkey) вместо пароля.

![Ключи доступа](screenshots/admin_panel/56_passkeys.png)

**Роли и администраторы** — Кто имеет доступ к панели и с какими правами.

![Роли и администраторы](screenshots/admin_panel/57_admins.png)

**Сессии** — Активные входы в панель; завершить чужую или все сессии.

![Сессии](screenshots/admin_panel/58_sessions.png)

**Антифрод** — Подозрительные оплаты и аккаунты: проверить и принять решение.

![Антифрод](screenshots/admin_panel/59_fraud.png)

**Журнал действий** — Кто из администраторов, когда и что изменил.

![Журнал действий](screenshots/admin_panel/60_audit.png)

**Резервные копии** — Расписание и хранение копий базы, ручной запуск и проверка.

![Резервные копии](screenshots/admin_panel/61_backups.png)

**Восстановление** — Восстановление из копии и проверка готовности к аварии.

![Восстановление](screenshots/admin_panel/62_recovery.png)

</details>

<details>
<summary><b>Поиск</b> (1)</summary>

**Быстрый поиск** — Ctrl+K (⌘K) из любого раздела: поиск по названию, описанию и синонимам, переход клавишами.

![Быстрый поиск](screenshots/admin_panel/63_command_search.png)

</details>

#### Личный кабинет пользователя

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

## 💳 Как устроена оплата

1. Клиент выбирает тариф в боте, Mini App или кабинете. Магазин создаёт заказ с ключом идемпотентности и открывает страницу оплаты провайдера.
2. Провайдер присылает webhook. Магазин проверяет подпись или IP и запрашивает статус платежа у провайдера: сумма, валюта и номер заказа должны совпасть.
3. Заказ становится оплаченным, worker выдаёт или продлевает доступ в Remnawave: срок, трафик, Internal Squad, лимит устройств.
4. Повтор webhook ничего не повторяет. Возврат из админки или из кабинета ЮKassa отзывает доступ и записывается в финансовый журнал.

Реальные платежи открыты сразу после установки. На случай сбоя есть аварийная кнопка «Остановить приём платежей». Подробно: [модуль «Платежи»](docs/ru/modules/07-payments.md), [три платёжных агента](docs/ru/WORKSPACE_PAYMENTS.md), [сквозная проверка на стенде](docs/ru/STAGING_E2E_V2_IMPLEMENTATION.md).

## 📚 Документация

| Задача | Где |
| --- | --- |
| Запустить магазин с нуля | [Руководство по запуску](docs/ru/LAUNCH_GUIDE.md) |
| Работать с каждым разделом панели | [30 модулей](docs/ru/modules/README.md) |
| Установка через SSH/Termius, DNS, TLS | [Установка на VDS](docs/ru/DEPLOYMENT_CURRENT.md), [INSTALL_STEPS.md](INSTALL_STEPS.md) |
| Эксплуатация, обновление, сбои | [Регламент](docs/ru/PRODUCTION_CURRENT.md), [обновление](docs/ru/DISTRIBUTION_UPGRADE_CURRENT.md) |
| Резервные копии | [Модуль 30](docs/ru/modules/30-backups-recovery.md), [полная копия](docs/ru/BACKUP_CURRENT.md) |
| API и права | [Каталог API](docs/API_ENDPOINTS.md), [архитектура](docs/ru/WORKSPACE_ARCHITECTURE.md), [карта проекта](docs/PROJECT_MAP_RU.md) |
| Android и iOS | [Мобильные приложения](docs/ru/MOBILE_GUIDE.md), [MOBILE.md](MOBILE.md) |
| Все документы | [DOCUMENTATION.md](DOCUMENTATION.md), [указатель](docs/INDEX.md) |
| English / Українська | [docs/en](docs/en/README.md), [docs/uk](docs/uk/README.md) |

## 🧪 Разработка и проверка

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-test.txt
APP_ENV=test APP_SECRET=test-only-secret PYTHONPATH=backend .venv/bin/python -m pytest -q tests

cd admin && npm ci && npm run typecheck && npm run build
cd ../cabinet && npm ci && npm run typecheck && npm test && npm run build
cd ../admin && NEXT_BASE_PATH=/cabinet npm run build --prefix ../cabinet && npx playwright test   # Chromium под production CSP
```

Тесты с PostgreSQL и Redis включаются переменными `AUDIT_TEST_DATABASE_URL` и `REDIS_URL`. **CI** (`.github/workflows/ci.yml`) поднимает PostgreSQL 18 и Redis 7.4 и выполняет:
- миграции Alembic;
- тесты backend и Support Pro;
- typecheck, сборку и Playwright-проверки интерфейсов;
- сборку Android;
- проверки контейнеров и документации.

`docker.yml` собирает образы. `publish-release.yml` публикует выпуск после слияния в `main`. `mobile-release.yml` прикладывает мобильные пакеты.

Для разработки интерфейсов: `npm run dev` в `admin` (порт 5173) или `cabinet` (порт 5174), адрес API — `NEXT_PUBLIC_API_URL`. Mini App — это кабинет, собранный с `NEXT_PUBLIC_SURFACE=miniapp`.

## 📄 Лицензия

[LICENSE](LICENSE) (Corgi Lusi VPN Shop Source License 2.8) разрешает бесплатно использовать и менять проект для собственного магазина, включая коммерческую работу и сборку мобильных клиентов. Соблюдайте условия распространения из лицензии. [Сторонние компоненты](THIRD_PARTY_NOTICES.md).

## 🗂 История выпусков

Релиз v28.23.0 перевёл базы на PostgreSQL 18.6 (перенос данных PostgreSQL 16 при обновлении со сверкой строк, старый том остаётся для отката) и сделал Mini App управляемым данными: `GET /api/app-config`, редактор «Конфигурация Mini App», баннеры разделов с корги Люси, акции с таймером, категории серверов, пополнение СБП, картой, криптовалютой и Telegram Stars, согласие с офертой. Миграция `0075_app_config` ([заметки](docs/ru/RELEASE_V28_23_0.md)).

Релиз v28.22.0 добавил баннеры разделов бота: 13 стандартных картинок с корги Люси и надписью раздела, свои изображения для каждого раздела и кнопки-папки в «Бот и кабинет → Баннеры бота», смену картинки в том же сообщении при навигации ([модуль 14](docs/ru/modules/14-bot-miniapp.md), [заметки](docs/ru/RELEASE_V28_22_0.md)).

Релиз v28.21.0 запустил движок автоматизации: правила «событие → условия → действия» (истечение подписки, оплата, новый клиент, клиент без покупки) выполняются фоновым процессом один раз на клиента и событие, кампании уходят в очередь рассылок ([модуль 25](docs/ru/modules/25-automation-jobs.md)). Исправлена работа с Remnawave 3.x (обёртка ответов `response`, лимит устройств `hwidDeviceLimit`), ограничение антиабуза стало обратимым, возвраты из кабинета YooKassa (`refund.succeeded`) отзывают доступ, бот не отправляет кнопки Mini App в группах. Миграция `0074_automation_engine` ([заметки](docs/ru/RELEASE_V28_21_0.md)).

Релиз v28.20.0 открыл реальные платежи сразу после установки: отдельного допуска и закрытия через 24 часа больше нет, а кнопка «Остановить приём платежей» остаётся для аварий; проверка staging E2E v2 стала добровольной ([платежи](docs/ru/modules/07-payments.md)).

Релиз v28.19.0 добавил допуск реальных платежей — [staging E2E v2](docs/ru/STAGING_E2E_V2_IMPLEMENTATION.md): отдельный стенд с `APP_ENV=staging` проводит настоящий заказ через обычный checkout и сам проверяет подписанный webhook, сверку с провайдером, выдачу по ID пользователя Remnawave, повтор и подделки webhook, возврат, отзыв доступа и успех после возврата; результат подписывается Ed25519, рабочий сервер принимает его со своим кодом запуска, от той же версии и не старше 24 часов. Миграция `0073_e2e_v2`. В «Антифроде» появились решения по сигналам с заметкой, повторное сканирование не создаёт дубли.

Релиз v28.18.0 полностью обновил инструкции: [руководство по запуску](docs/ru/LAUNCH_GUIDE.md) от сервера до первой продажи и [30 инструкций по модулям](docs/ru/modules/README.md), проверенных по коду. В админке появился редактор тарифов (срок, трафик, устройства, профиль Remnawave из списка Internal Squads), реферальная программа и партнёры перенесены в «Маркетинг → Рефералы и партнёры», выключение аварийного режима снимает технический режим, агент узла может передавать антиабузу адреса подключений из журнала Xray (`AGENT_OBSERVE_ACCESS_LOG=1`).

Релиз v28.17.0 добавил собственный приём почты (сервис `mail_receiver`, профиль `mail`): SMTP-сервер только для служебных адресов — отчёты DMARC попадают в раздел «Почтовый домен», письма на адрес поддержки становятся обращениями Support Pro; проверка SPF, DKIM и DMARC отправителя, грейлистинг, лимиты, ClamAV, STARTTLS, никаких писем о недоставке; чужие адреса отклоняются ([регламент](docs/ru/MAIL_RECEIVER_CURRENT.md)). Релиз v28.16.0 добавил глубокий анализ трафика на узлах (`AGENT_DPI=1`): nDPI, если установлен, иначе встроенный классификатор первых пакетов потоков — рукопожатие BitTorrent, DHT, uTP, трекеры и эвристика шифрованного BitTorrent; клиент определяется по журналу Xray в памяти узла, наружу уходят только счётчики, эвристика не влияет на антиабуз (миграция `0072_traffic_analysis`, [регламент](docs/ru/TRAFFIC_ANALYSIS_CURRENT.md)). Релиз v28.15.0 добавил раздел «Торренты на узлах»: Xray распознаёт BitTorrent, агент узла передаёт из access-журнала только число срабатываний по клиенту (без адресов и строк журнала), магазин хранит почасовые счётчики 30 дней, на 24 часа отмечает клиента в антиабузе и раз в сутки уведомляет его; шифрованный BitTorrent не распознаётся (миграция `0071_torrent_detection`, [регламент](docs/ru/TORRENT_DETECTION_CURRENT.md)). Релиз v28.14.0 добавил раздел «Терминал узлов»: полную командную оболочку на VPN-сервере прямо в панели через агент узла (без SSH и открытых портов на узле). Терминал включается и на сервере магазина (`TERMINAL_ENABLED`), и на узле (`AGENT_TERMINAL=1`), доступен только администратору с 2FA, каждая сессия подтверждается паролем и кодом, ограничена по времени и простою и записывается в зашифрованный журнал без паролей, набранных при выключенном эхо; сниппеты команд (миграция `0070_node_terminal`, [регламент](docs/ru/NODE_TERMINAL_CURRENT.md)). Релиз v28.13.0 добавил раздел «Почтовый домен: SPF, DKIM, DMARC»: проверку MX, SPF (лимит 10 DNS-запросов, покрытие адреса SMTP), DKIM (совпадение с ключом панели) и DMARC (политика, адреса отчётов) и приём отчётов DMARC из ящика только на чтение или загрузкой — без дублей, с защитой от архивов-бомб и XXE, только о своём домене, со сроком хранения и удалением (миграция `0069_mail_domain`, [регламент](docs/ru/MAIL_DOMAIN_CURRENT.md)). Релиз v28.12.0 добавил в Support Pro 3.8 мост Zendesk и Freshdesk: обращения и история внешнего helpdesk попадают в общую очередь без дублей, клиент объединяется по email, ответы операторов публикуются во внешнем обращении однократно, ограничение частоты (429) ставит синхронизацию на паузу, удаление данных клиента не даёт импортировать обращение снова ([регламент](docs/ru/SUPPORT_HELPDESK_BRIDGE_CURRENT.md)). Релиз v28.11.0 добавил ключи доступа (passkeys) в приложения Android и iOS: вход отпечатком, лицом или PIN-кодом, добавление и удаление ключей в приложении, связь приложений с доменом кабинета через `assetlinks.json` и `apple-app-site-association`, PKCE-код после входа; ключи общие с веб-кабинетом ([инструкция](docs/ru/NATIVE_PASSKEYS_CURRENT.md)). Миграций нет. Релиз v28.10.0 переработал административную панель: стартовая страница «Все разделы» собирает все 58 функций в 8 групп (аналитика, пользователи, тарифы и оплата, маркетинг, бот и кабинет, серверы, система, безопасность) с описанием каждой и поиском по задаче; у каждого раздела есть путь «Админ-панель → группа», заголовок и описание; все поля форм подписаны, примеры перенесены в подсказки внутри полей; типографика и тексты приведены к стилю личного кабинета, английские заголовки заменены русскими; скриншоты документации пересняты ([руководство](docs/ru/ADMIN_PANEL_CURRENT.md)). Миграций нет. Релиз v28.9.0 добавил сетевую аналитику узлов (миграция `0068_network_intel`): для адресов узлов Remnawave показываются ASN, владелец сети, префикс и страна RIR (RIPEstat) и репутация IP (AbuseIPDB при наличии ключа) с кэшем, отметкой свежести, учётом лимитов источников и предупреждениями; внутренние адреса наружу не отправляются, IPv6 поддерживается — строка матрицы «Расширенная DNS/ASN/reputation карта» закрыта ([регламент](docs/ru/NETWORK_INTEL_CURRENT.md)). Релиз v28.8.0 добавил среду плагинов (миграция `0067_plugin_runtime`): плагин — внешний HTTPS-сервис с подписанным пакетом-манифестом; администратор доверяет ключу издателя и подтверждает права, плагин получает подписанные события и API только с разрешёнными правами, версии обновляются и откатываются без перезапуска, при сбоях плагин останавливается автоматически — строка матрицы «Plugin runtime/hotload» закрыта ([регламент](docs/ru/PLUGINS_CURRENT.md)). Релиз v28.7.0 добавил email-канал поддержки (Support Pro 3.7, миграция `0007`): письма клиентов по IMAP становятся обращениями без дублей, ответы операторов уходят письмом с сохранением цепочки, автоответы и возвраты не открывают обращений, есть удаление данных клиента и срок хранения — строка матрицы «Внешние helpdesk/email каналы» закрыта для email ([регламент](docs/ru/SUPPORT_EMAIL_CHANNEL_CURRENT.md)). Релиз v28.6.0 добавил виджет подписки на рабочий стол Android и несколько профилей магазинов в админ-приложениях Android и iOS — строка матрицы «Native push/widget/multiprofile» закрыта ([регламент](docs/ru/WIDGET_AND_PROFILES_CURRENT.md)). Релиз v28.5.0 добавил нативные push-уведомления в приложения Android (FCM) и iOS (APNs): включение по согласию клиента, токен привязан к сессии входа и отзывается при выходе, потерянные токены отключаются автоматически, в админке — состояние провайдеров и доставки ([регламент](docs/ru/PUSH_NOTIFICATIONS_CURRENT.md)). Релиз v28.4.0 перевёл админ-панель, кабинет и Mini App на Next.js (static export, прежние nginx-образы) в дизайне Remna Dark и закрыл строку матрицы «Исторический импорт VPN/платежей»: версионированный адаптер, preview без записи, сверка с контрольными итогами, повтор без дублей и журнал отката ([регламент](docs/ru/HISTORY_IMPORT_CURRENT.md)). Runtime/API остаётся `21.5.1`, схема магазина обновляется до `0067_plugin_runtime`. Релиз v28.3.0 закрыл «70+ настроек с hot-reload и шифрованием». Внешние проверки и production gate остаются открытыми. [Заметки выпуска v28.23.0](docs/ru/RELEASE_V28_23_0.md).

Импорт users.db и массовые операции доступны роли admin в «Пользователи → Импорт и массовые операции». Порядок mapping, preview, применения и границы переноса: [инструкция](docs/ru/CUSTOMER_OPERATIONS_CURRENT.md).

В v21.3.0 добавлены [редакторы новостей, лендингов и юридических страниц](docs/ru/CONTENT_PUBLISHING_CURRENT.md), [промогруппы и персональные офферы](docs/ru/PERSONAL_OFFERS_CURRENT.md), пять previewed массовых действий включая ограничение/восстановление доступа в магазин.

В v21.4.0 добавлены [вложенные меню Telegram и Mini App](docs/ru/MENU_TREE_CURRENT.md): папки до четырёх уровней, стили, custom emoji, безопасные миниатюры и предпросмотр.

В v21.5.0 исправлена [синхронизация истории Support Pro после merge/split](docs/ru/SUPPORT_REMOTE_HISTORY_CURRENT.md): сообщения и файлы сохраняют идентичность, исходная очередь блокируется, внутренние заметки остаются на месте.
