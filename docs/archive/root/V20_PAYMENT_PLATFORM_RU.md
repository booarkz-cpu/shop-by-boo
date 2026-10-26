# VPN Shop v20 — Payment Platform

## Реализовано
- Stripe Checkout/PaymentIntent-compatible server flow, webhook verification, refunds and provider metrics.
- PayPal Orders/Capture, webhook verification and refunds where a capture is available.
- YooKassa/Platega/RollyPay сохранены.
- Crypto gateway adapter через внешний merchant API.
- Apple StoreKit 2 transaction verification foundation + App Store Server API lookup.
- Google Play purchase/subscription verification через Google Play Developer API.
- Unified provider router, health/circuit-breaker and failover-safe durable intents.
- Auto-renew engine foundation with retry/grace state; existing YooKassa recurring flow retained.
- Tax profile, VAT/reverse-charge flags and PDF invoices.
- Risk scoring before checkout and persistent risk assessments.
- Chargeback lifecycle and admin review API.
- Provider/day financial metrics: attempts, success, failures, refunds, gross/fees/net.
- Gift cards with hashed codes and wallet redemption.
- Corporate accounts / invoice terms foundation.
- Pricing experiments API for dynamic pricing rules.

## Безопасность
- Card data is never stored by Corgi.
- Stripe/PayPal/Apple/Google credentials stay server-side.
- Webhooks are verified before fulfillment.
- Mobile purchases are granted only after server-side verification.
- Payment intents are durable before external calls and remain idempotent.

## Production activation
Live external E2E still requires merchant credentials, webhook URLs and sandbox/production verification. The code does not claim those external accounts are connected merely because adapters exist.
