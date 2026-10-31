# Telegram

## The bot

1. Open [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name and username.
2. Copy the token into `.env`:

```env
BOT_TOKEN=123456789:AA...
BOT_USERNAME=your_bot
ADMIN_TELEGRAM_ID=your_telegram_id
```

3. Restart the bot:

```bash
docker compose restart bot
```

4. Open your bot and send `/start` — the menu must appear.

**Check:** `docker compose logs -f bot` shows incoming updates. If it stays empty, the token is wrong.

### Bot commands

`/start`, `/buy`, `/subscription`, `/promo`, `/account`, `/balance`, `/payments`, `/gifts`, `/referral`,
`/support`, `/devices`, `/faq`, `/rules`, `/privacy`, `/offer`.

The menu, banners and texts are edited in the admin panel — no redeploy needed.

## Mini App

1. In [@BotFather](https://t.me/BotFather): `/mybots` → your bot → **Bot Settings** → **Menu Button** → set
   `https://app.your-domain.com`.
2. In `.env`:

```env
MINI_APP_URL=https://app.your-domain.com
```

3. Restart the service:

```bash
docker compose restart miniapp backend
```

### How `initData` is verified

Telegram hands the Mini App signed data. The shop verifies it **on the server**: it builds a string from the
sorted pairs, computes HMAC-SHA256 with a key derived from `BOT_TOKEN` and compares it to the `hash` field in
constant time. It also rejects `auth_date` older than 10 minutes.

So a forged sign-in cannot pass, even if a client sends its own data directly. The check lives in
`backend/app/auth_api.py` and is covered by tests.

## Notifications

The shop messages a customer on payment, renewal, expiry, a support reply, a failure and a block.

```env
REQUIRED_TELEGRAM_CHANNEL=      # mandatory channel subscription, empty means not required
NOTIFICATION_EXPIRY_DAYS=3      # how many days before expiry to warn
```

## When it does not work

| Symptom | Check | Fix |
| --- | --- | --- |
| The bot is silent | `docker compose logs bot` | verify `BOT_TOKEN` |
| The webhook never arrives | `getWebhookInfo` on the bot | HTTPS domain, external reachability |
| Mini App is blank | browser console, `initData` | `MINI_APP_URL`, domain in bot settings |
| `Invalid Telegram initData` | server clock | sync time (`timedatectl`) |
| No notifications | the customer blocked the bot | the customer must send `/start` again |

[← Back to home](Home.md)
