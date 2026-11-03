# Telegram: функции бота и Mini App

Этап 13. Бот — `backend/app/bot.py`, `bot_workspace.py` (контейнер `bot`). Mini App — личный кабинет, собранный для Telegram (`cabinet/`, `NEXT_PUBLIC_SURFACE=miniapp`, контейнер `miniapp`). Бизнес-логика у бота, Mini App, кабинета и приложений общая: покупка, продление, промокоды, подарки и устройства проходят через одни и те же API backend. Бот показывает данные и открывает нужный раздел Mini App, второй логики у него нет.

Управление ботом — [TELEGRAM_GUIDE](TELEGRAM_GUIDE.md), кабинет — [USER_CABINET_GUIDE](USER_CABINET_GUIDE.md).

## 1. Вход в Mini App

1. Telegram открывает Mini App и передаёт `initData`.
2. Mini App отправляет его в `POST /api/auth/telegram`.
3. Backend проверяет подпись по документации Telegram: ключ — HMAC-SHA256(`WebAppData`, токен бота), подпись — HMAC-SHA256 отсортированных пар `ключ=значение` без `hash`, сравнение `hmac.compare_digest`. Отклоняются: `initData` старше 10 минут, отсутствие токена, отсутствие или неверный `user.id`.
4. Новый клиент проходит проверку регистрации (модерация, приглашения) и получает аккаунт.
5. Сессия создаётся так же, как в кабинете. Вход пишется в журнал (`auth.user.login`, метод `telegram`).

Токен бота читается из «Настроек без перезапуска»: после смены токена вход через новый бот работает без перезапуска backend.

## 2. Функции

| Функция | Бот | Mini App | Где логика |
| --- | --- | --- | --- |
| Старт, регистрация | `/start`: аккаунт по Telegram ID, реферальная ссылка `ref_…`, источник рекламы, обязательные каналы, закреплённое сообщение | Вход по `initData` | `bot.start`, `auth_api.telegram_auth` |
| Профиль | `/account`: кошелёк, реферальный баланс, подписка | «Профиль» | `bot_workspace`, кабинет |
| Тарифы Lucy | `/buy`: список с ценами, кнопка в магазин | «Тарифы» — Lucy Mini, Max, Ultra | `lucy_plans` |
| Покупка и продление | Кнопка открывает Mini App; Telegram Stars прямо в чате | Оплата, продление, автопродление | `shop`, `telegram_stars` |
| Промокоды | `/promo КОД` — ссылка в магазин с кодом; код проверяется на сервере ещё раз | Ввод промокода | `shop` |
| Подарки | Ссылка `GIFT_…` в `/start`, `/gifts` | «Подарки» | `gift_orders` |
| Рефералы | `/referral`, `/contest` — таблица конкурса | «Рефералы» | `referrals`, `referral_contests` |
| Пробный период | — | Только на Lucy Mini и не дольше неё | `lucy_plans.trial_plan` |
| Конфигурации | `/subscription` — ссылка подписки, `/keys` — ключи по серверам | «Подключение», QR-код | `sub_proxy`, Remnawave |
| Устройства | `/devices` — открыть раздел, `/stats` — число устройств | «Устройства» — лимит HWID, удаление | `cabinet_security` |
| Уведомления | `/status` — состояние сервиса и подписка на сбои; напоминания об окончании | «Уведомления» | `notifications_status_api`, `status_page` |
| Поддержка | `/support`, оценки CSAT и NPS кнопками | «Поддержка» | `support_threads`, `feedback` |
| История | `/payments` — последние платежи | «Платежи», «История» | `bot_workspace`, кабинет |
| Заморозка, фильтр, уровень | `/freeze`, `/filter`, `/level` | Те же разделы | `subscription_freeze`, `dns_filter`, `loyalty` |
| Вход в приложение | `/app` — одноразовая ссылка | — | `app_login` |
| Документы | `/info`, `/faq`, `/rules`, `/privacy`, `/offer` | «Документы» | `info_pages` |

## 3. Языки

- **Бот** отвечает на языке Telegram клиента: украинский, английский, остальным русский (или язык магазина по умолчанию). Все тексты бота на трёх языках — в реестре `bot_texts.py`. Владелец меняет их в «Telegram-бот → Тексты бота»: подстановки и HTML-теги проверяются, бот берёт новые тексты в течение минуты. Тест `tests/test_bot_texts.py` не пропускает русские строки в обработчиках бота мимо реестра.
- **Mini App** — переводы кабинета (`cabinet/src/i18n.tsx`) на ru, en и uk.

## 4. Проверено

| Что | Тест | Статус |
| --- | --- | --- |
| Подпись и срок `initData`, отказ без токена | `tests/test_behaviour_auth.py` | PASS |
| Пробный период только на Lucy Mini | `tests/test_cabinet_stage8.py::test_lucy_tariffs_and_the_trial_on_lucy_mini` | PASS |
| Тексты бота на трёх языках, правка из админки, ответ на языке клиента | `tests/test_bot_texts.py` | PASS |
| Связь бота с Telegram, меню команд | `tests/test_telegram_bot.py`, `tests/live/test_telegram_live.py` | PASS (mock); живой — задание CI `telegram` |
| Покупка через Mini App с настоящей кассой | нужны ключи sandbox (этап 14) | BLOCKED_SECRETS |
