# Що нового у v28.43.0

- Ще дві каси для карток і СБП — **Cashera** і **ParityPay** (`backend/app/payments_extra.py`). Обидві приймають лише разові платежі.
- Ключі задаються в налаштуваннях без перезапуску або в `.env`:
  - Cashera: `CASHERA_API_KEY`, `CASHERA_API_SECRET`;
  - ParityPay: `PARITYPAY_SHOP_ID`, `PARITYPAY_SECRET_KEY`, `PARITYPAY_CALLBACK_SECRET`.
- Сповіщення:
  - `https://<API_DOMAIN>/api/webhooks/cashera` — справжність перевіряється за заголовками `X-Api-Key` і `X-Secret`;
  - `https://<API_DOMAIN>/api/webhooks/paritypay` — за підписом HMAC-SHA256 у заголовку `X-SIGNATURE`.
- Підписка видається лише після повторної перевірки платежу в API каси.
- Виправлення: підписи AuraPay і ParityPay рахуються за значеннями саме в тому вигляді, у якому їх надіслала каса.
- Реєстр налаштувань: 224 поля, з них 132 live.
