# VPN Shop v19 — Marketplace & Remnawave Commerce

v19 превращает Corgi в коммерческий слой поверх Remnawave.

## Архитектура

`Customer -> Corgi Shop -> Payment -> Entitlement -> Remnawave Adapter -> User/Squad/Subscription`

Remnawave остаётся VPN control plane: пользователи получают доступ через Internal Squads, Hosts и subscription URL. Corgi отвечает за магазин, billing, entitlements, reseller/white-label и пользовательский UX.

## Marketplace

- Reseller accounts with server-side API keys.
- Plan allow-list per reseller.
- Commission percentage and gross-paid/commission reporting.
- White-label branding payload.
- Reseller catalog endpoint.
- Reseller stats endpoint.
- API key rotation.
- Payment attribution through `payments.reseller_id`.

## Existing commerce retained

- Plans and promotions.
- Promo codes.
- Gift codes.
- Referral ledger/rewards.
- Subscription billing lifecycle.
- Remnawave fulfillment and reconciliation.
- Subscription Gateway.

## Telegram

- `/start` opens the shop.
- `/buy` shows current plans and opens Mini App.
- `/subscription` returns the user's active subscription URL when available.
- `/promo CODE` deep-links a promo code into the shop.
- `/ops` remains owner-only.
- RU/EN/UK language selection is based on Telegram language code.

## Admin endpoints

- `GET /api/admin/marketplace/resellers`
- `POST /api/admin/marketplace/resellers`
- `PATCH /api/admin/marketplace/resellers/{id}`
- `POST /api/admin/marketplace/resellers/{id}/rotate-key`

## Reseller endpoints

Use `Authorization: Bearer <server-side reseller API key>`.

- `GET /api/reseller/catalog`
- `GET /api/reseller/stats`
- `GET /api/reseller/branding`

A reseller key is only returned once at creation/rotation and only its hash is persisted.

## Remnawave

The integration remains server-side. Corgi clients never receive the Remnawave API token. Remnawave 3.x numeric user IDs are used by the adapter.
