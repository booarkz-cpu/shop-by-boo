> Архив README до переработки рабочего пространства. Для установки и использования откройте актуальный README в корне проекта.

# VPN Shop

**Актуальный выпуск исходников: v20.0.29.** [Релиз и ZIP с SHA-256](https://github.com/booarkz-cpu/shop-by-boo/releases/tag/v20.0.29) · [заметки выпуска](../../.github/release-v20.0.29.md) · [Changelog](../../CHANGELOG.md). Это выпуск исходников; реальные платежи остаются закрытыми до полного staging E2E v2.

## Актуальные инструкции

| Задача | Документация |
| --- | --- |
| Начать с простых шагов | [Пять последовательных инструкций](../../docs/ru/steps/README.md) |
| Установить на VDS с нуля (Termius/SSH) | [Подробная установка v20.0.29](../../docs/ru/VDS_PRODUCTION_20_0_26.md) |
| Запустить тестовый стенд | [Проверка без реальных платежей](../../docs/ru/TESTING.md) |
| Обновить или восстановить сервер | [Обслуживание](../../docs/ru/steps/05-operations.md), [раздел в инструкции VDS](../../docs/ru/VDS_PRODUCTION_20_0_26.md) |
| Настроить кассы | [Все провайдеры по шагам](../../docs/ru/ALL_PAYMENT_PROVIDERS_BEGINNER_CHECKLIST.md), [подготовка staging](../../docs/ru/STAGING_VDS_E2E_OPERATOR_20_0_18.md) |
| Проверить допуск живых платежей | [Контракт staging E2E v2](../../docs/ru/STAGING_E2E_V2_IMPLEMENTATION.md), [аудит интеграций](../../docs/ru/PAYMENT_AUDIT_2026_09_28.md) |
| Разобраться в функциях и API | [Руководство функций](../../docs/ru/FUNCTION_GUIDE.md), [API](../../API_REFERENCE_RU.md) |
| Подготовить мобильные клиенты | [Мобильные приложения](../../docs/ru/MOBILE_GUIDE.md), [сборка и подпись](../../docs/ru/PRODUCTION_20_0_15.md) |
| Эксплуатировать Support Pro | [Руководство компонента](../../support-pro/README.md) |
| Ознакомиться с результатами проверки | [Отчёт 28 сентября](../../docs/ru/AUDIT_2026_09_28_REPOSITORY.md), [заметки v20.0.29](../../.github/release-v20.0.29.md) |
| Найти другую документацию | [Общий указатель](../../docs/INDEX.md), [операционный регламент](../../OPERATIONS_RUNBOOK_RU.md) |

| | Русский | English | Українська |
| --- | --- | --- | --- |
| Возможности | [Описание](../../docs/ru/README.md) | [Features](../../docs/en/README.md) | [Можливості](../../docs/uk/README.md) |
| Развёртывание | [Руководство](../../docs/ru/DEPLOYMENT.md) | [Deployment](../../docs/en/DEPLOYMENT.md) | [Розгортання](../../docs/uk/DEPLOYMENT.md) |
| Тестирование | [Инструкция](../../docs/ru/TESTING.md) | [Testing](../../docs/en/TESTING.md) | [Тестування](../../docs/uk/TESTING.md) |
| Платежи | [Состояние](../../docs/ru/PAYMENTS.md) | [Payments](../../docs/en/PAYMENTS.md) | [Платежі](../../docs/uk/PAYMENTS.md) |

Магазин VPN-подписок включает кабинет, Mini App, админку, Telegram-бот, Android/iOS и интеграцию Remnawave. Лицензия и условия использования: [LICENSE](../../LICENSE). CI: [текущие запуски](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/ci.yml). Перед production проверьте результат на своём VDS и полный staging E2E v2. Исторические инструкции ниже относятся к указанным в них версиям.

## Предыдущие выпуски

**Мобильные приложения 2.14.1:** [скачать сборки](https://github.com/booarkz-cpu/shop-by-boo/releases/tag/mobile-v2.14.1) · [установка и подпись](../../docs/ru/MOBILE_RELEASE_2_14_1.md). Android preview APK устанавливаются рядом с основными приложениями; iOS unsigned IPA требует Apple-подписи.

**Релиз 20.0.14 — исправления сводного аудита безопасности.** [Результаты по 19 пунктам](../../docs/ru/SECURITY_AUDIT_20_0_14.md) · [Обязательная инструкция обновления](../../docs/ru/SECURITY_UPGRADE_20_0_14.md) · [Changelog](../../CHANGELOG.md).

Перед обновлением подготовьте новые native-клиенты 2.14.1, пароли Redis и две MFA-учётные записи для restore. В production используются точные CORS origins и доверенный IP Caddy. Полный staging E2E v2 ещё не реализован: реальные платежи остаются закрытыми.

Магазин VPN-подписок: кабинет, Mini App, админка, Telegram-бот, приложения Android и iOS, выдача доступа через Remnawave.

A VPN subscription shop: cabinet, Mini App, admin panel, Telegram bot, Android and iOS apps, and Remnawave fulfillment.

Магазин VPN-підписок: кабінет, Mini App, адмінка, Telegram-бот, застосунки Android і iOS, видача доступу через Remnawave.

Лицензия — [LICENSE](../../LICENSE). Подробные описания лежат в `docs/ru`, `docs/en` и `docs/uk`.

| | Русский | English | Українська |
| --- | --- | --- | --- |
| Возможности | [docs/ru/README.md](../../docs/ru/README.md) | [docs/en/README.md](../../docs/en/README.md) | [docs/uk/README.md](../../docs/uk/README.md) |
| Развёртывание | [docs/ru/DEPLOYMENT.md](../../docs/ru/DEPLOYMENT.md) | [docs/en/DEPLOYMENT.md](../../docs/en/DEPLOYMENT.md) | [docs/uk/DEPLOYMENT.md](../../docs/uk/DEPLOYMENT.md) |
| Проверка без касс | [docs/ru/TESTING.md](../../docs/ru/TESTING.md) | [docs/en/TESTING.md](../../docs/en/TESTING.md) | [docs/uk/TESTING.md](../../docs/uk/TESTING.md) |
| Живые платежи | [docs/ru/PAYMENTS.md](../../docs/ru/PAYMENTS.md) | [docs/en/PAYMENTS.md](../../docs/en/PAYMENTS.md) | [docs/uk/PAYMENTS.md](../../docs/uk/PAYMENTS.md) |

Песочница разрешена только при `APP_ENV=development`, `test` или `staging`. На `APP_ENV=production` процесс с `PAYMENTS_SANDBOX=true` не стартует. Пока не пройден staging E2E, живые платежи отвечают отказом.


## v20.0.13 — защита staging gate и план E2E v2

Приём платежей перепроверяет срок staging-доказательства и его связь с текущей конфигурацией при каждом новом списании. Изменение staging-конфигурации закрывает gate и сбрасывает прежний результат; конкурирующие проверки резервируются через БД. [Подробный changelog](../../.github/release-v20.0.13.md) · [Пошаговая реализация staging E2E v2](../../docs/ru/STAGING_E2E_V2_IMPLEMENTATION.md). **Полный runner v2 ещё не реализован; реальные платежи остаются закрытыми.**

## v20.0.12 — проверка безопасности и запуск на VDS

Исправлены полномочия управления реселлерами, проверка содержимого архивов и конфигурация подписи мобильного клиента. [Подробный changelog](../../.github/release-v20.0.12.md) · [Пошаговая установка на VDS](../../docs/ru/VDS_PRODUCTION_V20_0_12.md). Production-приложение запускается с закрытым допуском живых платежей: текущий staging runner не подтверждает полный цикл E2E.

## v20.0.11 — исправления платежей и возвратов

- Stripe возвращает деньги по PaymentIntent, связанному с оплаченной Checkout Session. Stripe и PayPal поддерживают повторную сверку статуса возврата и стабильные ключи повторных запросов.
- Webhook Stripe и PayPal подтверждают заказ через общий путь с блокировками; поздние события не возвращают статус оплаченного или возвращённого платежа назад.
- Автоматическое подтверждение в песочнице и сверка возвратов записывают финансовые события.

[Заметки релиза](../../.github/release-v20.0.11.md). Живые платежи требуют отдельного staging E2E.

## v20.0.10 — подтверждение платежей в песочнице

- Тестовый endpoint подтверждения теперь использует общий путь с блокировками и повторной проверкой статуса. Возвращённый платёж нельзя повторно пометить оплаченным; запись в финансовый журнал выполняется как при webhook.
- Публикация релиза запускается после успешного CI для актуального коммита основной ветки.

[Заметки релиза](../../.github/release-v20.0.10.md). Живые платежи требуют отдельного staging E2E.

## v20.0.9 — безопасность аккаунтов и возвратов

- Убрано автоматическое объединение VK и email-аккаунтов: совпадение адреса теперь возвращает 409, существующие привязки продолжают работать.
- Подтверждение Platega/RollyPay требует совпадения валюты. Ответ без валюты не даёт выдать VPN или зачислить кошелёк.
- Возврат пополнения списывает зачисленную сумму ровно один раз и не отключает отдельную VPN-подписку. Потраченная сумма отражается отрицательным балансом.
- После ожидания блокировок платежи перечитываются с обновлением ORM-кэша; поздний webhook не должен воскресить возвращённый платёж.
- Админская сессия проверяется на принадлежность аккаунту; удалённым пользователям не выдаются новые сессии.

[Подробный аудит и порядок обновления](../../docs/ru/AUDIT_20_0_9.md) · [Заметки релиза](../../.github/release-v20.0.9.md).

Живые платежи по-прежнему закрыты до полной сквозной проверки. Этот релиз не является подтверждением готовности платёжных интеграций к production.

## v20.0.8 — аудит, установка и безопасный staging

| | Русский | English | Українська |
| --- | --- | --- | --- |
| Полный регламент staging E2E | [Пошаговая проверка](../../docs/ru/STAGING_E2E_20_0_8.md) | [Step-by-step check](../../docs/en/STAGING_E2E_20_0_8.md) | [Покрокова перевірка](../../docs/uk/STAGING_E2E_20_0_8.md) |
| Установка, функции и эксплуатация | [Развёртывание](../../docs/ru/DEPLOYMENT.md), [функции](../../docs/ru/FUNCTION_GUIDE.md), [операции](../../OPERATIONS_RUNBOOK_RU.md) | [Deployment](../../docs/en/DEPLOYMENT.md), [features](../../docs/en/README.md), [payments](../../docs/en/PAYMENTS.md) | [Розгортання](../../docs/uk/DEPLOYMENT.md), [функції](../../docs/uk/README.md), [платежі](../../docs/uk/PAYMENTS.md) |

**Русский.** Образы закреплены digest; Python и JavaScript зависимости проверяются до публикации контейнеров. Пароль Support Pro передаётся отдельной переменной и безопасно собирается в URL. При `APP_ENV=production` значение `COOKIE_SECURE=false` останавливает backend. Для ручного `DATABASE_URL` кодируйте пароль: `urllib.parse.quote(password, safe='')`; `@` превращается в `%40`, `#` — в `%23`. Не вставляйте сырой пароль в URL. Текущий staging runner не проверяет webhook и выдачу; реальные платежи закрыты до реализации полного E2E. Старый допуск v20.0.7 сбрасывается новым ключом.

**English.** Container bases use immutable digests and CI audits Python and JavaScript dependencies before image publishing. Support Pro builds its database URL from separate credentials. Backend refuses `APP_ENV=production` with `COOKIE_SECURE=false`. Percent-encode passwords in a manually supplied `DATABASE_URL` with `urllib.parse.quote(password, safe='')`. The current staging runner does not verify webhook delivery or fulfillment; live payments remain gated until a complete E2E implementation exists. The v20.0.7 gate is invalidated.

**Українська.** Базові образи закріплені digest, а CI перевіряє залежності Python і JavaScript до публікації контейнерів. Support Pro складає URL бази з окремих параметрів. Backend зупиняється за `APP_ENV=production` та `COOKIE_SECURE=false`. Для ручного `DATABASE_URL` закодуйте пароль через `urllib.parse.quote(password, safe='')`. Поточний staging runner не перевіряє webhook і видачу; реальні платежі заблоковані до повного E2E. Старий допуск v20.0.7 скасовано.

[Отчёт аудита v20.0.8](../../docs/ru/AUDIT_20_0_8.md) · [Заметки релиза](../../.github/release-v20.0.8.md)

## Аудит 20.0.7 и актуальные руководства

- [Отчёт аудита и границы проверок](../../docs/ru/AUDIT_20_0_7.md)
- [Пошаговое подключение Android и iOS](../../docs/ru/MOBILE_GUIDE.md)
- [Функции магазина по разделам](../../docs/ru/FUNCTION_GUIDE.md)
- [Справочник API](../../API_REFERENCE_RU.md) · [Операционный регламент](../../OPERATIONS_RUNBOOK_RU.md)

Мобильные приложения магазина показывают подписку, оплату и сведения аккаунта. Встроенного движка VPN в них нет: импортируйте ссылку подписки в совместимый внешний клиент. API не подтверждает Kill Switch или защиту DNS/IPv6 без реального туннеля.

Бесплатное разрешение на собственный коммерческий магазин, внутренние изменения и собранные клиентские приложения дано в [LICENSE](../../LICENSE). Публикация изменённого исходного кода или контейнеров требует отдельного разрешения.

## Русский

### Тестовый стенд

Стенд поднимает API, админку, кабинет и Mini App без YooKassa, Platega, RollyPay, Stripe, PayPal, Telegram и Remnawave. Подписка будет `sandbox://local/...`: это проверка магазина, а не рабочий VPN.

Нужны Docker Engine, плагин Compose и свободные порты 18080–18083.

```bash
git clone https://github.com/booarkz-cpu/shop-by-boo.git vpn-shop-src
cd vpn-shop-src
bash scripts/test-up.sh
```

Скрипт создаёт `.env.test` со случайными секретами, передаёт его Compose и собирает `docker-compose.test.yml`, ждёт `http://127.0.0.1:18080/health` и покупает тариф «Тестовый месяц» через песочницу. Пароль администратора печатается один раз: почта `admin@example.test`.

| Поверхность | Адрес |
| --- | --- |
| API | http://127.0.0.1:18080/health |
| Админка | http://127.0.0.1:18081 |
| Кабинет | http://127.0.0.1:18082 |
| Mini App | http://127.0.0.1:18083 |

Порты слушают только `127.0.0.1`. Для проверки с другой машины создайте SSH-туннель, например `ssh -L 18081:127.0.0.1:18081 user@server`, затем откройте `http://127.0.0.1:18081`. `COOKIE_SECURE=false` допустим только в этом локальном стенде.

Остановка: `docker compose --env-file .env.test -f docker-compose.test.yml down`. Флаг `-v` удаляет базу.

### Установка на VDS

Боевой магазин принимает заказы по HTTPS. Нужны Ubuntu или Debian, root по SSH, домен и пять имён на IP сервера: API, админка, Mini App, кабинет и Support Pro. Ещё нужны панель Remnawave и токен бота от @BotFather. Установщик сам открывает SSH, TCP 80, TCP 443 и UDP 443 в файрволе сервера. PostgreSQL, Redis и порт приложения наружу не публикуются. Если у хостера есть отдельный файрвол панели, разрешите в нём те же порты.

Пароль может содержать специальные символы. В ручном `DATABASE_URL` кодируйте его через `urllib.parse.quote(password, safe='')`; Support Pro использует отдельные переменные `POSTGRES_*`.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git openssl
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
sudo git clone https://github.com/booarkz-cpu/shop-by-boo.git /opt/vpn-shop
cd /opt/vpn-shop
sudo bash install.sh
```

`install.sh` ставит Docker, если его ещё нет, и запускает `deploy/install-vps.sh`. Вопросы читаются в терминале SSH. Тот же результат вручную:

```bash
cd /opt/vpn-shop
cp .env.example .env
openssl rand -hex 32
```

Впишите в `.env`:

| Переменная | Значение |
| --- | --- |
| `APP_SECRET` | строка из `openssl rand -hex 32`, не короче 32 символов |
| `APP_ENV` | `production` |
| `DB_PASSWORD` и `POSTGRES_PASSWORD` | один и тот же пароль |
| `DATABASE_URL` | тот же пароль в `postgresql+asyncpg://vpnshop:ПАРОЛЬ@db:5432/vpnshop` |
| `BOT_TOKEN` | токен BotFather |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | первый вход в панель |
| `REMNAWAVE_URL`, `REMNAWAVE_TOKEN` | панель |
| `PUBLIC_BASE_URL`, `MINI_APP_URL`, `CABINET_URL` | адреса `https://` |
| `API_DOMAIN`, `ADMIN_DOMAIN`, `APP_DOMAIN`, `CABINET_DOMAIN` | имена без схемы |
| `SUPPORT_PRO_DOMAIN` | имя службы заявок |
| `SUPPORT_PRO_DB_PASSWORD` | отдельный пароль базы заявок |
| `SUPPORT_PRO_SSO_SECRET` | ещё одна строка `openssl rand -hex 32` |
| `COOKIE_SECURE` | `true` |
| `PAYMENTS_SANDBOX` | `false` |

Без `SUPPORT_PRO_DOMAIN` файл `docker-compose.yml` не стартует.

```bash
cd /opt/vpn-shop
docker compose up -d --build
curl -fsS https://API_DOMAIN/health
```

Ответ содержит `"ok": true` и текущую версию из `backend/app/main.py`. Откройте `https://ADMIN_DOMAIN` и войдите почтой из `.env`. Ключи касс можно оставить пустыми: живые платежи закрыты до реализации полного staging E2E v2.

### Возможности

Магазин продаёт VPN-подписки. Покупатель выбирает тариф, оплачивает его и получает ссылку подписки Remnawave. Узлы VPN живут в панели Remnawave: этот репозиторий их не поднимает.

| Часть | Где лежит | Что делает |
| --- | --- | --- |
| API | `backend/app/main.py` | Покупатели, тарифы, платежи, выдача подписки, методы панели |
| Бот | `backend/app/bot.py` | Telegram: старт, цены, промокод, ссылка на Mini App |
| Воркер | `backend/worker.py` | Очередь, повтор выдачи, пробный период, сверка платежей |
| Админка | `admin/` | Вход сотрудника, тарифы, платежи, пользователи, контент |
| Mini App | `miniapp/` | Покупка внутри Telegram |
| Кабинет | `cabinet/` | Вход по email, обзор подписки, оплата, подключение |
| Приложения | `mobile/` | Android и iOS для покупателя и администратора |
| Support Pro | `support-pro/` | Отдельная служба заявок |
| Периметр | `docker-compose.yml`, `deploy/Caddyfile` | HTTPS и отдельные домены |

База — PostgreSQL. Очереди и блокировки — Redis. Схема меняется только миграциями Alembic в `backend/alembic`.

Покупатель может:

- Зарегистрироваться по email в личном кабинете или войти через Telegram, VK и Яндекс, если эти входы заполнены в `.env`.
- Открыть Mini App из бота и увидеть тарифы.
- Купить фиксированный тариф или собрать срок, трафик и число устройств. Конструктор тарифов доступен, если администратор его включил.
- Применить промокод. Скидка и срок фиксируются в снимке платежа и не меняются, если тариф потом отредактируют.
- Получить пробный период, если действующей подписки нет.
- Пополнить внутренний баланс и потратить его на тариф. Повторное списание с тем же `Idempotency-Key` блокируется. Сумма 0 и меньше отклоняется до обращения к кассе.
- Купить и погасить подарочную карту. Карта зачисляется на баланс только в валюте `DEFAULT_CURRENCY`.
- Открыть ссылку подписки, скачать её файлом и посмотреть QR для Happ, v2rayNG и Streisand, когда ссылка начинается с `https://`.
- Включить отмену подписки в конце оплаченного срока.
- Смотреть свои платежи в центре биллинга.
- Скачать приложения Android и iOS из карточек кабинета. Как скачать приложения для Android и iOS из старых релизов, описано ниже, в истории. Новые сборки администратор загружает в панель сам.

Администратор может:

- Войти по email и паролю. Роли: `viewer`, `operator`, `admin`. У роли `viewer` нет права смотреть ключи подписки.
- Включить TOTP. Сессии привязаны к браузеру и гасятся после 15 минут бездействия или смены User-Agent.
- Создавать и выключать тарифы, конструктор, промокоды, акции и пункты меню кабинета.
- Смотреть платежи, возвращать оплаченный заказ и повторять выдачу, если Remnawave ответил ошибкой. Повтор выдачи работает только для статуса `paid`.
- Загружать APK и IPA. Покупатель скачивает файл из кабинета, администратор — из панели.
- Делать рассылку в Telegram. Сообщение ставится в очередь, доставляет процесс бота.
- Включать технический режим. Пока он включён, новые платежи отклоняются.
- Смотреть журнал аудита. В ответы панели не кладётся текст исключения и секрет провайдера.
- Регистрировать узел и запускать failover только с правом `provision_nodes`. Без этого права методы отвечают отказом.

Первый администратор создаётся из `ADMIN_EMAIL` и `ADMIN_PASSWORD` при пустой таблице администраторов.

Боевая выдача ходит в Remnawave по `REMNAWAVE_URL` и `REMNAWAVE_TOKEN`. Магазин создаёт или продлевает пользователя и записывает срок, лимит трафика и ссылку. Повтор той же операции не продлевает срок второй раз. Обновление карточки из панели не копирует более поздний срок в оплаченную подписку. Без этих двух переменных песочница пишет `sandbox://local/...` и `sandbox-user-{id}`: это метка проверки, а не рабочий VPN.

### Запуск с платёжными системами

Сначала поднимите магазин по разделу «Установка на VDS». `APP_ENV=production`, `PAYMENTS_SANDBOX=false`, `COOKIE_SECURE=true`. Заполните только те ключи, которыми будете пользоваться. Пустой ключ выключает провайдера. Затем `docker compose up -d`.

| Провайдер | Переменные | Вебхук |
| --- | --- | --- |
| YooKassa | `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_WEBHOOK_IP_ALLOWLIST` | `POST https://API_DOMAIN/api/webhooks/yookassa` |
| Platega | `PLATEGA_MERCHANT_ID`, `PLATEGA_SECRET` | `POST https://API_DOMAIN/api/webhooks/platega` |
| RollyPay | `ROLLYPAY_API_KEY`, `ROLLYPAY_SIGNING_SECRET` | `POST https://API_DOMAIN/api/webhooks/rollypay` |
| Stripe | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | `POST https://API_DOMAIN/api/payments/webhooks/stripe` |
| PayPal | `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID` | `POST https://API_DOMAIN/api/payments/webhooks/paypal` |
| Криптошлюз | `CRYPTO_GATEWAY_URL`, `CRYPTO_GATEWAY_KEY` | `POST https://API_DOMAIN/api/webhooks/crypto` |

`YOOKASSA_API_URL` по умолчанию `https://api.yookassa.ru`. `PLATEGA_API_URL` — `https://app.platega.io`. `ROLLYPAY_API_URL` — `https://rollypay.io`. Адрес проверяется как публичный URL. Возвраты Platega и RollyPay требуют `PLATEGA_REFUND_URL`, `PLATEGA_REFUND_STATUS_URL`, `ROLLYPAY_REFUND_URL` и `ROLLYPAY_REFUND_STATUS_URL`. `ROLLYPAY_TEST_MODE=true` — тестовый счёт кассы, а не песочница магазина. SEPA redirect-checkout не открывает.

1. YooKassa. В кабинете ЮKassa возьмите shop id и секретный ключ и запишите их в `.env`. В уведомлениях укажите URL вебхука и событие успешной оплаты. В `YOOKASSA_WEBHOOK_IP_ALLOWLIST` перечислите сети ЮKassa через запятую. Пустой список отклоняет все уведомления. Магазин смотрит адрес ближайшего прокси: Caddy подставляет `X-Forwarded-For` из реального клиента.
2. Platega. Запишите merchant id и секрет. В кабинете Platega укажите вебхук. Уведомление должно приходить с `X-MerchantId` и `X-Secret`. Перед выдачей магазин ещё раз читает транзакцию и сверяет сумму и номер заказа.
3. RollyPay. Запишите API-ключ и секрет подписи. Уведомление обязано содержать `X-Signature` (HMAC-SHA256 тела) и `X-Timestamp`. Метка старше пяти минут отклоняется.
4. Stripe. В кабинете Stripe укажите вебхук `POST /api/payments/webhooks/stripe` и секрет подписи в `STRIPE_WEBHOOK_SECRET`. Подписка включается только если провайдер ответил `paid` или `succeeded`, а сумма, валюта и `order_id` совпали. Неоплаченная сессия checkout подписку не включает.
5. PayPal. Укажите вебхук `POST /api/payments/webhooks/paypal` и `PAYPAL_WEBHOOK_ID`. Заказ проводится, когда заказ у PayPal в статусе `COMPLETED`, сумма и валюта совпали и есть завершённый захват.
6. Криптошлюз. Вебхук `POST /api/webhooks/crypto` требует `X-Timestamp` (unix-секунды, окно 5 минут) и `X-Signature` = hex HMAC-SHA256 от `{timestamp}.{сырое тело}` ключом `CRYPTO_GATEWAY_KEY`. Затем магазин делает `GET {CRYPTO_GATEWAY_URL}/payments/{id}` и принимает статусы `paid`, `succeeded`, `success`, `confirmed` только при совпадении суммы, валюты и `order_id`.
7. Apple и Google. `MOBILE_STORE_PRODUCTS` — JSON, где ключ это id продукта, а значение это id тарифа. Пример: `{"com.shop.month": 1}`. Пустая переменная отклоняет `POST /api/payments/mobile/verify`. Чек Apple без `transactionId` и без ключей App Store Server API отклоняется. Чек Google Play годится только при `SUBSCRIPTION_STATE_ACTIVE`, и продукт из ответа Google должен быть в этой карте.
8. Открытие боевых платежей возможно только после внедрения [полного staging E2E v2](../../docs/ru/STAGING_E2E_V2_IMPLEMENTATION.md), нового релиза и свежего доказательства для текущей конфигурации. В **v20.0.13 это недоступно**: runner возвращает `full_e2e=false`, `contract_version=1`; `POST /api/admin/payments/production-gate` с `{"enabled":true}` отвечает `409`. Нельзя открывать приём прямым изменением БД или подменой статуса.
9. После выпуска и успешного прохождения настоящего E2E v2 выполните контрольное списание и возврат по регламенту ниже. До этого проверяйте только отдельный staging и не обещайте покупателям приём живых платежей.

`AUTO_RENEW_ENABLED=true` сохраняет способ оплаты ЮKassa для следующего периода. Не включайте автопродление, пока ручной возврат на staging не прошёл. Песочница рекуррентные списания не выполняет. Покупатель не может сам поставить `tax_exempt` или `reverse_charge`.

Подробные таблицы переменных — в [docs/ru/PAYMENTS.md](../../docs/ru/PAYMENTS.md).

### Подробная проверка реальных платежей после внедрения E2E v2

**Статус этой инструкции:** описан будущий приёмочный тест с настоящими деньгами на production после выпуска проверенного runner v2. На текущем v20.0.13 выполнить его нельзя: платёжный gate законно отказывает `409`, а покупательский checkout — `503`. Не выключайте защиту и не имитируйте результат проверки. Порядок внедрения v2, тестов с песочницей и получения доказательства приведён [отдельно](../../docs/ru/STAGING_E2E_V2_IMPLEMENTATION.md).

#### 1. Допуск перед первым живым списанием

1. Сохраните и пробно восстановите независимую копию PostgreSQL, медиа и секретов. Зафиксируйте версию приложения, миграций, DNS и контакты поддержки провайдера. Убедитесь, что тестовый пользователь и тестовый тариф не затронут существующих покупателей.
2. Разверните **новый релиз с реализованным E2E v2**; проверьте, что отдельный staging с другими ключами, доменами, БД и Remnawave прошёл через настоящий пользовательский `Payment` → подписанный webhook → одну выдачу → повтор события → возврат и отзыв. Сравните ID событий и состояние провайдера, магазина и Remnawave. Простое «оплачен» в ответе API провайдера не является таким доказательством.
3. На production установите `APP_ENV=production`, `PAYMENTS_SANDBOX=false`, `COOKIE_SECURE=true`. Включите только нужного провайдера, его действительные credentials и callback URL из таблицы выше. Для YooKassa настройте актуальные адреса в `YOOKASSA_WEBHOOK_IP_ALLOWLIST`; для Platega/RollyPay — требуемые секреты уведомлений. Проверяйте текущее значение адресов и режимов по документации вашего провайдера перед настройкой: они могут измениться. Токены держите только в защищённом `.env` и кабинете кассы.
4. Проверьте DNS, внешний HTTPS, доступность webhook, часы и работоспособность процессов. Замените примерный домен своим:

   ```bash
   cd /opt/vpn-shop
   sudo docker compose --env-file .env config --quiet
   sudo docker compose ps
   curl -fsS https://api.example.com/health/ready
   sudo docker compose exec backend alembic current
   ```

   `health/ready` должен показать `ok: true`, доступность БД и Redis. Backend, worker, bot, веб-клиенты и Caddy должны работать. Не печатайте `docker compose config` без `--quiet` в публичный журнал: он может раскрыть переменные окружения.
5. Администратор с `security.manage` проверяет в панели статус **успешного полного E2E v2**, `config_revision` и возраст результата не более 24 часов, затем через штатный интерфейс включает production gate. Сохранённый флаг также перепроверяется при каждом новом списании и автопродлении. Если gate отвечает `409`, результат устарел, не полон либо конфигурация изменилась; вернитесь к staging и проведите проверку заново. Не правьте `staging_e2e.status` или `payments.production_gate` вручную.

#### 2. Проведите один контролируемый платёж

1. Выберите разрешённый кассой небольшой **ненулевой** тариф. Зафиксируйте валюту и ожидаемую сумму с учётом скидок и налогов, идентификатор тестового покупателя и время. Определите, кто оплатит реальными деньгами и кто подтвердит возврат. Не используйте настоящие чужие данные или платёжные реквизиты в отчёте.
2. Войдите в кабинет как этот покупатель и создайте заказ обычным интерфейсом, выбрав **конкретного** провайдера. Не вызывайте `/api/internal/staging-e2e/payment`: он не создаёт обычный заказ магазина. Не нажимайте оплату повторно при сетевой задержке; используйте тот же `Idempotency-Key` при предусмотренном повторе запроса и сверьте операцию перед новым заказом.
3. Запишите внутренний `Payment.id`, `order_id`, `provider_payment_id`, ожидаемые сумму и валюту, не сохраняя секретную checkout-ссылку. Оплатите счёт по HTTPS в официальной форме кассы. Сверьте фактический платёж в кабинете провайдера по внешнему ID и `order_id`; убедитесь, что списана ожидаемая сумма в нужной валюте и не создан второй платёж.
4. Дождитесь **настоящего webhook провайдера**, а не только возврата браузера или опроса статуса. В админке откройте запись `GET /api/admin/payments/{payment_id}` либо карточку платежа: `status=paid`, `fulfillment_status=completed`. Сверьте время, провайдера, `order_id`, сумму, валюту, отсутствие ошибок обработки события и соответствующую запись финансового журнала. Обработчик ещё раз сверяет подтверждение с API кассы. Не отправляйте поддельный «успешный» webhook ради прохождения проверки.
5. Откройте кабинет покупателя: подписка должна иметь верный тариф, срок и лимиты, а ссылка выдачи вести на действительный `https://` адрес Remnawave. Проверьте в **вашей** панели Remnawave конкретного пользователя и наличие ровно одного доступа. Ответ `sandbox://local/...` означает локальный тестовый доступ, не работающую боевую выдачу.

#### 3. Повторы и отрицательные исходы

| Проверка | Что должно произойти |
| --- | --- |
| Повтор того же события через штатный механизм доставки провайдера | Срок подписки, сумма, число финансовых записей и доступов не увеличиваются. |
| Чужой заказ, неверная сумма/валюта, недействительная подпись или IP | Событие отвергается; платёж не становится `paid`, VPN не выдаётся. Такие пробы проводите на отдельном staging, а не мошенническим запросом в боевую кассу. |
| Задержка webhook, недоступность Remnawave | Платёж сверяется с кассой; выдача попадает в контролируемый повтор без второго списания. |
| Истечение 24 часов после E2E или смена staging-конфигурации | Новые списания и автопродления останавливаются до свежего E2E. Уже оплаченные операции расследуются отдельно. |

Запишите фактические ID и времена, не копируя в тикеты токены, полный webhook, данные карты и ссылку подписки. Если нет webhook или выдачи, **не повторяйте реальное списание**: сначала проверьте кабинет провайдера, `sudo docker compose logs --tail=100 backend worker caddy` и статус заказа. Операционный маршрут повторной выдачи применим только к подтверждённому `paid` и не заменяет финансовую сверку.

#### 4. Проведите возврат и сверьте отзыв доступа

1. Через админку создайте запрос возврата для того же `Payment.id`, проверьте dry-run и одобрите его уполномоченной ролью. Исполните возврат штатным процессом. API проекта предусматривает `/api/admin/payments/{payment_id}/refund-request`, `/api/admin/refunds/{refund_id}/approve`, `/api/admin/refunds/{refund_id}/execute` и `/api/admin/refunds/{refund_id}/reconcile`; используйте интерфейс панели, чтобы не пропустить параметры и проверки доступа.
2. Дождитесь конечного состояния операции в кабинете кассы и в магазине. Сверьте provider refund ID, величину и валюту возврата, финансовую запись и статус `refunded`. Промежуточное `processing` либо `refunded_pending_revoke` не означает завершение всего сценария; проверьте фоновые задачи и повторите сверку штатным маршрутом при необходимости.
3. Убедитесь, что соответствующий доступ отозван/сокращён в Remnawave. Повторный success-webhook после возврата не должен возвращать `paid` и выдавать VPN. Не делайте второй возврат, пока первый ещё обрабатывается; сначала сверьте provider refund ID.

#### 5. Завершите проверку и наблюдайте систему

Сохраните короткий акт: версия и время, провайдер, внутренние и внешние ID, ожидаемая/фактическая сумма и валюта, время webhook, результат выдачи, повтор события, возврат, отзыв доступа и ответственный оператор. Личные данные и секреты удалите. Повторите **отдельный** цикл для каждого подключаемого провайдера; успешная YooKassa не подтверждает Stripe или RollyPay. После проверки следите за очередями webhook/выдачи, возвратами, `/health/ready`, сроком TLS и возрастом доказательства E2E. При расхождении немедленно выключите gate штатным `{"enabled":false}`, сохраните ID и журналы и сверьте операции с кассой до возобновления продаж.

Этот раздел описывает проверку на будущей версии с настоящим E2E v2. На v20.0.13 применяйте только [изолированный staging-регламент](../../docs/ru/STAGING_E2E_V2_IMPLEMENTATION.md); ручное открытие платёжного шлюза для «пробного» живого списания недопустимо.

## English

### Test stand

The stand runs the API, admin panel, cabinet and Mini App without YooKassa, Platega, RollyPay, Stripe, PayPal, Telegram or Remnawave. The subscription link is `sandbox://local/...`. That checks the shop. It is not a working VPN profile.

You need Docker Engine, the Compose plugin, and free ports 18080–18083.

```bash
git clone https://github.com/booarkz-cpu/shop-by-boo.git vpn-shop-src
cd vpn-shop-src
bash scripts/test-up.sh
```

The script writes `.env.test` with random secrets, passes it to Compose, builds `docker-compose.test.yml`, waits for `http://127.0.0.1:18080/health`, and buys the plan "Тестовый месяц" through the sandbox. The admin password is printed once. The email is `admin@example.test`.

| Surface | URL |
| --- | --- |
| API | http://127.0.0.1:18080/health |
| Admin | http://127.0.0.1:18081 |
| Cabinet | http://127.0.0.1:18082 |
| Mini App | http://127.0.0.1:18083 |

The ports bind to `127.0.0.1` only. For remote access use an SSH tunnel, for example `ssh -L 18081:127.0.0.1:18081 user@server`, then open `http://127.0.0.1:18081`. `COOKIE_SECURE=false` applies only to this local test.

Stop with `docker compose --env-file .env.test -f docker-compose.test.yml down`. Add `-v` to drop the database.

### Install on a VDS

A live shop takes orders over HTTPS. You need Ubuntu or Debian, root SSH, a domain, and five names pointing at the server: API, admin, Mini App, cabinet, and Support Pro. You also need a Remnawave panel and a bot token from @BotFather. The installer opens SSH, TCP 80, TCP 443 and UDP 443 in the server firewall. PostgreSQL, Redis and the application port stay unpublished. If the hoster has a panel firewall, allow the same ports there.

Passwords may contain special characters. Percent-encode the password in a manually supplied `DATABASE_URL` with `urllib.parse.quote(password, safe='')`; Support Pro uses separate `POSTGRES_*` variables.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git openssl
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
sudo git clone https://github.com/booarkz-cpu/shop-by-boo.git /opt/vpn-shop
cd /opt/vpn-shop
sudo bash install.sh
```

`install.sh` installs Docker when it is missing, then runs `deploy/install-vps.sh`. The questions are read on the SSH terminal. The same result by hand:

```bash
cd /opt/vpn-shop
cp .env.example .env
openssl rand -hex 32
```

Set in `.env`:

| Variable | Value |
| --- | --- |
| `APP_SECRET` | output of `openssl rand -hex 32`, at least 32 characters |
| `APP_ENV` | `production` |
| `DB_PASSWORD` and `POSTGRES_PASSWORD` | the same password |
| `DATABASE_URL` | that password inside `postgresql+asyncpg://vpnshop:PASSWORD@db:5432/vpnshop` |
| `BOT_TOKEN` | the BotFather token |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | the first panel login |
| `REMNAWAVE_URL`, `REMNAWAVE_TOKEN` | the panel |
| `PUBLIC_BASE_URL`, `MINI_APP_URL`, `CABINET_URL` | `https://` origins |
| `API_DOMAIN`, `ADMIN_DOMAIN`, `APP_DOMAIN`, `CABINET_DOMAIN` | hostnames without a scheme |
| `SUPPORT_PRO_DOMAIN` | ticket desk hostname |
| `SUPPORT_PRO_DB_PASSWORD` | a separate database password |
| `SUPPORT_PRO_SSO_SECRET` | another `openssl rand -hex 32` string |
| `COOKIE_SECURE` | `true` |
| `PAYMENTS_SANDBOX` | `false` |

`docker-compose.yml` does not start without `SUPPORT_PRO_DOMAIN`.

```bash
cd /opt/vpn-shop
docker compose up -d --build
curl -fsS https://API_DOMAIN/health
```

The body contains `"ok": true` and the current version. Open `https://ADMIN_DOMAIN` and sign in with the email from `.env`. Gateway keys can stay empty: live charges stay closed until a complete staging E2E v2 runner is implemented and passes.

### Features

The shop sells VPN subscriptions. A buyer picks a plan, pays, and receives a Remnawave subscription link. VPN nodes live in the Remnawave panel. This repository does not provision them.

| Part | Path | Role |
| --- | --- | --- |
| API | `backend/app/main.py` | Buyers, plans, payments, fulfillment, admin methods |
| Bot | `backend/app/bot.py` | Telegram: start, prices, promo code, Mini App link |
| Worker | `backend/worker.py` | Queue, fulfillment retry, trial, payment reconciliation |
| Admin | `admin/` | Staff sign-in, plans, payments, users, content |
| Mini App | `miniapp/` | Purchase inside Telegram |
| Cabinet | `cabinet/` | Email sign-in, subscription overview, payment, connect |
| Apps | `mobile/` | Android and iOS for the buyer and the administrator |
| Support Pro | `support-pro/` | Separate ticket desk |
| Edge | `docker-compose.yml`, `deploy/Caddyfile` | HTTPS and separate hostnames |

PostgreSQL stores the data. Redis holds queues and locks. The schema changes only through Alembic migrations in `backend/alembic`.

A buyer can:

- Register by email in the personal cabinet, or sign in with Telegram, VK, and Yandex when those logins are set in `.env`.
- Open the Mini App from the bot and see the plans.
- Buy a fixed plan or assemble duration, traffic, and device count in the plan constructor when an administrator has enabled it.
- Apply a promo code. The discount and term are frozen on the payment snapshot.
- Take a trial when there is no active subscription.
- Top up the internal wallet and spend it on a plan. The same `Idempotency-Key` cannot debit twice. An amount of 0 or less is refused before any gateway call.
- Buy and redeem a gift card. A card credits the wallet only in `DEFAULT_CURRENCY`.
- Open the subscription link, download it as a file, and show a QR code for Happ, v2rayNG, and Streisand when the link starts with `https://`.
- Cancel at the end of the paid term.
- Read payments in the billing center.
- Download Android and iOS apps from the cabinet cards. Older release APK links stay in the history section below. New builds are uploaded by an administrator.

An administrator can:

- Sign in with email and password. Roles are `viewer`, `operator`, and `admin`. A `viewer` cannot read subscription keys.
- Turn on TOTP. Sessions are bound to the browser and end after 15 minutes idle or a User-Agent change.
- Create and disable plans, the constructor, promo codes, campaigns, and cabinet menu items.
- Read payments, refund a paid order, and retry fulfillment when Remnawave failed. A retry works only for status `paid`.
- Upload APK and IPA files. Buyers download from the cabinet. Administrators download from the panel.
- Queue a Telegram broadcast. The bot process delivers it.
- Turn on maintenance mode. New payments are refused while it is on.
- Read the audit log. Panel responses omit exception text and provider secrets.
- Register a node and start failover only with the `provision_nodes` permission.

The first administrator is created from `ADMIN_EMAIL` and `ADMIN_PASSWORD` when the administrator table is empty.

Live fulfillment calls Remnawave with `REMNAWAVE_URL` and `REMNAWAVE_TOKEN`. The shop creates or extends the user and stores the term, traffic limit, and link. Repeating the same operation does not extend the term twice. Refreshing the card from the panel does not copy a later expiry into the paid subscription. Without those two variables the sandbox writes `sandbox://local/...` and `sandbox-user-{id}`. That mark is a shop check, not a working VPN.

### Start with payment systems

Bring the shop up with the VDS section first. Use `APP_ENV=production`, `PAYMENTS_SANDBOX=false`, and `COOKIE_SECURE=true`. Fill only the keys you will use. An empty key removes that provider from the route. Then run `docker compose up -d`.

| Provider | Variables | Webhook |
| --- | --- | --- |
| YooKassa | `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_WEBHOOK_IP_ALLOWLIST` | `POST https://API_DOMAIN/api/webhooks/yookassa` |
| Platega | `PLATEGA_MERCHANT_ID`, `PLATEGA_SECRET` | `POST https://API_DOMAIN/api/webhooks/platega` |
| RollyPay | `ROLLYPAY_API_KEY`, `ROLLYPAY_SIGNING_SECRET` | `POST https://API_DOMAIN/api/webhooks/rollypay` |
| Stripe | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | `POST https://API_DOMAIN/api/payments/webhooks/stripe` |
| PayPal | `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID` | `POST https://API_DOMAIN/api/payments/webhooks/paypal` |
| Crypto gateway | `CRYPTO_GATEWAY_URL`, `CRYPTO_GATEWAY_KEY` | `POST https://API_DOMAIN/api/webhooks/crypto` |

`YOOKASSA_API_URL` defaults to `https://api.yookassa.ru`. `PLATEGA_API_URL` defaults to `https://app.platega.io`. `ROLLYPAY_API_URL` defaults to `https://rollypay.io`. The address is checked as a public URL. Platega and RollyPay refunds need `PLATEGA_REFUND_URL`, `PLATEGA_REFUND_STATUS_URL`, `ROLLYPAY_REFUND_URL`, and `ROLLYPAY_REFUND_STATUS_URL`. `ROLLYPAY_TEST_MODE=true` is the gateway test invoice, not the shop sandbox. SEPA does not open a redirect checkout.

1. YooKassa. Copy the shop id and secret key into `.env`. In YooKassa notifications set the webhook URL and the successful-payment event. Put YooKassa networks in `YOOKASSA_WEBHOOK_IP_ALLOWLIST`, comma-separated. An empty list refuses every notice. The shop reads the nearest proxy address: Caddy sets `X-Forwarded-For` from the real client.
2. Platega. Store the merchant id and secret. Set the webhook in the Platega cabinet. The notice must carry `X-MerchantId` and `X-Secret`. Before fulfillment the shop reads the transaction again and compares the amount and the order id.
3. RollyPay. Store the API key and the signing secret. The notice must carry `X-Signature` (HMAC-SHA256 of the body) and `X-Timestamp`. A stamp older than five minutes is refused.
4. Stripe. Point the Stripe webhook at `POST /api/payments/webhooks/stripe` and store the signing secret in `STRIPE_WEBHOOK_SECRET`. A subscription is applied only when the provider reports `paid` or `succeeded` and the amount, currency, and `order_id` match. An unpaid checkout session does not grant a plan.
5. PayPal. Point the webhook at `POST /api/payments/webhooks/paypal` and set `PAYPAL_WEBHOOK_ID`. The order is applied when PayPal reports `COMPLETED`, the amount and currency match, and a capture is completed.
6. Crypto gateway. `POST /api/webhooks/crypto` requires `X-Timestamp` (unix seconds, five-minute window) and `X-Signature` equal to the hex HMAC-SHA256 of `{timestamp}.{raw body}` with `CRYPTO_GATEWAY_KEY`. The shop then calls `GET {CRYPTO_GATEWAY_URL}/payments/{id}` and accepts `paid`, `succeeded`, `success`, or `confirmed` only when the amount, currency, and `order_id` match.
7. Apple and Google. `MOBILE_STORE_PRODUCTS` is JSON: the key is the store product id and the value is the shop plan id. Example: `{"com.shop.month": 1}`. An empty value refuses `POST /api/payments/mobile/verify`. An Apple receipt without `transactionId` and App Store Server API keys is refused. A Google Play receipt is accepted only for `SUBSCRIPTION_STATE_ACTIVE`, and the product in Google's answer must be in that map.
8. Open live charges. Keys are not enough. A staging run must cover the invoice, the webhook, fulfillment, a repeat of the same webhook, and a refund. The result must be younger than 24 hours and carry `FULL_E2E_PASS`. In the panel, with `security.manage`, save staging keys that differ from the live keys in `.env`. Then call `POST /api/admin/payments/production-gate` with `{"enabled": true}`. A stale check answers `409`. Turn it off with `{"enabled": false}`. While the flag is off, the buyer sees that live payments are temporarily blocked.
9. Check one payment. Create a small plan, pay it, and confirm status `paid`, fulfillment `completed`, and a link that starts with `https://`. A repeated webhook does not extend the term. A panel refund revokes access, and a later successful webhook does not grant it again.

`AUTO_RENEW_ENABLED=true` stores a YooKassa payment method for the next period. Leave it off until a manual staging refund has passed. The sandbox does not run recurring charges. A buyer cannot set `tax_exempt` or `reverse_charge`.

Variable tables are in [docs/en/PAYMENTS.md](../../docs/en/PAYMENTS.md).

## Українська

### Тестовий стенд

Стенд піднімає API, адмінку, кабінет і Mini App без YooKassa, Platega, RollyPay, Stripe, PayPal, Telegram і Remnawave. Посилання підписки буде `sandbox://local/...`. Це перевірка магазину, а не робочий VPN.

Потрібні Docker Engine, плагін Compose і вільні порти 18080–18083.

```bash
git clone https://github.com/booarkz-cpu/shop-by-boo.git vpn-shop-src
cd vpn-shop-src
bash scripts/test-up.sh
```

Скрипт створює `.env.test` з випадковими секретами, передає його Compose і збирає `docker-compose.test.yml`, чекає на `http://127.0.0.1:18080/health` і купує тариф «Тестовый месяц» через пісочницю. Пароль адміністратора друкується один раз. Пошта — `admin@example.test`.

| Поверхня | Адреса |
| --- | --- |
| API | http://127.0.0.1:18080/health |
| Адмінка | http://127.0.0.1:18081 |
| Кабінет | http://127.0.0.1:18082 |
| Mini App | http://127.0.0.1:18083 |

Порти доступні лише через `127.0.0.1`. Для віддаленої перевірки створіть SSH-тунель: `ssh -L 18081:127.0.0.1:18081 user@server`. `COOKIE_SECURE=false` годиться лише для локального стенду.

Зупинка: `docker compose --env-file .env.test -f docker-compose.test.yml down`. Прапор `-v` видаляє базу.

### Встановлення на VDS

Бойовий магазин приймає замовлення через HTTPS. Потрібні Ubuntu або Debian, root по SSH, домен і п'ять імен на IP сервера: API, адмінка, Mini App, кабінет і Support Pro. Ще потрібні панель Remnawave і токен бота від @BotFather. Встановлювач сам відкриває SSH, TCP 80, TCP 443 і UDP 443 у файрволі сервера. PostgreSQL, Redis і порт застосунку назовні не публікуються. Якщо в хостера є окремий файрвол панелі, дозвольте в ньому ті самі порти.

Пароль може містити спеціальні символи. У ручному `DATABASE_URL` закодуйте його через `urllib.parse.quote(password, safe='')`; Support Pro використовує окремі змінні `POSTGRES_*`.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git openssl
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
sudo git clone https://github.com/booarkz-cpu/shop-by-boo.git /opt/vpn-shop
cd /opt/vpn-shop
sudo bash install.sh
```

`install.sh` ставить Docker, якщо його ще немає, і запускає `deploy/install-vps.sh`. Питання читаються в терміналі SSH. Той самий результат вручну:

```bash
cd /opt/vpn-shop
cp .env.example .env
openssl rand -hex 32
```

Впишіть у `.env`:

| Змінна | Значення |
| --- | --- |
| `APP_SECRET` | рядок з `openssl rand -hex 32`, не коротший за 32 символи |
| `APP_ENV` | `production` |
| `DB_PASSWORD` і `POSTGRES_PASSWORD` | один і той самий пароль |
| `DATABASE_URL` | той самий пароль у `postgresql+asyncpg://vpnshop:ПАРОЛЬ@db:5432/vpnshop` |
| `BOT_TOKEN` | токен BotFather |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | перший вхід у панель |
| `REMNAWAVE_URL`, `REMNAWAVE_TOKEN` | панель |
| `PUBLIC_BASE_URL`, `MINI_APP_URL`, `CABINET_URL` | адреси `https://` |
| `API_DOMAIN`, `ADMIN_DOMAIN`, `APP_DOMAIN`, `CABINET_DOMAIN` | імена без схеми |
| `SUPPORT_PRO_DOMAIN` | ім'я служби заявок |
| `SUPPORT_PRO_DB_PASSWORD` | окремий пароль бази заявок |
| `SUPPORT_PRO_SSO_SECRET` | ще один рядок `openssl rand -hex 32` |
| `COOKIE_SECURE` | `true` |
| `PAYMENTS_SANDBOX` | `false` |

Без `SUPPORT_PRO_DOMAIN` файл `docker-compose.yml` не стартує.

```bash
cd /opt/vpn-shop
docker compose up -d --build
curl -fsS https://API_DOMAIN/health
```

Відповідь містить `"ok": true` і `"version": "20.0.5"`. Відкрийте `https://ADMIN_DOMAIN` і увійдіть поштою з `.env`. Ключі кас можна лишити порожніми: живі платежі закриті, доки не пройдено staging E2E.

### Можливості

Магазин продає VPN-підписки. Покупець обирає тариф, оплачує його і отримує посилання підписки Remnawave. Вузли VPN живуть у панелі Remnawave: цей репозиторій їх не піднімає.

| Частина | Де лежить | Що робить |
| --- | --- | --- |
| API | `backend/app/main.py` | Покупці, тарифи, платежі, видача підписки, методи панелі |
| Бот | `backend/app/bot.py` | Telegram: старт, ціни, промокод, посилання на Mini App |
| Воркер | `backend/worker.py` | Черга, повтор видачі, пробний період, звірка платежів |
| Адмінка | `admin/` | Вхід співробітника, тарифи, платежі, користувачі, контент |
| Mini App | `miniapp/` | Покупка всередині Telegram |
| Кабінет | `cabinet/` | Вхід поштою, огляд підписки, оплата, підключення |
| Застосунки | `mobile/` | Android і iOS для покупця і адміністратора |
| Support Pro | `support-pro/` | Окрема служба заявок |
| Периметр | `docker-compose.yml`, `deploy/Caddyfile` | HTTPS і окремі домени |

База — PostgreSQL. Черги і блокування — Redis. Схема змінюється лише міграціями Alembic у `backend/alembic`.

Покупець може:

- Зареєструватися поштою в особистому кабінеті або увійти через Telegram, VK і Яндекс, якщо ці входи заповнені в `.env`.
- Відкрити Mini App з бота і побачити тарифи.
- Купити фіксований тариф або зібрати строк, трафік і кількість пристроїв у конструкторі тарифів, якщо адміністратор його увімкнув.
- Застосувати промокод. Знижка і строк фіксуються в знімку платежу.
- Отримати пробний період, якщо чинної підписки немає.
- Поповнити внутрішній баланс і витратити його на тариф. Повторне списання з тим самим `Idempotency-Key` блокується. Сума 0 і менше відхиляється до звернення до каси.
- Купити і погасити подарункову картку. Картка зараховується на баланс лише у валюті `DEFAULT_CURRENCY`.
- Відкрити посилання підписки, завантажити його файлом і подивитися QR для Happ, v2rayNG і Streisand, коли посилання починається з `https://`.
- Увімкнути скасування підписки наприкінці оплаченого строку.
- Дивитися свої платежі в центрі білінгу.
- Завантажити застосунки Android і iOS з карток кабінету. Старі посилання на APK лишаються в історії нижче. Нові збірки адміністратор завантажує в панель сам.

Адміністратор може:

- Увійти поштою і паролем. Ролі: `viewer`, `operator`, `admin`. Роль `viewer` не бачить ключі підписки.
- Увімкнути TOTP. Сесії прив'язані до браузера і гасяться після 15 хвилин бездіяльності або зміни User-Agent.
- Створювати і вимикати тарифи, конструктор, промокоди, акції і пункти меню кабінету.
- Дивитися платежі, повертати оплачене замовлення і повторювати видачу, якщо Remnawave відповів помилкою. Повтор працює лише для статусу `paid`.
- Завантажувати APK і IPA. Покупець завантажує файл з кабінету, адміністратор — з панелі.
- Робити розсилку в Telegram. Повідомлення стає в чергу, доставляє процес бота.
- Увімкнути технічний режим. Поки він увімкнений, нові платежі відхиляються.
- Дивитися журнал аудиту. У відповіді панелі немає тексту винятку і секрету провайдера.
- Реєструвати вузол і запускати failover лише з правом `provision_nodes`.

Перший адміністратор створюється з `ADMIN_EMAIL` і `ADMIN_PASSWORD`, коли таблиця адміністраторів порожня.

Бойова видача ходить у Remnawave за `REMNAWAVE_URL` і `REMNAWAVE_TOKEN`. Магазин створює або подовжує користувача і записує строк, ліміт трафіку і посилання. Повтор тієї самої операції не подовжує строк удруге. Оновлення картки з панелі не копіює пізніший строк в оплачену підписку. Без цих двох змінних пісочниця пише `sandbox://local/...` і `sandbox-user-{id}`: це мітка перевірки, а не робочий VPN.

### Запуск із платіжними системами

Спочатку підніміть магазин за розділом «Встановлення на VDS». `APP_ENV=production`, `PAYMENTS_SANDBOX=false`, `COOKIE_SECURE=true`. Заповніть лише ті ключі, якими будете користуватися. Порожній ключ вимикає провайдера. Потім `docker compose up -d`.

| Провайдер | Змінні | Вебхук |
| --- | --- | --- |
| YooKassa | `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_WEBHOOK_IP_ALLOWLIST` | `POST https://API_DOMAIN/api/webhooks/yookassa` |
| Platega | `PLATEGA_MERCHANT_ID`, `PLATEGA_SECRET` | `POST https://API_DOMAIN/api/webhooks/platega` |
| RollyPay | `ROLLYPAY_API_KEY`, `ROLLYPAY_SIGNING_SECRET` | `POST https://API_DOMAIN/api/webhooks/rollypay` |
| Stripe | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | `POST https://API_DOMAIN/api/payments/webhooks/stripe` |
| PayPal | `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID` | `POST https://API_DOMAIN/api/payments/webhooks/paypal` |
| Криптошлюз | `CRYPTO_GATEWAY_URL`, `CRYPTO_GATEWAY_KEY` | `POST https://API_DOMAIN/api/webhooks/crypto` |

`YOOKASSA_API_URL` за замовчуванням `https://api.yookassa.ru`. `PLATEGA_API_URL` — `https://app.platega.io`. `ROLLYPAY_API_URL` — `https://rollypay.io`. Адреса перевіряється як публічний URL. Повернення Platega і RollyPay потребують `PLATEGA_REFUND_URL`, `PLATEGA_REFUND_STATUS_URL`, `ROLLYPAY_REFUND_URL` і `ROLLYPAY_REFUND_STATUS_URL`. `ROLLYPAY_TEST_MODE=true` — тестовий рахунок каси, а не пісочниця магазину. SEPA redirect-checkout не відкриває.

1. YooKassa. У кабінеті ЮKassa візьміть shop id і секретний ключ і запишіть їх у `.env`. У сповіщеннях вкажіть URL вебхука і подію успішної оплати. У `YOOKASSA_WEBHOOK_IP_ALLOWLIST` перелічіть мережі ЮKassa через кому. Порожній список відхиляє всі сповіщення. Магазин дивиться адресу найближчого проксі: Caddy підставляє `X-Forwarded-For` із реального клієнта.
2. Platega. Запишіть merchant id і секрет. У кабінеті Platega вкажіть вебхук. Сповіщення має приходити з `X-MerchantId` і `X-Secret`. Перед видачею магазин ще раз читає транзакцію і звіряє суму і номер замовлення.
3. RollyPay. Запишіть API-ключ і секрет підпису. Сповіщення мусить містити `X-Signature` (HMAC-SHA256 тіла) і `X-Timestamp`. Мітка старша за п'ять хвилин відхиляється.
4. Stripe. У кабінеті Stripe вкажіть вебхук `POST /api/payments/webhooks/stripe` і секрет підпису в `STRIPE_WEBHOOK_SECRET`. Підписка вмикається лише якщо провайдер відповів `paid` або `succeeded`, а сума, валюта і `order_id` збіглися. Неоплачена сесія checkout підписку не вмикає.
5. PayPal. Вкажіть вебхук `POST /api/payments/webhooks/paypal` і `PAYPAL_WEBHOOK_ID`. Замовлення проводиться, коли PayPal у статусі `COMPLETED`, сума і валюта збіглися і є завершене захоплення.
6. Криптошлюз. Вебхук `POST /api/webhooks/crypto` вимагає `X-Timestamp` (unix-секунди, вікно 5 хвилин) і `X-Signature` = hex HMAC-SHA256 від `{timestamp}.{сире тіло}` ключем `CRYPTO_GATEWAY_KEY`. Потім магазин робить `GET {CRYPTO_GATEWAY_URL}/payments/{id}` і приймає статуси `paid`, `succeeded`, `success`, `confirmed` лише коли збіглися сума, валюта і `order_id`.
7. Apple і Google. `MOBILE_STORE_PRODUCTS` — JSON, де ключ це id продукту, а значення це id тарифу. Приклад: `{"com.shop.month": 1}`. Порожня змінна відхиляє `POST /api/payments/mobile/verify`. Чек Apple без `transactionId` і без ключів App Store Server API відхиляється. Чек Google Play годиться лише при `SUBSCRIPTION_STATE_ACTIVE`, і продукт із відповіді Google має бути в цій карті.
8. Відкрийте бойові платежі. Ключів недостатньо. Потрібен успішний staging: рахунок, вебхук, видача, повтор того самого вебхука і повернення. Результат має бути не старший за 24 години, зі статусом `FULL_E2E_PASS`. У панелі, з правом `security.manage`, збережіть staging-ключі, які не збігаються з бойовими ключами з `.env`. Потім `POST /api/admin/payments/production-gate` з тілом `{"enabled": true}`. Якщо перевірка застаріла, відповідь `409`. Вимкнення: `{"enabled": false}`. Поки прапор вимкнений, покупець бачить «Реальные платежи временно заблокированы».
9. Перевірте один платіж. Створіть тариф з маленькою ціною, оплатіть його, переконайтеся, що статус `paid`, видача `completed`, а посилання починається з `https://`. Повторний вебхук строк не подовжує. Повернення з панелі відкликає доступ, і повторний успішний вебхук підписку не повертає.

`AUTO_RENEW_ENABLED=true` зберігає спосіб оплати ЮKassa для наступного періоду. Не вмикайте автопродовження, доки ручне повернення на staging не пройшло. Пісочниця рекурентні списання не виконує. Покупець не може сам поставити `tax_exempt` або `reverse_charge`.

Докладні таблиці змінних — у [docs/uk/PAYMENTS.md](../../docs/uk/PAYMENTS.md).

## Changelog

### 20.0.5

Сверка потерянного счёта ЮKassa больше не создаёт второй платёж. Планировщик и `POST /api/admin/payments/reconcile` ищут уже созданный счёт через `find_by_order_id`. Новый счёт ЮKassa использует `Idempotence-Key`, равный номеру заказа. Заметки: [.github/release-v20.0.5.md](../../.github/release-v20.0.5.md).

A lost YooKassa invoice is no longer turned into a second charge. The scheduler and `POST /api/admin/payments/reconcile` look up the existing invoice with `find_by_order_id`. A new YooKassa invoice uses an `Idempotence-Key` equal to the order id. Notes: [.github/release-v20.0.5.md](../../.github/release-v20.0.5.md).

Звірка втраченого рахунку ЮKassa більше не створює другий платіж. Планувальник і `POST /api/admin/payments/reconcile` шукають уже створений рахунок через `find_by_order_id`. Новий рахунок ЮKassa використовує `Idempotence-Key`, рівний номеру замовлення. Нотатки: [.github/release-v20.0.5.md](../../.github/release-v20.0.5.md).

### 20.0.4

Версия в коде — `20.0.4`. Её отдают `GET /health` и `GET /api/public/v16/release`. Регистрация узла и failover требуют право `provision_nodes`. Обновление с GitHub читает репозиторий проекта. Заметки: [.github/release-v20.0.4.md](../../.github/release-v20.0.4.md).

The code version is `20.0.4`. `GET /health` and `GET /api/public/v16/release` return it. Node registration and failover require the `provision_nodes` permission. The GitHub updater reads the project repository. Notes: [.github/release-v20.0.4.md](../../.github/release-v20.0.4.md).

Версія в коді — `20.0.4`. Її віддають `GET /health` і `GET /api/public/v16/release`. Реєстрація вузла і failover потребують права `provision_nodes`. Оновлення з GitHub читає репозиторій проєкту. Нотатки: [.github/release-v20.0.4.md](../../.github/release-v20.0.4.md).

### 20.0.3

Нулевой заказ не проводится. Stripe, PayPal и криптошлюз сверяются с API провайдера. Вебхук криптошлюза: `POST /api/webhooks/crypto`. Заметки: [.github/release-v20.0.3.md](../../.github/release-v20.0.3.md).

A zero-amount order is not applied. Stripe, PayPal and the crypto gateway are checked against the provider API. Crypto webhook: `POST /api/webhooks/crypto`. Notes: [.github/release-v20.0.3.md](../../.github/release-v20.0.3.md).

Нульове замовлення не проводиться. Stripe, PayPal і криптошлюз звіряються з API провайдера. Вебхук криптошлюзу: `POST /api/webhooks/crypto`. Нотатки: [.github/release-v20.0.3.md](../../.github/release-v20.0.3.md).

### 20.0.2

Поддельный чек Apple больше не выдаёт подписку. Stripe и PayPal проводят заказ только при совпадении суммы и валюты. Карта продуктов: `MOBILE_STORE_PRODUCTS`. Заметки: [.github/release-v20.0.2.md](../../.github/release-v20.0.2.md).

A forged Apple receipt no longer grants a subscription. Stripe and PayPal apply an order only when the amount and currency match. Product map: `MOBILE_STORE_PRODUCTS`. Notes: [.github/release-v20.0.2.md](../../.github/release-v20.0.2.md).

Підроблений чек Apple більше не видає підписку. Stripe і PayPal проводять замовлення лише коли сума і валюта збігаються. Карта продуктів: `MOBILE_STORE_PRODUCTS`. Нотатки: [.github/release-v20.0.2.md](../../.github/release-v20.0.2.md).

### 20.0.1

Тестовый стенд слушает TCP 18080–18083 только на localhost. Установщик VDS сам открывает SSH, TCP 80, TCP 443 и UDP 443. Заметки релиза: [.github/release-v20.0.1.md](../../.github/release-v20.0.1.md).

The test stack binds TCP 18080–18083 to localhost only. The VDS installer opens SSH, TCP 80, TCP 443 and UDP 443. Release notes: [.github/release-v20.0.1.md](../../.github/release-v20.0.1.md).

Тестовий стенд слухає TCP 18080–18083 лише на localhost. Встановлювач VDS сам відкриває SSH, TCP 80, TCP 443 і UDP 443. Нотатки релізу: [.github/release-v20.0.1.md](../../.github/release-v20.0.1.md).

Ниже сохранена история релизов.

---

# Remnawave VPN Shop 3.1.6

Платформа магазина VPN: Telegram-бот, Mini App, отдельный личный кабинет, админ-панель Material Design + Web 3.0, отдельные приложения Android и iOS для покупателя и администратора, API, платежи YooKassa / Platega / RollyPay и sandbox без шлюзов, конструктор тарифа, статус узлов Remnawave, антиабьюз, агент узла, выдача доступа, очереди и резервные копии.

Состояние: **3.1.6**. Предыдущие релизы: **3.1.5**, **3.1.4**, **3.1.3**, **3.1.2**, **3.1.1**, **3.1.0**, **3.0.1**, **3.0.0-realise**, **2.13.0**, **2.12.0**, **2.11.0**, **2.10.0**, **2.9.0**, **2.8.0**, **2.7.0**, **2.6.0**, **2.5.0** и **2.4.0**. Перед production пройдите `INSTALL_STEPS.md`, `INSTRUCTION.md` (разделы 9.20, 9.19, 9.18, 9.17, 9.16 и 9.15), `MOBILE.md`, `MODULES.md`, `SECURITY.md` и `PRODUCTION_CHECKLIST.md`. Лицензия — `LICENSE`.

## Русский

### Состав

| Часть | Технология | Зачем |
| --- | --- | --- |
| API и бот | Python, FastAPI, aiogram, PostgreSQL, Redis | Магазин, платежи, выдача VPN, фоновые задачи |
| Админка | React, Vite | Тарифы, конструктор, узлы, платформа, платежи и кабинет |
| Mini App | React, Vite, Telegram WebApp | Покупка внутри Telegram |
| Личный кабинет | React, Vite | Вход по email, Telegram, VK и Яндексу |
| Android и iOS | Kotlin Compose, SwiftUI | Покупатель и администратор, русский и английский |
| Периметр | Docker Compose, Caddy | HTTPS и разделение доменов |
| Проверки | `tests/`, `scripts/sandbox-e2e.sh` | Регрессия и прогон без живых касс |

### Возможности 3.1.6

- **Админка больше не отвечает 502.** nginx пишет pid и кэш в `/tmp/nginx`. Caddy открывает домен только после того, как панель отвечает на HTTP.
- Схема остаётся `0038_v2_6_0_platform`. Подробности — раздел 9.20 `INSTRUCTION.md` и `RELEASE_NOTES_V3_1_6.md`.

### Возможности 3.1.5

- **Админка, Mini App и кабинет стартуют на read-only корне.** nginx получает tmpfs для `/var/cache/nginx` и `/run`. В 3.1.4 эти контейнеры писали `Read-only file system` и уходили в `Restarting`.
- Установщик печатает логи панелей, если они перезапускаются, и включает `vm.overcommit_memory=1` для Redis.
- Схема остаётся `0038_v2_6_0_platform`. Подробности — раздел 9.19 `INSTRUCTION.md` и `RELEASE_NOTES_V3_1_5.md`.

### Возможности 3.1.4

- **Первый запуск больше не роняет API.** Backend и worker больше не создают `alembic_version` одновременно. Если контейнер всё же не поднялся, установщик печатает логи backend и worker, а не только `installation failed at line 382`.
- Пробелы в ответах снимаются. Часовой пояс `Moscow` записывается как `Europe/Moscow`.
- Схема остаётся `0038_v2_6_0_platform`. Покупатель Android остаётся **2.10.0**, администратор — **2.12.0**. Подробности — раздел 9.18 `INSTRUCTION.md` и `RELEASE_NOTES_V3_1_4.md`.

### Возможности 3.1.3

- **Установка через `curl | bash` дожидается ответов.** Канал занят скриптом, поэтому вопросы читаются с терминала SSH. В 3.1.2 первый вопрос завершался `installation failed at line 34`.
- Схема остаётся `0038_v2_6_0_platform`. Покупатель Android остаётся **2.10.0**, администратор — **2.12.0**. Подробности — раздел 9.17 `INSTRUCTION.md` и `RELEASE_NOTES_V3_1_3.md`.

### Возможности 3.1.2

- **Ключи VPN не видны роли viewer.** Подписка и ключи Remnawave требуют право `users.keys`. Списки и карточка пользователя отдают поля без ссылки подписки и паролей. Обзор показывает только общее число пользователей.
- **Ответы панели без текста исключения.** Диагностика, задания, копии, провайдеры, выплаты, мониторы, журнал аудита и причины возвратов не возвращают stderr и строки исключений. Подробность остаётся в журнале процесса.
- **UUID пользователя Remnawave.** Карточка, продление, подписка и ключи принимают строковый идентификатор.
- Схема остаётся `0038_v2_6_0_platform`. Покупатель Android остаётся **2.10.0**, администратор — **2.12.0**. Подробности — раздел 9.16 `INSTRUCTION.md` и `RELEASE_NOTES_V3_1_2.md`.

### Возможности 3.1.1

- **Секреты staging сохраняются.** Повторное сохранение вкладки **Проверка тестового контура** оставляет пустое поле секрета, Shop ID и Merchant ID как уже записанное значение. Совпадение с ключами из `.env` по-прежнему отклоняется.
- **Адрес оплаты в журнале.** Раннер печатает `[CHECKOUT]` и https-ссылку. Статус `awaiting_checkout` production gate не открывает. Кнопка **Разрешить реальные платежи** ждёт `FULL_E2E_PASS` моложе 24 часов. Порядок — раздел 9.15 `INSTRUCTION.md`.
- **Журнал без секретов.** Перед записью статуса токены и секреты длиннее 7 символов заменяются на `[скрыто]`.
- **Установка по шагам.** `INSTALL_STEPS.md` перечисляет каждый вопрос `install.sh` и `deploy/install-vps.sh`.
- Схема остаётся `0038_v2_6_0_platform`. Покупатель Android остаётся **2.10.0**, администратор — **2.12.0**. Подробности — `RELEASE_NOTES_V3_1_1.md`.

### Возможности 3.1.0

- **Публичный список тарифов** больше не отдаёт `remnawave_profile_id`. Идентификатор профиля остаётся в панели администратора и в снимке платежа.
- **Статус автопродления** для покупателя при ошибке отвечает фразой «Автопродление не выполнено». Текст исключения остаётся в базе и в журнале.
- **Контрольная сумма пакета.** Загрузка APK или IPA считает SHA-256. Кабинет и панель показывают её только вместе со ссылкой на скачивание. Имя файла на диске по-прежнему скрыто.
- **Файл подписки.** `GET /api/me/subscription-file` отдаёт ссылку подписки текстовым файлом `remnawave-subscription.txt`. В кабинете, вкладка «Подключение», кнопка **Скачать подписку**.
- **Справка по установке.** `GET /api/public/apps/install` возвращает карточки магазина, официальные ссылки GitHub и шаги на русском и английском.
- Схема остаётся `0038_v2_6_0_platform`. Покупатель Android остаётся **2.10.0**, администратор — **2.12.0**. Подробности — раздел 9.14 в `INSTRUCTION.md` и `RELEASE_NOTES_V3_1_0.md`.

### Как скачать приложения для Android и iOS

Пакеты проекта и файл, который загрузил администратор вашего магазина, — разные ссылки. Кабинет отдаёт загруженный файл. Ссылки ниже — сборки этого репозитория.

**Android, покупатель 2.10.0**

1. Скачайте APK: https://github.com/booarkz-cpu/remnawave-vpn-shop/releases/download/v2.10.0/remnawave_vpn_shop_android_user_2_10_0.apk
2. Скачайте контрольную сумму: https://github.com/booarkz-cpu/remnawave-vpn-shop/releases/download/v2.10.0/remnawave_vpn_shop_android_user_2_10_0.apk.sha256
3. В каталоге, где лежат оба файла, выполните `sha256sum -c remnawave_vpn_shop_android_user_2_10_0.apk.sha256`.
4. На телефоне разрешите установку из выбранного источника и откройте APK.
5. Если администратор магазина загрузил свой APK, в личном кабинете кнопка **Скачать** на карточке Android ведёт на `GET /api/public/apps/android-user/download`. Рядом показана контрольная сумма этого файла.

**Android, администратор 2.12.0**

1. Скачайте APK: https://github.com/booarkz-cpu/remnawave-vpn-shop/releases/download/v2.12.0/remnawave_vpn_shop_android_admin_2_12_0.apk
2. Скачайте контрольную сумму: https://github.com/booarkz-cpu/remnawave-vpn-shop/releases/download/v2.12.0/remnawave_vpn_shop_android_admin_2_12_0.apk.sha256
3. В том же каталоге выполните `sha256sum -c remnawave_vpn_shop_android_admin_2_12_0.apk.sha256`.
4. В панели, вкладка **Приложения**, блок **Скачать приложение администратора** отдаёт файл, загруженный администратором: `GET /api/admin/apps/android-admin/download`. Нужна сессия с правом `read`.

**iOS**

Готового IPA в релизах GitHub нет. Администратор магазина может загрузить подписанный IPA. Тогда кабинет покупателя открывает `GET /api/public/apps/ios-user/download`, а панель — `GET /api/admin/apps/ios-admin/download`. Собрать и подписать пакет можно в Xcode на macOS из каталогов `mobile/ios-user` и `mobile/ios-admin`.

Краткая справка без входа: `GET /api/public/apps/install`.

### Возможности 3.0.1

- **Автопродление и шифрованная копия.** Секрет расшифровывается через `decrypt_secret` из пакета `app`. В контейнере больше нет импорта `backend.app.security`, из‑за которого продление и проверка копии отвечали ошибкой.
- **Баланс списывается один раз.** `POST /api/me/wallet/spend` требует `Idempotency-Key`. Повтор с тем же ключом возвращает уже созданный платёж. Другой ключ на ту же покупку в течение 30 секунд получает 409 и не списывает баланс второй раз. Покупка подарка повторно проверяет ключ уже под блокировкой пользователя.
- **Второй счёт на ту же покупку.** Новый `Idempotency-Key` в течение 30 секунд не открывает второй сеанс провайдера, пока предыдущий счёт на тот же снимок тарифа ещё создаётся или ожидает оплаты.
- Схема остаётся `0038_v2_6_0_platform`. Покупатель Android остаётся **2.10.0**, администратор — **2.12.0**. Подробности — раздел 9.13 в `INSTRUCTION.md`, `SECURITY.md` и `RELEASE_NOTES_V3_0_1.md`.

### Возможности 3.0.0-realise

- **Пакет приложения до 80 МБ.** `POST /api/admin/apps/{id}/file` больше не упирается в общий потолок тела 12 МБ, если у запроса есть `Content-Length`. Запрос без `Content-Length` по-прежнему ограничен 12 МБ. Право `manage_content` проверяется до чтения файла.
- **Секреты не уходят в прокси окружения.** Вызовы Telegram, Яндекс OAuth и Remnawave создают HTTP-клиент с `trust_env=False`.
- **Адрес клиента.** Заголовок `X-Forwarded-For` учитывается только если непосредственный сосед — loopback, частный или link-local адрес (Caddy). Прямой клиент не может подставить адрес из allowlist вебхука.
- **Ответы без текста исключения.** Повтор выдачи и сводка здоровья не возвращают строку исключения. Подробность остаётся в журнале процесса.
- Схема базы остаётся `0038_v2_6_0_platform`. Приложения Android покупателя остаются **2.10.0**, администратора — **2.12.0**. Подробности — раздел 9.12 в `INSTRUCTION.md` и `RELEASE_NOTES_V3_0_0.md`.

### Возможности 2.13.0

- **Скачивание приложений.** Панель, вкладка «Приложения», даёт ссылку на приложение администратора. Личный кабинет даёт ссылку на приложение покупателя. Администратор загружает APK или IPA и меняет тексты, видимость и https-ссылку карточки. Подробности — раздел 9.11 в `INSTRUCTION.md` и `RELEASE_NOTES_V2_13_0.md`.
- Схема базы остаётся `0038_v2_6_0_platform`. Приложения Android покупателя остаются **2.10.0**, администратора — **2.12.0**.

### Возможности 2.12.0

- **Массовая рассылка в Telegram.** Веб-панель, раздел «Маркетинг», и приложения администратора Android и iOS ставят сообщение в очередь `POST /api/admin/broadcasts`. Доставляет процесс бота. Аудитория: все с Telegram, активная подписка или без активной подписки. Кнопка и картинка — только `https://`. Повтор `POST /api/admin/broadcasts/{id}/retry` продолжает с сохранённого счётчика. Подробный разбор — `RELEASE_NOTES_V2_12_0.md` и раздел 9.10 в `INSTRUCTION.md`.
- Приложение администратора Android: `versionName` **2.12.0**, `versionCode` **2120**. iOS-администратор: `MARKETING_VERSION` **2.12.0**. Приложение покупателя остаётся **2.10.0**. Схема базы остаётся `0038_v2_6_0_platform`.

### Возможности 2.11.0

- **README и инструкции на двух языках.** Этот файл и `INSTRUCTION.md`, `INSTALL.md`, `MODULES.md`, `SECURITY.md`, `MOBILE.md` читаются по-русски и по-английски.
- **Обновление всего проекта с GitHub.** Команда на сервере: `sudo bash /opt/vpn-shop/scripts/update-from-github.sh`. Скрипт скачивает zip `full_release` и файл `.sha256` только с GitHub, отклоняет чужой хост, symlink, путь с `..` и архив больше 80 МБ. `.env` не затирается. `scripts/update.sh` сначала снимает снимок текущей установки и делает `pg_dump`, и только потом копирует новые файлы. Ошибка сборки откатывает этот снимок. API архив не распаковывает. Вкладка «Релизы» показывает статус через `GET /api/admin/github-update`. Cron не включён.
- Схема базы остаётся `0038_v2_6_0_platform`. Лицензия прежняя, файл `LICENSE`. APK покупателя и администратора остаются пакетами **2.10.0** из того релиза.

### Возможности 2.10.0

- **Release APK.** `remnawave_vpn_shop_android_user_2_10_0.apk` и `remnawave_vpn_shop_android_admin_2_10_0.apk`, `versionCode` 2100. Сертификат и контрольные суммы — в `RELEASE_NOTES_V2_10_0.md`. Пакеты 2.9.0 были debug-подписаны, перед 2.10.0 их удаляют один раз. Закрытый ключ в релиз не входит.
- **Один шаг подключения.** QR `GET /api/me/connection-qr` и кнопки Happ, v2rayNG, Streisand для `https://` ссылки подписки.
- **Устройства, трафик, подарок и пополнение.** Список устройств без `device_key` и `last_ip`. Трафик с запасным лимитом из снимка. Подарок и пополнение кошелька, включая sandbox при `PAYMENTS_SANDBOX=true`.
- **Вход клиента и биометрия.** Native 2.14.0 использует одноразовый PKCE S256 exchange. Сохранённый токен закрывается биометрией или PIN. Старый общий HMAC ключ больше не поддерживается в production.
- **Telegram.** Срок подписки, пополнение и успешная оплата. Ошибка отправки не откатывает платёж.
- **Дежурство в приложении администратора.** Включение тарифа, карточка платежа без текста ошибки провайдера, признак устаревшего агента.
- **iOS.** Исходники с `MARKETING_VERSION` 2.10.0. IPA собирается в Xcode на macOS. В релизе IPA нет.

### Возможности 2.9.0

- **APK для Android.** Релиз GitHub содержит два debug-подписанных пакета для ручной установки: покупатель `remnawave_vpn_shop_android_user_2_9_0.apk` и администратор `remnawave_vpn_shop_android_admin_2_9_0.apk`. Повторная сборка — `scripts/build-android-apk.sh`.
- **iOS.** Исходники `mobile/ios-user` и `mobile/ios-admin` открываются в Xcode на macOS. IPA собирается там же. В архиве этого релиза IPA нет.
- Платёжная ссылка в приложении покупателя открывается после разбора адреса: `https`, либо `http` только для `localhost`, `127.0.0.1` и `10.0.2.2`.
- User-Agent приложений: `RemnawaveShop-Android-User/2.9.0`, `RemnawaveShop-Android-Admin/2.9.0`, `RemnawaveShop-iOS-User/2.9.0`, `RemnawaveShop-iOS-Admin/2.9.0`.

### Возможности 2.8.0

- **Каталог приложений.** Вкладка админки «Приложения»: тексты на русском и английском, ссылка и видимость для Android и iOS покупателя и администратора.
- **Логотип кабинета и приложений.** Загрузка PNG/JPG/WEBP. Кабинет покупателя и четыре приложения показывают один и тот же файл. Логотип самой панели задаётся отдельно в «Брендинг панели».
- Публичный ответ `GET /api/public/apps` содержит только включённые карточки покупателя.

### Возможности 2.7.0

- **Четыре приложения.** `mobile/android-user`, `mobile/android-admin`, `mobile/ios-user`, `mobile/ios-admin`. Покупатель покупает тариф, собирает конструктор, видит серверы и копирует ссылку подписки. Администратор смотрит обзор, платежи, мониторинг и разбирает нарушения.
- **Язык в приложении.** Переключатель RU/EN. Каталоги `mobile/l10n/user.json` и `mobile/l10n/admin.json`.
- **Сессия.** Заголовок `X-Shop-Client` получает `access_token` в JSON. Веб-вход остаётся на HttpOnly cookie и токен в JSON не кладёт.
- **Лицензия приложений.** Условия описаны в файле `LICENSE`. Разбор функций — `MOBILE.md`.

### Возможности 2.6.0

- **Платформа.** Вкладка «Платформа»: скоринг разделения подписки, агенты узлов, чёрный список HWID, ключи API, исходящие webhook, счётчики стран. Секрет показывается один раз.
- **Агент узла.** `scripts/node-agent.py` отправляет heartbeat и наблюдения. Действия на узле — только `throttle` и `clear`, и только если на узле задан `AGENT_APPLY_TC=1`.
- **Почта и метрики.** Тестовое SMTP-письмо уходит администратору, который нажал кнопку. DKIM выдаёт TXT-запись. `/metrics` добавляет три ряда, дашборд лежит в `deploy/grafana/vpnshop-platform.json`.
- **Кабинет на домашний экран.** `cabinet/public/manifest.webmanifest`.
- **Семь тем админки:** dark, light, midnight, graphite, lagoon, amber, paper.
- **Лицензия.** Файл `LICENSE`, русский и английский текст.

### Возможности 2.5.0

- **Конструктор тарифов.** Администратор задаёт базовую цену и пункты: число устройств, объём трафика (0 = безлимит) и срок в днях. Покупатель собирает комбинацию в кабинете и в Mini App. Цена = база + выбранные пункты. Снимок срока, трафика и устройств записывается в платёж и не меняется, если конструктор потом отредактируют.
- **Мониторинг Remnawave.** В админке вкладка «Мониторинг Remnawave» показывает доступность панели, задержку и статус узлов. Покупатель видит отдельный раздел «Серверы» и краткий статус на обзоре. Публичный и пользовательский ответы не содержат адресов, токенов и сырого JSON панели.
- **Проверка до релиза без касс.** `PAYMENTS_SANDBOX=true` и `bash scripts/sandbox-e2e.sh`. Живые YooKassa, Platega и RollyPay для этого прогона не нужны.
- Интерфейсы и документы GitHub на **русском и английском**.

Уже было в 2.4.0 и сохранено: личный кабинет, CMS вкладок, инструкции Android / iOS / TV / компьютер, кошелёк, подарки, пробный период, промокоды, рефералы, автопродление, RBAC, 2FA, бэкапы.

### Быстрый старт

```bash
cp .env.example .env
# Заполните APP_SECRET, пароль БД, BOT_TOKEN, REMNAWAVE_*, ADMIN_*,
# API_DOMAIN, ADMIN_DOMAIN, APP_DOMAIN, CABINET_DOMAIN.
# Для проверки без касс: PAYMENTS_SANDBOX=true
docker compose up -d --build
bash scripts/sandbox-e2e.sh
```

Одношаговая установка на Debian/Ubuntu:

```bash
sudo bash install.sh
```

Обновление уже установленного магазина с GitHub:

```bash
sudo bash /opt/vpn-shop/scripts/update-from-github.sh
```

Подробности — в `INSTRUCTION.md`, раздел 9.9. Не коммитьте `.env`, токены и пароли.

### Документация

| Файл | Содержание |
| --- | --- |
| `INSTRUCTION.md` | Полная инструкция RU/EN, включая тест без касс и обновление с GitHub |
| `MODULES.md` | Каждый модуль и зачем он нужен, RU/EN |
| `FUNCTIONS.md` | Разбор функций кода, RU/EN |
| `SECURITY.md` | Модель безопасности RU/EN |
| `DOCUMENTATION.md` | Карта актуальных документов и архивных аудитов |
| `LICENSE` | Лицензия Source 2.0, RU/EN |
| `MOBILE.md` | Android и iOS: функции, сессия, логотип, сборка, RU/EN |
| `RELEASE_NOTES_V3_1_0.md` | Аудит 3.1.0, контрольная сумма и скачивание приложений |
| `RELEASE_NOTES_V3_0_1.md` | Аудит 3.0.1: автопродление, копия и баланс |
| `RELEASE_NOTES_V3_0_0.md` | Аудит 3.0.0-realise и результат чеклиста |
| `RELEASE_NOTES_V2_13_0.md` | Скачивание приложений 2.13.0 |
| `RELEASE_NOTES_V2_12_0.md` | Рассылка 2.12.0, разбор функций и проверка |
| `RELEASE_NOTES_V2_11_0.md` | Документация 2.11.0 и безопасный порядок обновления |
| `RELEASE_NOTES_V2_10_0.md` | Что вошло в 2.10.0, release APK, подпись клиента |
| `RELEASE_NOTES_V2_9_0.md` | Что вошло в 2.9.0, APK и сборка iOS |
| `RELEASE_NOTES_V2_8_0.md` | Что вошло в 2.8.0 |
| `RELEASE_NOTES_V2_7_0.md` | Что вошло в 2.7.0 |
| `RELEASE_NOTES_V2_6_0.md` | Что вошло в 2.6.0 и границы реализации |
| `RELEASE_NOTES_V2_5_0.md` | Что вошло в 2.5.0 и чего нет из внешних проектов |
| `INSTALL.md` | Установщик, RU/EN |
| `PRODUCTION_CHECKLIST.md` | Чеклист production |
| `.env.example` | Переменные окружения |

### Локальная проверка

```bash
python3 -m compileall -q backend
python3 -m pytest -q
bash -n install.sh deploy/install-vps.sh scripts/sandbox-e2e.sh scripts/update.sh scripts/update-from-github.sh
cd admin && npm ci && npx vite build
cd ../miniapp && npm install && npx vite build
cd ../cabinet && npm install && npx vite build
```

### Лицензия

**Лицензия исходного кода проекта.** Бесплатно разрешены свой коммерческий VPN-магазин, внутренние изменения и распространение собранных клиентских приложений своим покупателям. Условия и ограничения на публикацию исходников — в [LICENSE](../../LICENSE).

## English

A VPN shop with a Telegram bot, a Mini App, a standalone user cabinet, an admin console, separate Android and iOS apps for buyers and administrators, a FastAPI backend, three payment providers plus a sandbox provider, a tariff constructor, Remnawave node status, abuse scoring, a node agent, provisioning, queues and backups.

Release version: **v20.0.14**. Previous published version: **v20.0.13**. Earlier series: **3.1.5**, **3.1.4**, **3.1.3**, **3.1.2**, **3.1.1**, **3.1.0**, **3.0.1**, **3.0.0-realise**, **2.13.0**, **2.12.0**, **2.11.0**, **2.10.0**, **2.9.0**, **2.8.0**, **2.7.0**, **2.6.0**, **2.5.0** and **2.4.0**. Read `INSTALL_STEPS.md`, sections 9.20, 9.19, 9.18, 9.17, 9.16 and 9.15 of `INSTRUCTION.md`, `MOBILE.md`, `MODULES.md`, `SECURITY.md` and `PRODUCTION_CHECKLIST.md` before production. The license is `LICENSE`.

### What is in the tree

| Part | Stack | Role |
| --- | --- | --- |
| API and bot | Python, FastAPI, aiogram, PostgreSQL, Redis | Shop, payments, VPN provisioning, background jobs |
| Admin | React, Vite | Plans, constructor, nodes, platform, payments, cabinet |
| Mini App | React, Vite, Telegram WebApp | Purchase inside Telegram |
| User cabinet | React, Vite | Sign-in with email, Telegram, VK and Yandex |
| Android and iOS | Kotlin Compose, SwiftUI | Buyer and administrator, Russian and English |
| Edge | Docker Compose, Caddy | HTTPS and separate domains |
| Checks | `tests/`, `scripts/sandbox-e2e.sh` | Regression and a run without live gateways |

### What 3.1.6 adds

- **The admin UI no longer answers 502.** nginx writes its pid and cache under `/tmp/nginx`. Caddy opens the domain only after the panel answers HTTP.
- The schema stays `0038_v2_6_0_platform`. Details are in section 9.20 of `INSTRUCTION.md` and in `RELEASE_NOTES_V3_1_6.md`.

### What 3.1.5 adds

- **The admin UI, Mini App, and cabinet start on a read-only root.** nginx gets tmpfs mounts for `/var/cache/nginx` and `/run`. In 3.1.4 those containers logged `Read-only file system` and stayed in `Restarting`.
- The installer prints the panel logs when they restart, and sets `vm.overcommit_memory=1` for Redis.
- The schema stays `0038_v2_6_0_platform`. Details are in section 9.19 of `INSTRUCTION.md` and in `RELEASE_NOTES_V3_1_5.md`.

### What 3.1.4 adds

- **The first boot no longer drops the API.** Backend and worker no longer create `alembic_version` at the same time. If a container still does not start, the installer prints the backend and worker logs instead of only `installation failed at line 382`.
- Answers are trimmed. The time zone `Moscow` is stored as `Europe/Moscow`.
- The schema stays `0038_v2_6_0_platform`. The Android buyer app stays **2.10.0** and the administrator app stays **2.12.0**. Details are in section 9.18 of `INSTRUCTION.md` and in `RELEASE_NOTES_V3_1_4.md`.

### What 3.1.3 adds

- **`curl | bash` waits for answers.** The pipe is occupied by the script, so questions are read from the SSH terminal. In 3.1.2 the first question ended with `installation failed at line 34`.
- The schema stays `0038_v2_6_0_platform`. The Android buyer app stays **2.10.0** and the administrator app stays **2.12.0**. Details are in section 9.17 of `INSTRUCTION.md` and in `RELEASE_NOTES_V3_1_3.md`.

### What 3.1.2 adds

- **VPN keys are hidden from role viewer.** A Remnawave subscription and connection keys require `users.keys`. User lists and the user card omit the subscription URL and passwords. Overview shows only the user total.
- **Panel responses omit exception text.** Diagnostics, jobs, backups, providers, payouts, monitors, the audit log, and refund reasons do not return stderr or exception strings. The detail stays in the process log.
- **Remnawave user UUIDs.** The user card, extension, subscription, and keys accept a string identifier.
- The schema stays `0038_v2_6_0_platform`. The Android buyer app stays **2.10.0** and the administrator app stays **2.12.0**. Details are in section 9.16 of `INSTRUCTION.md` and in `RELEASE_NOTES_V3_1_2.md`.

### What 3.1.1 adds

- **Staging secrets are kept.** Saving **Проверка тестового контура** (Staging checks) again leaves a blank secret, Shop ID, or Merchant ID as the value already stored. A match with the `.env` keys is still rejected.
- **The payment URL is in the log.** The runner prints `[CHECKOUT]` and an https link. Status `awaiting_checkout` does not open the production gate. **Разрешить реальные платежи** (Allow live payments) waits for `FULL_E2E_PASS` younger than 24 hours. The order is section 9.15 of `INSTRUCTION.md`.
- **The log hides secrets.** Before the status is stored, tokens and secrets of 8 characters or more are replaced with `[скрыто]`.
- **Step-by-step install.** `INSTALL_STEPS.md` lists every prompt from `install.sh` and `deploy/install-vps.sh`.
- The schema stays `0038_v2_6_0_platform`. The Android buyer app stays **2.10.0** and the administrator app stays **2.12.0**. Details are in `RELEASE_NOTES_V3_1_1.md`.

### What 3.1.0 adds

- **The public plan list** no longer returns `remnawave_profile_id`. The profile id stays in the administrator panel and on the payment snapshot.
- **Auto-renew status** for the buyer answers «Автопродление не выполнено» when a renewal failed. The exception text stays in the database and in the log.
- **Package checksum.** An APK or IPA upload stores SHA-256. The cabinet and the panel show it only next to a download link. The stored file name stays hidden.
- **Subscription file.** `GET /api/me/subscription-file` returns the subscription URL as `remnawave-subscription.txt`. In the cabinet Connection tab the button is **Скачать подписку** (Download subscription).
- **Install guide.** `GET /api/public/apps/install` returns the shop cards, the official GitHub links and the steps in Russian and English.
- The schema stays `0038_v2_6_0_platform`. The Android buyer app stays **2.10.0** and the administrator app stays **2.12.0**. Details are in section 9.14 of `INSTRUCTION.md` and in `RELEASE_NOTES_V3_1_0.md`.

### How to download the Android and iOS apps

The project packages and the file an administrator uploaded to your shop are different links. The cabinet serves the uploaded file. The links below are the builds from this repository.

**Android buyer 2.10.0**

1. Download the APK: https://github.com/booarkz-cpu/remnawave-vpn-shop/releases/download/v2.10.0/remnawave_vpn_shop_android_user_2_10_0.apk
2. Download the checksum: https://github.com/booarkz-cpu/remnawave-vpn-shop/releases/download/v2.10.0/remnawave_vpn_shop_android_user_2_10_0.apk.sha256
3. In the directory that holds both files, run `sha256sum -c remnawave_vpn_shop_android_user_2_10_0.apk.sha256`.
4. On the phone, allow installation from the source you chose and open the APK.
5. When a shop administrator has uploaded their own APK, the cabinet **Скачать** (Download) button on the Android card opens `GET /api/public/apps/android-user/download`. The checksum of that file is shown beside the button.

**Android administrator 2.12.0**

1. Download the APK: https://github.com/booarkz-cpu/remnawave-vpn-shop/releases/download/v2.12.0/remnawave_vpn_shop_android_admin_2_12_0.apk
2. Download the checksum: https://github.com/booarkz-cpu/remnawave-vpn-shop/releases/download/v2.12.0/remnawave_vpn_shop_android_admin_2_12_0.apk.sha256
3. In the same directory, run `sha256sum -c remnawave_vpn_shop_android_admin_2_12_0.apk.sha256`.
4. In the panel, the Apps tab, the block **Скачать приложение администратора** (Download the administrator app) serves the file an administrator uploaded: `GET /api/admin/apps/android-admin/download`. The session needs the `read` permission.

**iOS**

GitHub releases do not include an IPA. A shop administrator can upload a signed IPA. The buyer cabinet then opens `GET /api/public/apps/ios-user/download`, and the panel opens `GET /api/admin/apps/ios-admin/download`. Build and sign the package in Xcode on macOS from `mobile/ios-user` and `mobile/ios-admin`.

The public summary is `GET /api/public/apps/install`.

### What 3.0.1 adds

- **Auto-renew and encrypted backups.** Secrets are decrypted with `decrypt_secret` from the `app` package. The container no longer imports `backend.app.security`, which made renewal and backup validation fail.
- **The wallet is debited once.** `POST /api/me/wallet/spend` requires `Idempotency-Key`. The same key returns the payment already created. A different key for the same purchase within 30 seconds receives 409 and does not debit the balance again. Gift purchase re-checks the key while the user row is locked.
- **A second invoice for the same purchase.** A new `Idempotency-Key` within 30 seconds does not open another provider session while the previous invoice for the same plan snapshot is still being created or is waiting for payment.
- The schema stays `0038_v2_6_0_platform`. The Android buyer app stays **2.10.0** and the administrator app stays **2.12.0**. Details are in section 9.13 of `INSTRUCTION.md`, in `SECURITY.md` and in `RELEASE_NOTES_V3_0_1.md`.

### What 3.0.0-realise adds

- **App packages up to 80 MB.** `POST /api/admin/apps/{id}/file` is no longer cut by the global 12 MB body ceiling when the request has `Content-Length`. A request without `Content-Length` stays at 12 MB. The `manage_content` permission is checked before the file is read.
- **Secrets stay off environment proxies.** Telegram, Yandex OAuth and Remnawave HTTP clients set `trust_env=False`.
- **Client address.** `X-Forwarded-For` is used only when the immediate peer is loopback, private or link-local (Caddy). A direct client cannot supply a webhook allowlist address.
- **Responses omit exception text.** Provisioning retry and the health summary do not return the exception string. The detail stays in the process log.
- The database schema stays `0038_v2_6_0_platform`. The buyer Android app stays **2.10.0**. The administrator Android app stays **2.12.0**. Details are in section 9.12 of `INSTRUCTION.md` and in `RELEASE_NOTES_V3_0_0.md`.

### What 2.13.0 adds

- **App downloads.** The admin Apps tab links to the administrator app. The user cabinet links to the buyer app. An administrator uploads an APK or IPA and edits the card text, visibility and https link. Details are in section 9.11 of `INSTRUCTION.md` and in `RELEASE_NOTES_V2_13_0.md`.
- The database schema stays `0038_v2_6_0_platform`. The buyer Android app stays **2.10.0**. The administrator Android app stays **2.12.0**.

### What 2.12.0 adds

- **Telegram mass broadcast.** The web Marketing section and the Android and iOS administrator apps queue a message with `POST /api/admin/broadcasts`. The bot process delivers it. The audience is everyone with Telegram, an active subscription, or no active subscription. A button and an image accept only `https://`. `POST /api/admin/broadcasts/{id}/retry` continues from the saved counter. The full walkthrough is `RELEASE_NOTES_V2_12_0.md` and section 9.10 of `INSTRUCTION.md`.
- Android administrator app: `versionName` **2.12.0**, `versionCode` **2120**. iOS administrator app: `MARKETING_VERSION` **2.12.0**. The buyer app stays **2.10.0**. The database schema stays `0038_v2_6_0_platform`.

### What 2.11.0 adds

- **Bilingual GitHub documents.** This README and the install, module, security and mobile guides are written in Russian and in English.
- **Update the whole project from GitHub.** On the server run `sudo bash /opt/vpn-shop/scripts/update-from-github.sh`. The script downloads the `full_release` zip and the matching `.sha256` from GitHub only. It rejects another host, a symlink, a `..` path and an archive larger than 80 MB. `.env` stays in place. `scripts/update.sh` snapshots the current install and runs `pg_dump` before it copies the new files. A failed build restores that snapshot. The API process does not extract the archive. The admin Releases tab reads `GET /api/admin/github-update`. Cron is not enabled.
- The database schema stays `0038_v2_6_0_platform`. The license file stays `LICENSE`. The buyer and administrator APKs stay the **2.10.0** release packages.

### What 2.10.0 added

Release-signed sideload APKs `remnawave_vpn_shop_android_user_2_10_0.apk` and `remnawave_vpn_shop_android_admin_2_10_0.apk`, `versionCode` 2100. The certificate is in `RELEASE_NOTES_V2_10_0.md`. A 2.9.0 debug APK must be uninstalled once before 2.10.0. The private key is not in the release.

The buyer app shows a subscription QR from `GET /api/me/connection-qr` and opens Happ, v2rayNG and Streisand for an `https://` subscription URL. The device list omits `device_key` and `last_ip`. Traffic falls back to the subscription snapshot limit. Gift redeem and wallet top-up work, including provider `sandbox` when `PAYMENTS_SANDBOX=true`.

Native 2.14.0 login uses one-use PKCE S256 exchange. A saved token is locked with biometrics or the device PIN. Older native clients must be rebuilt. Telegram notices cover expiry, top-up and a successful payment. A send failure does not roll back the payment.

The administrator app can enable a plan, open a payment card without the provider error text, and see a stale agent. iOS sources use `MARKETING_VERSION` 2.10.0. The IPA is built in Xcode on macOS. This release has no IPA.

### What 2.9.0 added

The GitHub release attached two debug-signed sideload APKs, `remnawave_vpn_shop_android_user_2_9_0.apk` and `remnawave_vpn_shop_android_admin_2_9_0.apk`. Rebuild with `scripts/build-android-apk.sh`. iOS sources open in Xcode. A payment URL opens only for `https`, or for `http` on `localhost`, `127.0.0.1` and `10.0.2.2`. The 2.9.0 User-Agent strings are `RemnawaveShop-Android-User/2.9.0`, `RemnawaveShop-Android-Admin/2.9.0`, `RemnawaveShop-iOS-User/2.9.0` and `RemnawaveShop-iOS-Admin/2.9.0`.

### What 2.8.0 added

The admin **Приложения** tab stores Russian and English card text, a link and visibility for the four apps. One PNG, JPG or WEBP logo is shown in the buyer cabinet and in the apps. The panel logo stays in **Брендинг панели**. `GET /api/public/apps` returns only enabled buyer cards.

### What 2.7.0 added

Four apps: `mobile/android-user`, `mobile/android-admin`, `mobile/ios-user`, `mobile/ios-admin`. The buyer pays, builds a tariff, sees servers and copies the subscription link. The administrator reads the overview, payments and monitoring and reviews violations. The RU/EN switch uses `mobile/l10n/user.json` and `mobile/l10n/admin.json`. Header `X-Shop-Client` receives `access_token` in JSON. Web sign-in keeps the JWT in an HttpOnly cookie. The license is the same `LICENSE` file. See `MOBILE.md`.

### What 2.6.0 added

The **Платформа** tab scores subscription sharing, lists node agents, an HWID blacklist, API keys, outbound webhooks and country counts. A secret is shown once. `scripts/node-agent.py` sends a heartbeat. The node may apply only `throttle` and `clear`, and only when `AGENT_APPLY_TC=1`. The SMTP test sends mail to the administrator who pressed the button. DKIM returns a TXT record. Extra Prometheus lines and `deploy/grafana/vpnshop-platform.json` cover the platform. The cabinet can be installed to the home screen via `cabinet/public/manifest.webmanifest`. Admin themes: dark, light, midnight, graphite, lagoon, amber, paper. The license terms are in `LICENSE`.

### What 2.5.0 added

**Конструктор тарифов.** An administrator sets a base price and options for devices, traffic (0 means unlimited) and days. The buyer combines them in the cabinet and in the Mini App. The price is the base plus the chosen options. The duration, traffic and device snapshot is stored on the payment. A public or buyer server response contains no address, token or raw panel JSON. `PAYMENTS_SANDBOX=true` and `bash scripts/sandbox-e2e.sh` exercise the shop without live YooKassa, Platega or RollyPay.

2.4.0 remains: the user cabinet, tab CMS, Android / iOS / TV / computer guides, wallet, gifts, trial, promo codes, referrals, auto-renew, RBAC, 2FA and backups.

### Quick start

```bash
cp .env.example .env
# Fill APP_SECRET, the database password, BOT_TOKEN, REMNAWAVE_*, ADMIN_*,
# API_DOMAIN, ADMIN_DOMAIN, APP_DOMAIN, CABINET_DOMAIN.
# For a gateway-free check: PAYMENTS_SANDBOX=true
docker compose up -d --build
bash scripts/sandbox-e2e.sh
```

One-command install on Debian/Ubuntu:

```bash
sudo bash install.sh
```

Update an existing install from GitHub:

```bash
sudo bash /opt/vpn-shop/scripts/update-from-github.sh
```

The full procedure is `INSTRUCTION.md`, section 9.9. Do not commit `.env`, tokens or passwords.

### Documentation

| File | Contents |
| --- | --- |
| `INSTRUCTION.md` | Full RU/EN guide, including the gateway-free test and the GitHub update |
| `MODULES.md` | Why each module exists, RU/EN |
| `FUNCTIONS.md` | Function map, RU/EN |
| `SECURITY.md` | Security model, RU/EN |
| `DOCUMENTATION.md` | Index of current documents and archived audits |
| `LICENSE` | Source License 2.0, RU/EN |
| `MOBILE.md` | Android and iOS functions, session, logo and build, RU/EN |
| `RELEASE_NOTES_V3_1_0.md` | 3.1.0 audit, checksum and app download steps |
| `RELEASE_NOTES_V3_0_1.md` | 3.0.1 audit: auto-renew, backups and wallet |
| `RELEASE_NOTES_V3_0_0.md` | 3.0.0-realise audit and checklist result |
| `RELEASE_NOTES_V2_13_0.md` | 2.13.0 app downloads |
| `RELEASE_NOTES_V2_12_0.md` | 2.12.0 broadcast, function reference and the check |
| `RELEASE_NOTES_V2_11_0.md` | 2.11.0 documents and the safe update order |
| `INSTALL.md` | Installer, RU/EN |
| `PRODUCTION_CHECKLIST.md` | Production checklist |
| `.env.example` | Environment variables |

### Local check

```bash
python3 -m compileall -q backend
python3 -m pytest -q
bash -n install.sh deploy/install-vps.sh scripts/sandbox-e2e.sh scripts/update.sh scripts/update-from-github.sh
cd admin && npm ci && npx vite build
cd ../miniapp && npm install && npx vite build
cd ../cabinet && npm install && npx vite build
```

### License

**Project source license.** Your own commercial VPN shop, internal changes, and distribution of built customer apps to your customers are permitted free of charge. See [LICENSE](../../LICENSE) for the conditions and source redistribution limits.

- v20 Payment Platform: see V20_PAYMENT_PLATFORM_RU.md

## Changelog

### 20.0.7

См. [отчёт аудита](../../docs/ru/AUDIT_20_0_7.md) и [заметки релиза](../../.github/release-v20.0.7.md).

### 20.0.6

Ниже сохранена история релизов. Как пройти staging E2E — [PAYMENTS.md](../../docs/ru/PAYMENTS.md). How to pass staging E2E — [PAYMENTS.md](../../docs/en/PAYMENTS.md). Як пройти staging E2E — [PAYMENTS.md](../../docs/uk/PAYMENTS.md). Исторический маркер `FULL_E2E_PASS` больше не выдаётся текущим runner: см. раздел v20.0.8.
