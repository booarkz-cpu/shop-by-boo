# What is new in v28.36.0

Short operator notes for the modules added in v28.36.0. The detailed (Russian) pages are linked in each section.

## Payment gateway queue
«Tariffs and payment → Payment agents → Gateway queue» sets the order of the reserve chain (default YooKassa → RollyPay →
Platega → CryptoBot → Freekassa): move up/down, switch off, «return to work» after the circuit breaker opened. An order
that a gateway refuses goes to the next configured one by itself. The same queue is in the Android and iOS admin apps
(«Payments» tab). Launch readiness warns while only one gateway has keys.
The gateway report (`GET /api/admin/payments/providers-report`) shows conversion, average check, failures and refunds
per gateway and names the best one from 10 orders. Details: [billing](../modules/billing_and_taxes.md).

## Money recovery automation
New automation events: **abandoned checkout** (N minutes after an unpaid order, 5–4320) and **failed auto-renewal**
(0–14 days after), with ready presets: a reminder, a promo code for an abandoned checkout, a series «today / day 1 /
day 3» after a failed renewal, and a notice when traffic is limited.

## Account sync woken by commits
`/api/me/sync` now answers as soon as a payment, subscription or user row of that customer is committed (Redis
`sync:user:<id>` between processes, a check every 15 s as a safety net). Details: [account_sync](../modules/account_sync.md).

## Block monitor
Probes (`scripts/block-probe.py`, a cheap VPS in the customers' region) check the API domains, reserve domains and nodes
every 5 minutes. When every probe of a region fails a target that the shop sees working, it is a block: a Telegram alert,
the blocked API address goes last in the signed reserve list for the apps, and optionally every customer gets a reserve
Internal Squad (Reality, XHTTP) while it lasts. «Servers → Block monitor». The squad bulk calls of Remnawave were not
tried against a live panel, so the automatic reserve squad is off by default. Details: [anti_blocking](../modules/anti_blocking.md).

## Unit economics by source
The first-touch source of a customer (`?start=src_vk_ads`, `?startapp=src_…`, `?utm_source=…` on the cabinet) is
stored once (migration `0079_acquisition`). «Analytics → Unit economics» shows new and paying customers, revenue,
the ad spend you enter per month, CAC and ROMI. Details: [unit_economics](../modules/unit_economics.md).

## «VPN does not work» diagnostics in the apps
In the Android and iOS apps 3.2.0 the «Report a problem» button (with a subscription) checks DNS, the shop API, the
subscription download and TCP to every server, sends it with the customer's words to `POST /api/me/diagnostics` and
shows the likely cause at once (no or expired subscription, device limit, servers down, shop unreachable, servers
blocked from this network, some servers down). Support gets the full report as a ticket.
Details: [in_app_diagnostics](../modules/in_app_diagnostics.md).

## Hot standby of the database
`scripts/hot-standby.sh` sets up PostgreSQL streaming replication to a second server: TLS, a replication-only role,
the port open only to the standby's IP (a DOCKER-USER iptables rule — Docker ports bypass ufw). The standby agent
(`scripts/standby-agent.py`, every minute) reports lag to the primary and alerts in Telegram when the primary is silent
on every path (replication stream, `/health/live`, TCP 443 and 22). Promotion is one command (`hot-standby.sh promote`)
or automatic with `AUTO_PROMOTE=1`, optionally switching Cloudflare DNS. Automatic promotion is off by default because
of split brain; the returning old primary must run `hot-standby.sh demote` first. Not tried on two real servers yet —
run a drill. «Backups → Hot standby». Details: [hot_standby](../modules/hot_standby.md).

## Node autoscaling
«Servers → Autoscaling» watches users online per online node. Above the upper threshold for the sustain time it
recommends (Telegram) or, in auto mode, creates a Hetzner Cloud server with Remnawave Node and adds it to the panel;
below the lower threshold it removes a node it created itself (never a hand-made one). Auto mode needs
`HETZNER_API_TOKEN` and `REMNANODE_SECRET_KEY` in `.env`. The Remnawave node create/delete calls were not tried against
a live panel — watch the first run. Details: [node_autoscale](../modules/node_autoscale.md).

## Apps 3.2.0
Android versionCode 3200, iOS 3.2.0 (3200): the gateway queue in the admin apps and the diagnostics above.
