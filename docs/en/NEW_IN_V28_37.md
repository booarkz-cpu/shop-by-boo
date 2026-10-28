# What is new in v28.37.0

Short operator notes for the modules added in v28.37.0. The detailed (Russian) pages are linked in each section.
Shop migration head: `0080_reconciliation` (new tables only). No new `.env` keys: every module is switched on in the
admin panel and is off by default. Apps: 3.3.0 (build 3300).

## Reconciliation with the comparison snapshots
Bedolaga Telegram Bot, Bedolaga Cabinet, Remnawave Admin and StepBot were read again at the coverage-map snapshots
and at their current commits. Missing features were ported as our own implementation (no code copied). Not ported,
with reasons: about 20 extra payment gateways, Apple In-App Purchase, a black list downloaded from a third-party
repository. Details: [SNAPSHOT_RECONCILIATION](../ru/SNAPSHOT_RECONCILIATION.md).

## Moderation and access
Black list (Telegram IDs, e-mails, domains), disposable e-mail ban, invite-only registration (`start=inv_…`,
`?invite=`), cleanup of customers who blocked the bot, bulk ban. Several required channels with a scope (all / trial /
purchase). Panel guard: maintenance switches on by itself when Remnawave stops answering and off when it is back.
System error log. Customer activity timeline. Details: [moderation](../modules/moderation.md).

## Sales
Smart cart (not enough on the balance → top up → bought by itself), guest purchase by e-mail, daily plans billed from
the wallet, grace access after the end of a subscription, traffic reset on payment, gift code batches with CSV,
«My stats» and one-click offers, payment method choice (SBP, card, crypto) routed to the gateways that accept it.
Details: [sales flows](../modules/sales_flows.md).

## Growth
Referral contests with a leaderboard (`/contest`), ad network postbacks and Yandex Metrika offline conversions, a
message pinned for every customer, churn forecast with a retention promo code, connection quality per carrier with a
recommended server, support auto-replies from the knowledge base, e-mail templates, 9 Mini App themes.
Details: [growth tools](../modules/growth_tools.md).

## Money
P&L with gateway fees and infrastructure costs per node; reseller wholesale orders by API (`POST /api/reseller/orders`).
Details: [P&L](../modules/pnl.md).

## Operations
A live Remnawave contract check against the newest panel in CI (fixed node restart, renewal by panel `id`, host bulk
actions). The standby server now also replicates Support Pro and media files and runs a weekly promotion drill on a
copy. Autoscaling takes node CPU from the node agents. k6 load tests and the OWASP ZAP baseline run in a separate
workflow that never blocks a release.

## Surfaces
Web admin: 18 new blocks. Mobile admins: generic module cards with actions (`GET /api/admin/mobile/panels`). Bot and
Mini App: new banners «contest», «stats», «channels», «guest».
