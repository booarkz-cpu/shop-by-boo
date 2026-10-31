# Admin panel

Every section reads and changes real data. Each action checks the permission on the server — hiding a button in
the browser is not enough.

## Sections

| Section | What it does |
| --- | --- |
| Dashboard | customers, money, subscriptions, service state |
| Users | customer card: subscriptions, payments, devices, traffic, sessions |
| Subscriptions | all subscriptions, term, plan, status, extension and disable |
| Plans | create and edit plans, Remnawave Internal Squad, prices and duration |
| Devices | bound devices and limits |
| Payments | orders, statuses, re-reconciliation, refunds |
| Promo codes | discounts, limits, expiry |
| Finance | operations ledger, P&L, provider reconciliation |
| Analytics | revenue, conversion, cohorts, retention |
| Remnawave | panel users, synchronisation, node state |
| Reverse proxy | routes, TLS, Caddy state |
| Telegram | bot, banners, menu, broadcasts |
| Cabinet | cabinet and Mini App menu and sections |
| Support | tickets, replies, auto-replies, knowledge base |
| System state | health checks, workers, queues |
| Background jobs | schedules, last runs, errors |
| Logs | error log and administrator action log |
| Integrations | state of external services |
| Automation | rules and campaigns: event → action |
| GitHub | versions, releases, update check |
| Updates | current and available version, nightly update, history |
| Backups | copies, integrity check, restore |
| Settings | branding, themes, texts, languages |
| Security | administrators, roles, 2FA, passkeys, sessions |

## How access works

Roles: `admin`, `operator`, `support`, `viewer`. The permission is enforced by `require_permission(...)` on every
administrative route. A refund requires `payments.refund`, viewing a customer requires `users.read`, replying in
support requires `support.write`.

If a button does nothing, read the server response first: `403` means "no permission", not "broken interface".

## What the panel does on failure

* A section that fails to load shows the reason and a retry button — no data is changed;
* a render failure shows an error screen instead of a blank page;
* dangerous operations (refund, delete, disable subscription) require confirmation.

## Working with a customer

1. Open "Users", find the customer by email, Telegram or ID.
2. The card shows subscriptions, payments, devices, traffic per day and sessions.
3. Actions: extend, change plan, disable, refund, send a message.

Traffic per day comes from Remnawave statistics. If the panel does not serve them, the section shows an empty
chart instead of an error.

[← Back to home](Home.md)
