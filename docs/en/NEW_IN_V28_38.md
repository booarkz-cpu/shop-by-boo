# What is new in v28.38.0

The functions of [remnawave-subscription-middleware](https://github.com/Mrvibecodic/remnawave-subscription-middleware), implemented inside the shop (the project has no licence file, so no code was copied). Shop migration head: `0081_subscription_proxy` (new tables only). Apps: 3.4.0 (build 3400). Details: [subscription_proxy](../modules/subscription_proxy.md), comparison: [MIDDLEWARE_RECONCILIATION](../ru/MIDDLEWARE_RECONCILIATION.md).

## Subscription proxy
Customers update the subscription through your own domain (`SUB_PROXY_DOMAINS`, or `https://<API_DOMAIN>/sub/<shortUuid>`); the shop fetches it from the panel's internal address. The panel link keeps working.
The cabinet, Mini App, bot, apps and resellers show the mirror link. The proxy adds:
- device block by HWID with a stub, and HWID from the User-Agent;
- per-app header rules (non-Latin text goes as `base64:`);
- extra keys per Internal Squad and a merged second subscription — only for active subscriptions and URI lists;
- a neutral page for scanners;
- a request log (14 days) and a client version catalogue that marks outdated apps.

## Webhooks and the change journal
Panel webhooks are forwarded to several receivers, each re-signed with its own secret. «Who changed the user» journals field changes as «shop» or «external» (CSV export can anonymise). The dashboard shows a subscription events feed, and «Panel requests» counts the shop's API calls by source and path.

## Customers and plans
- Term from the first connection (`user.first_connected`).
- Grace in a limited squad.
- Sessions and anomalies by IP, provider and country (`/api/connections`, Remnawave 3.4), «online now», drop connections, customer geography.
- Traffic by day and server in the admin, cabinet, Mini App and apps.
- A WireGuard / AmneziaWG pool, connection keys with QR codes, the bot command `/keys`.

## Servers and operations
- A full host and Internal Squad editor (checked against a live panel in CI).
- Rich Telegram alerts (title, quote, table, buttons).
- A torrent events-per-hour threshold.
- The iOS carrier taken from the ASN of the public IP.
- Production security headers on the test stack for the ZAP scan.

## Gateways
CloudPayments and Lava (cards, SBP): a notification counts only with a valid signature and after the order is re-read through the gateway API; both join the gateway queue and payment methods. Keys: `CLOUDPAYMENTS_*`, `LAVA_*`.
