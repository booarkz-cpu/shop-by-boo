# What is new in v28.43.0

- Two more gateways for cards and SBP, **Cashera** and **ParityPay**, in `backend/app/payments_extra.py`. They take one-time payments only. The shop migration head stays at `0081_subscription_proxy`, and the apps stay at 3.4.0.
- Keys go in runtime settings or `.env`:
  - Cashera: `CASHERA_API_KEY`, `CASHERA_API_SECRET`.
  - ParityPay: `PARITYPAY_SHOP_ID`, `PARITYPAY_SECRET_KEY`, `PARITYPAY_CALLBACK_SECRET`.
- Notifications:
  - `https://<API_DOMAIN>/api/webhooks/cashera` checks the static `X-Api-Key` and `X-Secret` headers in constant time.
  - `https://<API_DOMAIN>/api/webhooks/paritypay` checks the HMAC-SHA256 `X-SIGNATURE` header.
- The subscription is delivered only after the payment is read again from the gateway API.
- Fix: AuraPay and ParityPay signatures use the values exactly as sent. An integer amount such as `1200` no longer breaks the signature.
- Settings registry: 224 fields, 132 of them live.
