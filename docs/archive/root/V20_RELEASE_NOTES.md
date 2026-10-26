# VPN Shop v20 — Payment Platform R0–R3

## R0 — Payment foundation
- Unified payment provider capability registry.
- Provider health, priorities and circuit breakers extended to the new platform.
- Durable idempotent checkout remains the source of truth before external calls.
- Stripe Checkout, PayPal Orders/Capture and generic crypto gateway adapters.
- Existing YooKassa, Platega and RollyPay integrations retained.

## R1 — Recurring + mobile stores
- Existing YooKassa recurring charging retained in the auto-renew engine.
- Auto-renew status now advertises YooKassa/Stripe/PayPal capability surface.
- Apple StoreKit 2 transaction verification + App Store Server API lookup.
- Google Play subscription verification + server-side purchase validation.
- Mobile purchase tokens are persisted as external transaction identifiers, never as card data.

## R2 — Finance, tax, risk and operations
- Tax profiles, VAT ID and reverse-charge flags.
- PDF invoices with invoice numbering and VAT breakdown.
- Pre-checkout risk score and persisted risk assessment.
- Chargeback lifecycle and evidence storage.
- Provider/day metrics: attempts, success, failure, refunds, gross, fees, net.
- Provider webhooks trigger fulfillment only after verification.

## R3 — Commerce expansion
- Gift cards with hashed codes and wallet redemption.
- Corporate accounts with VAT/payment terms/credit limit foundation.
- Dynamic pricing experiment registry.
- Admin analytics/capabilities endpoints.
- Crypto and SEPA capability contracts without pretending an external merchant/bank account is connected.

## Production boundary
The code implements the adapters and server workflows. Live production activation still requires the corresponding merchant credentials, App Store/Play Console credentials, webhook registrations and successful staging E2E. External credentials were not available in this build environment, so no live transaction was claimed or fabricated.
