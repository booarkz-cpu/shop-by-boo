# Що нового у v28.40.0

Ще дві каси для карток і СБП: **WATA** і **Antilopay**. Код — у `backend/app/payments_extra.py`. Head міграцій магазину — `0081_subscription_proxy`, застосунки — 3.4.0.

- **Ключі.** Каса стає в чергу кас і у вибір способу оплати, щойно задано її ключі в налаштуваннях без перезапуску або в `.env`.
  - WATA: `WATA_ACCESS_TOKEN`.
  - Antilopay: `ANTILOPAY_PROJECT_ID`, `ANTILOPAY_SECRET_ID`, `ANTILOPAY_PRIVATE_KEY`, `ANTILOPAY_PUBLIC_KEY`, `ANTILOPAY_CUSTOMER_EMAIL`.
  - RSA-ключі приймаються як base64 (DER) або PEM.
- **Сповіщення.**
  - `https://<API_DOMAIN>/api/webhooks/wata`: підпис `X-Signature` RSA SHA-512. Відкритий ключ магазин бере з `/public-key` і кешує на годину.
  - `https://<API_DOMAIN>/api/webhooks/antilopay`: підпис `X-Apay-Callback` RSA SHA-256.
- **Запити до Antilopay** підписані закритим ключем магазину.
- **Видача.** Підписка видається лише після повторної перевірки платежу в API каси.
- **Реєстр налаштувань:** 213 полів, з них 121 live.

Докладно: [billing_and_taxes](../modules/billing_and_taxes.md#wata-и-antilopay-v2840).
