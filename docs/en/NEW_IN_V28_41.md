# What is new in v28.41.0

Two more gateways for cards and SBP, **AuraPay** and **Anore**, in `backend/app/payments_extra.py`. The shop migration head stays at `0081_subscription_proxy`. The apps stay at 3.4.0.

- **Keys.** A gateway joins the gateway queue and the payment method routing once its keys are set in runtime settings or in `.env`:
  - `AURAPAY_SHOP_ID`, `AURAPAY_API_KEY`, `AURAPAY_SECRET_KEY`;
  - `ANORE_API_KEY`, `ANORE_SECRET_KEY`, `ANORE_SHOP_ID`.
- **Notifications.**
  - `https://<API_DOMAIN>/api/webhooks/aurapay`. `X-SIGNATURE` is an HMAC-SHA256 over the field values, taken in alphabetical key order.
  - `https://<API_DOMAIN>/api/webhooks/anore`. `Anore-Signature` is an HMAC-SHA256 over the body, and `Anore-Event` must match the body's `event`.
- **Delivery.** The subscription is delivered only after the payment is read again from the gateway API. The gateways have no recurring charges and no refunds through the API.
- **Settings registry.** 219 fields, of which 127 are live.

Details: [billing_and_taxes](../modules/billing_and_taxes.md#aurapay-и-anore-v2841).
