# What is new in v28.40.0

Two more gateways for cards and SBP, **WATA** and **Antilopay**, in `backend/app/payments_extra.py`. The shop migration head stays at `0081_subscription_proxy`. The apps stay at 3.4.0.

- **Keys.** A gateway joins the gateway queue and the payment method routing once its keys are set in runtime settings or in `.env`.
  - WATA: `WATA_ACCESS_TOKEN`.
  - Antilopay: `ANTILOPAY_PROJECT_ID`, `ANTILOPAY_SECRET_ID`, `ANTILOPAY_PRIVATE_KEY`, `ANTILOPAY_PUBLIC_KEY`, `ANTILOPAY_CUSTOMER_EMAIL`.
  - RSA keys can be given as base64 DER or as PEM.
- **Notifications.**
  - `https://<API_DOMAIN>/api/webhooks/wata`: `X-Signature` is RSA SHA-512. The public key comes from WATA's `/public-key` and is cached for an hour.
  - `https://<API_DOMAIN>/api/webhooks/antilopay`: `X-Apay-Callback` is RSA SHA-256. Requests to Antilopay are signed with the shop's private key.
- **Delivery.** The subscription is delivered only after the payment is read again from the gateway API. Recurring charges and refunds through the API are not supported.
- **Settings registry.** 213 fields, 121 of them live.

Details: [billing_and_taxes](../modules/billing_and_taxes.md#wata-и-antilopay-v2840).
