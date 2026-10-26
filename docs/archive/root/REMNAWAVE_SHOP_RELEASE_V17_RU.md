# VPN Shop v17 — Remnawave Shop

## Продажи подписок из Corgi через Remnawave

Corgi теперь оформляет коммерческий заказ и fulfillment, а Remnawave остаётся VPN control plane.

- Corgi: catalog, checkout, billing, entitlement, identity, apps.
- Remnawave: users, internal squads, nodes, hosts and subscription generation.
- API token: server-side only.
- Panel 3.x: numeric `userId` is used by the integration.

### Admin endpoints

- `GET /api/admin/remnawave/shop` — status and plan mappings.
- `POST /api/admin/remnawave/shop/test` — connection/API smoke test.
- `POST /api/admin/remnawave/shop/plan-mapping/validate` — verifies that enabled Corgi plans have Remnawave profile/squad mappings.

### User endpoints

- `GET /api/me/remnawave/subscription` — current entitlement and subscription URL.
- `POST /api/me/remnawave/subscription/refresh` — refreshes expiry and subscription URL from Remnawave.

### Payment flow

`checkout → provider confirmation → idempotent fulfillment → create/extend Remnawave user → apply traffic/profile → fetch subscription URL → Corgi entitlement`

A temporary Remnawave outage does not cause a second charge: fulfillment is queued/retried using the existing payment locks and idempotency model.
