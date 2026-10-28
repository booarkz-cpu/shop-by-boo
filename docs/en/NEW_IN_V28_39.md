# What is new in v28.39.0

Two more gateways for cards and SBP: **Pal24 (PayPalych)** and **Mulen Pay** (`backend/app/payments_extra.py`). Shop migration head stays `0081_subscription_proxy`; apps stay 3.4.0.

- Each gateway joins the gateway queue and the payment method routing once its keys are set in runtime settings (secrets stored encrypted) or `.env`: `PAL24_SHOP_ID`, `PAL24_API_TOKEN`, `PAL24_SIGNATURE_TOKEN`; `MULENPAY_SHOP_ID`, `MULENPAY_API_KEY`, `MULENPAY_SECRET_KEY`.
- Notifications: `https://<API_DOMAIN>/api/webhooks/pal24` (Result URL, MD5 `SignatureValue`) and `https://<API_DOMAIN>/api/webhooks/mulenpay` (SHA-1 `sign`).
- The subscription is delivered only after the payment is read again from the gateway API (status, order and amount). No recurring charges or API refunds.
- Settings registry: 207 fields, 115 live.

Details: [billing_and_taxes](../modules/billing_and_taxes.md#pal24-и-mulen-pay-v2839).
