# VPN Shop by Corgi

[![CI](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/ci.yml)
[![Docker](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/docker.yml/badge.svg?branch=main)](https://github.com/booarkz-cpu/shop-by-boo/actions/workflows/docker.yml)
[![Release](https://img.shields.io/github/v/release/booarkz-cpu/shop-by-boo?display_name=tag)](https://github.com/booarkz-cpu/shop-by-boo/releases/latest)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178C6)
![License](https://img.shields.io/badge/license-2.8-FF8A1F)

Актуальная схема каталогов, функциональных границ и визуальной системы собрана в [карте проекта](docs/PROJECT_MAP_RU.md). Полное дерево каталогов и правила границ модулей: [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md).

Единый магазин VPN-подписок: админ-панель, веб кабинет пользователя, Telegram-бот и Mini App, приложения Android и iOS. Админка, кабинет и Mini App построены на Next.js и используют единую тёмную систему Remna Dark (светлая тема сохранена) с контекстными подсказками у всех редактируемых полей.

**v28.8.0 — текущий стабильный тег дистрибутива.** Он содержит runtime/API `21.5.1`, head магазина `0067_plugin_runtime` и Support Pro `0007` / 3.7. Разделение тега и версии API намеренное: оператор устанавливает `v28.8.0`, а health/API возвращает `21.5.1`. Полная фактическая матрица и критерии закрытия опубликованы отдельно: [карта покрытия](docs/ru/WORKSPACE_COVERAGE.md), [критерии завершения](docs/ru/MATRIX_COMPLETION_21_5_1.md).

В alpha.7 добавлен [вход администратора по passkey](docs/ru/ADMIN_PASSKEYS.md), [операционный dashboard и alerts](docs/ru/OPERATIONS_MONITORING.md). Исправлена привязка публикации мобильных пакетов к актуальному тегу; подписи владельца по-прежнему нужны.

Текущий стабильный выпуск: [v28.8.0](https://github.com/booarkz-cpu/shop-by-boo/releases/tag/v28.8.0). Точный commit и результаты CI указаны на странице релиза. Production-платежи остаются закрытыми: application E2E v2 не завершён. Подписанные APK/IPA требуют ключей владельца. Изменения рабочего пространства описаны в [CHANGELOG.md](CHANGELOG.md). Актуальные инструкции: [DOCUMENTATION.md](DOCUMENTATION.md), [INSTALL_STEPS.md](INSTALL_STEPS.md), [FUNCTIONS.md](FUNCTIONS.md), [SECURITY.md](SECURITY.md). Исторические редакции не являются текущим руководством.

Сведение поддержки и перенос старой истории: [отдельная инструкция](docs/ru/WORKSPACE_SUPPORT_BRIDGE.md).

## Обновление v28.8.0

Админ-панель, личный кабинет и Telegram Mini App переведены на **Next.js** (static export, прежние nginx-образы и Caddy) и получили единый дизайн **Remna Dark**: сворачиваемый sidebar и выдвижное меню на телефонах, дашборд с плашкой состояния, плитками метрик 2×2/4×1, поиском и сегментированным фильтром серверов, skeleton-загрузку. Mini App использует Telegram WebApp SDK: тема и safe area из клиента, haptic feedback, нативные BackButton/MainButton, подтверждение закрытия во время оплаты. Кабинет показывает статус, остаток трафика и срок подписки, QR и копирование ссылки, пошаговую инструкцию, карточки тарифов, профиль и историю платежей. Новый [перенос истории](docs/ru/HISTORY_IMPORT_CURRENT.md) подписок и платежей сверяет контрольные итоги, не дублирует строки при повторе и откатывается журналом. Production CSP (`script-src 'self'`) соблюдается: inline-скрипты Next.js выносятся в файлы при сборке.

Настройки без перезапуска из v28.3.0 (96 live-параметров, зашифрованные секреты, staged apply и откат) сохранены.

Обновление существующей установки с тегов `v26`–`v28.7.0` выполняется проверяющим скриптом: [инструкция обновления дистрибутива](docs/ru/DISTRIBUTION_UPGRADE_CURRENT.md). Версия API остаётся `21.5.1`; перед применением новой миграции `0067_plugin_runtime` обязателен согласованный backup.

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

## Начать работу

Для проверки без настоящих касс, Telegram и Remnawave нужны Docker Engine, Compose и Python 3:

```bash
git clone --branch v28.8.0 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
bash scripts/test-up.sh
```

Скрипт создаст `.env.test`, покажет параметры входа и адреса тестовых интерфейсов. Пароли не публикуйте. [Подробная проверка](docs/ru/TESTING.md).

Установка на VDS через SSH или Termius:

```bash
git clone --branch v28.8.0 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
sudo bash deploy/install-vps.sh
```

Сначала прочитайте [установку на VDS](docs/ru/DEPLOYMENT_CURRENT.md). Нужны DNS-записи для выбранных доменов, открытые 80/443, токен Telegram и доступ к Remnawave. Установщик запрашивает значения интерактивно. Перед эксплуатацией проверьте выпуск на отдельном стенде; стабильный канал не означает допуск production-платежей. Автообновление существующего production-сервера остаётся на стабильных выпусках.

## Руководства по каждой функции

| Задача | Руководство |
| --- | --- |
| Создать конкурс или колесо призов | [Правила, бюджет, розыгрыш и приватность](docs/ru/WORKSPACE_GIVEAWAYS.md) |
| Прочитать результаты текущего выпуска | [Отчёт v28.8.0](docs/ru/RELEASE_V28_8_0.md) |
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

## Выпуск v28.8.0

Релиз v28.8.0 добавляет среду плагинов (миграция `0067_plugin_runtime`): плагин — внешний HTTPS-сервис с подписанным пакетом-манифестом; администратор доверяет ключу издателя и подтверждает права, плагин получает подписанные события и API только с разрешёнными правами, версии обновляются и откатываются без перезапуска, при сбоях плагин останавливается автоматически — строка матрицы «Plugin runtime/hotload» закрыта ([регламент](docs/ru/PLUGINS_CURRENT.md)). Релиз v28.7.0 добавил email-канал поддержки (Support Pro 3.7, миграция `0007`): письма клиентов по IMAP становятся обращениями без дублей, ответы операторов уходят письмом с сохранением цепочки, автоответы и возвраты не открывают обращений, есть удаление данных клиента и срок хранения — строка матрицы «Внешние helpdesk/email каналы» закрыта для email ([регламент](docs/ru/SUPPORT_EMAIL_CHANNEL_CURRENT.md)). Релиз v28.6.0 добавил виджет подписки на рабочий стол Android и несколько профилей магазинов в админ-приложениях Android и iOS — строка матрицы «Native push/widget/multiprofile» закрыта ([регламент](docs/ru/WIDGET_AND_PROFILES_CURRENT.md)). Релиз v28.5.0 добавил нативные push-уведомления в приложения Android (FCM) и iOS (APNs): включение по согласию клиента, токен привязан к сессии входа и отзывается при выходе, потерянные токены отключаются автоматически, в админке — состояние провайдеров и доставки ([регламент](docs/ru/PUSH_NOTIFICATIONS_CURRENT.md)). Релиз v28.4.0 перевёл админ-панель, кабинет и Mini App на Next.js (static export, прежние nginx-образы) в дизайне Remna Dark и закрыл строку матрицы «Исторический импорт VPN/платежей»: версионированный адаптер, preview без записи, сверка с контрольными итогами, повтор без дублей и журнал отката ([регламент](docs/ru/HISTORY_IMPORT_CURRENT.md)). Runtime/API остаётся `21.5.1`, схема магазина обновляется до `0067_plugin_runtime`. Релиз v28.3.0 закрыл «70+ настроек с hot-reload и шифрованием». Внешние проверки и production gate остаются открытыми. [Заметки выпуска v28.8.0](docs/ru/RELEASE_V28_8_0.md).

Импорт users.db и массовые операции доступны роли admin в «Клиенты → Импорт и массовые операции». Порядок mapping, preview, применения и границы переноса: [инструкция](docs/ru/CUSTOMER_OPERATIONS_CURRENT.md).

В v21.3.0 добавлены [редакторы новостей, лендингов и юридических страниц](docs/ru/CONTENT_PUBLISHING_CURRENT.md), [промогруппы и персональные офферы](docs/ru/PERSONAL_OFFERS_CURRENT.md), пять previewed массовых действий включая ограничение/восстановление доступа в магазин.

В v21.4.0 добавлены [вложенные меню Telegram и Mini App](docs/ru/MENU_TREE_CURRENT.md): папки до четырёх уровней, стили, custom emoji, безопасные миниатюры и предпросмотр.

В v21.5.0 исправлена [синхронизация истории Support Pro после merge/split](docs/ru/SUPPORT_REMOTE_HISTORY_CURRENT.md): сообщения и файлы сохраняют идентичность, исходная очередь блокируется, внутренние заметки остаются на месте.
