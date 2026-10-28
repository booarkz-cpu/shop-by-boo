# Що нового у v28.41.0

Ще дві каси для карток і СБП: **AuraPay** і **Anore** (`backend/app/payments_extra.py`). Head міграцій магазину — `0081_subscription_proxy`, застосунки — 3.4.0.

- Каса стає в чергу кас і у вибір способу оплати, щойно задано її ключі в налаштуваннях без перезапуску або в `.env`:
  - AuraPay: `AURAPAY_SHOP_ID`, `AURAPAY_API_KEY`, `AURAPAY_SECRET_KEY`;
  - Anore: `ANORE_API_KEY`, `ANORE_SECRET_KEY`, `ANORE_SHOP_ID`.
- Сповіщення:
  - AuraPay — `https://<API_DOMAIN>/api/webhooks/aurapay`, підпис HMAC-SHA256 у `X-SIGNATURE`;
  - Anore — `https://<API_DOMAIN>/api/webhooks/anore`, підпис HMAC-SHA256 у `Anore-Signature`, `Anore-Event` має збігатися з подією в тілі.
- Підписка видається лише після повторної перевірки платежу в API каси.
- Реєстр налаштувань: 219 полів, з них 127 live.

Докладно: [billing_and_taxes](../modules/billing_and_taxes.md#aurapay-и-anore-v2841).
