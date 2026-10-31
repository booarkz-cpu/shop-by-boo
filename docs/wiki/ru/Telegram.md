# Telegram

## Бот

1. Откройте [@BotFather](https://t.me/BotFather), выполните `/newbot`, придумайте имя и username.
2. Скопируйте токен в `.env`:

```env
BOT_TOKEN=123456789:AA...
BOT_USERNAME=your_bot
ADMIN_TELEGRAM_ID=ваш_telegram_id
```

3. Перезапустите бота:

```bash
docker compose restart bot
```

4. Откройте своего бота и отправьте `/start` — должно появиться меню.

**Проверка:** `docker compose logs -f bot` показывает входящие обновления. Если пусто — проверьте токен.

### Команды бота

`/start`, `/buy`, `/subscription`, `/promo`, `/account`, `/balance`, `/payments`, `/gifts`, `/referral`,
`/support`, `/devices`, `/faq`, `/rules`, `/privacy`, `/offer`.

Меню, баннеры и тексты редактируются в админ-панели — обновлять магазин для этого не нужно.

## Mini App

1. В [@BotFather](https://t.me/BotFather): `/mybots` → ваш бот → **Bot Settings** → **Menu Button** →
   укажите `https://app.ваш-домен.ru`.
2. В `.env`:

```env
MINI_APP_URL=https://app.ваш-домен.ru
```

3. Перезапустите сервис:

```bash
docker compose restart miniapp backend
```

### Как проверяется `initData`

Telegram передаёт Mini App подписанные данные. Магазин **на сервере** проверяет их: собирает строку из
отсортированных пар, считает HMAC-SHA256 с ключом, производным от `BOT_TOKEN`, и сравнивает с полем `hash`
через сравнение постоянного времени. Дополнительно проверяется, что `auth_date` не старше 10 минут.

Это значит: подделать вход нельзя, даже если клиент попытается отправить свои данные напрямую. Проверка
лежит в `backend/app/auth_api.py` и покрыта тестами.

## Уведомления

Магазин пишет клиенту при: оплате, продлении, истечении подписки, ответе поддержки, сбое и блокировке.

```env
REQUIRED_TELEGRAM_CHANNEL=      # обязательная подписка на канал, пусто — не требуется
NOTIFICATION_EXPIRY_DAYS=3      # за сколько дней предупреждать об истечении
```

## Если не работает

| Симптом | Проверка | Исправление |
| --- | --- | --- |
| Бот молчит | `docker compose logs bot` | проверить `BOT_TOKEN` |
| Webhook не доходит | `getWebhookInfo` у бота | HTTPS-домен, доступность извне |
| Mini App пустой | консоль браузера, `initData` | `MINI_APP_URL`, домен в настройках бота |
| `Invalid Telegram initData` | часы сервера | синхронизировать время (`timedatectl`) |
| Уведомления не приходят | блокировка бота клиентом | клиент должен снова нажать `/start` |

[← На главную](Home.md)
