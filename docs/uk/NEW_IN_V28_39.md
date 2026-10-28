# Що нового у v28.39.0

Ще дві каси для карток і СБП: **Pal24 (PayPalych)** і **Mulen Pay** (`backend/app/payments_extra.py`). Head міграцій магазину — `0081_subscription_proxy`, застосунки — 3.4.0.

- Каса стає в чергу кас і у вибір способу оплати, щойно задано ключі в налаштуваннях без перезапуску (секрети зберігаються зашифровано) або в `.env`: `PAL24_SHOP_ID`, `PAL24_API_TOKEN`, `PAL24_SIGNATURE_TOKEN`; `MULENPAY_SHOP_ID`, `MULENPAY_API_KEY`, `MULENPAY_SECRET_KEY`.
- Сповіщення: `https://<API_DOMAIN>/api/webhooks/pal24` (Result URL, підпис MD5 `SignatureValue`) і `https://<API_DOMAIN>/api/webhooks/mulenpay` (підпис SHA-1 `sign`).
- Підписка видається лише після повторної перевірки платежу в API каси (статус, замовлення і сума). Автоплатежів і повернень через API немає.
- Реєстр налаштувань: 207 полів, 115 live.

Докладно: [billing_and_taxes](../modules/billing_and_taxes.md#pal24-и-mulen-pay-v2839).
