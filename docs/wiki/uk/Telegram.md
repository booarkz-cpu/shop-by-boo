# Telegram

## Бот

1. Відкрийте [@BotFather](https://t.me/BotFather), виконайте `/newbot`, придумайте ім'я та username.
2. Скопіюйте токен у `.env`:

```env
BOT_TOKEN=123456789:AA...
BOT_USERNAME=your_bot
ADMIN_TELEGRAM_ID=ваш_telegram_id
```

3. Перезапустіть бота:

```bash
docker compose restart bot
```

4. Відкрийте свого бота й надішліть `/start` — має з'явитися меню.

**Перевірка:** `docker compose logs -f bot` показує вхідні оновлення. Якщо порожньо — перевірте токен.

### Команди бота

`/start`, `/buy`, `/subscription`, `/promo`, `/account`, `/balance`, `/payments`, `/gifts`, `/referral`,
`/support`, `/devices`, `/faq`, `/rules`, `/privacy`, `/offer`.

Меню, банери й тексти редагуються в адмін-панелі — оновлювати магазин для цього не потрібно.

## Mini App

1. У [@BotFather](https://t.me/BotFather): `/mybots` → ваш бот → **Bot Settings** → **Menu Button** →
   вкажіть `https://app.ваш-домен.com`.
2. У `.env`:

```env
MINI_APP_URL=https://app.ваш-домен.com
```

3. Перезапустіть сервіс:

```bash
docker compose restart miniapp backend
```

### Як перевіряється `initData`

Telegram передає Mini App підписані дані. Магазин перевіряє їх **на сервері**: збирає рядок із відсортованих
пар, рахує HMAC-SHA256 із ключем, похідним від `BOT_TOKEN`, і порівнює з полем `hash` у постійному часі.
Додатково відхиляється `auth_date`, старший за 10 хвилин.

Отже, підробити вхід неможливо, навіть якщо клієнт надішле свої дані напряму. Перевірка лежить у
`backend/app/auth_api.py` і покрита тестами.

## Сповіщення

Магазин пише клієнту при: оплаті, продовженні, закінченні підписки, відповіді підтримки, збої та блокуванні.

```env
REQUIRED_TELEGRAM_CHANNEL=      # обов'язкова підписка на канал, порожньо — не потрібна
NOTIFICATION_EXPIRY_DAYS=3      # за скільки днів попереджати про закінчення
```

## Якщо не працює

| Симптом | Перевірка | Виправлення |
| --- | --- | --- |
| Бот мовчить | `docker compose logs bot` | перевірити `BOT_TOKEN` |
| Webhook не доходить | `getWebhookInfo` у бота | HTTPS-домен, доступність ззовні |
| Mini App порожній | консоль браузера, `initData` | `MINI_APP_URL`, домен у налаштуваннях бота |
| `Invalid Telegram initData` | годинник сервера | синхронізувати час (`timedatectl`) |
| Сповіщення не приходять | клієнт заблокував бота | клієнт має знову натиснути `/start` |

[← На головну](Home.md)
