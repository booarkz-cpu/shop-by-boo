# Admin panel guide

The admin panel is the single place to run the shop. Every section works through the backend's typed API. The browser never runs commands on the server and never sends the server arbitrary commands, paths or addresses to execute.

Russian original: [ADMIN_PANEL_GUIDE](../../ru/new/ADMIN_PANEL_GUIDE.md). Related: [ADMIN_MODULES](../../ru/new/ADMIN_MODULES.md) (modules and sections), [ADMIN_CONTROL_MATRIX](../../ru/new/ADMIN_CONTROL_MATRIX.md) (operations of every module), [RBAC](../../ru/new/RBAC.md) (roles and permissions). Other guides: [index](README.md).

## Signing in

The panel is at `https://<ADMIN_DOMAIN>`. Ways to sign in:
- e-mail and password;
- a passkey;
- the Telegram Mini App, if the administrator has a Telegram ID and no two-factor protection;
- a one-time ticket from the administrator app (valid for 60 seconds).

With two-factor protection on, the password is followed by a code from an authenticator app or a recovery code. Dangerous actions (restoring a backup, running a plan on servers, deleting copies and others) ask for the code again, valid for 10 minutes in this session.

The installer creates the first administrator. Others are added in «Security → Roles and administrators»: e-mail, password, Telegram ID and role; an account can be disabled or deleted there too.

## Layout

- **Menu** on the left, eight groups: Analytics, Users, Plans and payments, Marketing, Bot and cabinet, Servers, System, Security. On a phone the menu slides out with a button.
- **Section search:** `⌘K` / `Ctrl+K`, or the field on the «All sections» page.
- **Admin center** («System → Admin center: 30 modules»): the 30 modules of the specification — which sections manage them, which operations exist, which permissions they need. The button in a row opens the section.
- **Section state.** Every section shows loading, an error with its reason and a «Retry» button, or an empty state with a hint. Without a permission the server answers 403 and the section shows why.

## System status

«Analytics → System status» (`GET /api/admin/health/summary`, permission `ops.diagnostics`) — one page with the state of every part of the installation. Each row has a status («OK», «attention», «error» or «not configured»), one sentence about what was found, the response time of network checks and a button to the section that manages that part.

| Part | What is checked | Section |
| --- | --- | --- |
| Backend (API) | Answers; release number and API version | Updates |
| Frontend | The admin panel, cabinet and Mini App serve their page | Deployments |
| PostgreSQL | `SELECT 1`, response time | Diagnostics |
| Database migrations | The database mark equals the release's latest migration | Updates |
| Redis | `PING`, response time | Diagnostics |
| Remnawave | The panel answers and accepts the token; «not configured» without an address | Remnawave: panel |
| Nodes | How many enabled nodes are online | Servers |
| Caddy (reverse proxy) | Accepts HTTPS for the shop's domains | Diagnostics |
| TLS certificates | Every domain's certificate chain is valid; a warning 14 days before expiry | Diagnostics |
| Payments | Which gateways are configured, which are temporarily out of the queue after errors, whether payments are paused | Payment gateways |
| Background jobs | A live worker (mark within 90 s), jobs queued longer than 15 min, failures within a day | Job queue |
| Backups | Age of the latest good copy; a warning after 26 h | Backups |
| Telegram bot | The bot's connection to Telegram as the bot process reports it | Telegram bot |
| Updates | The installed release and the latest release on GitHub (cached for an hour) | Updates |

Each check has its own time limit (5 seconds for network ones); a slow or broken part never hides the others; answers of external services, tokens and passwords never reach the page — the reason goes to the server log. «Check again» repeats every check. Free disk space and memory are shown by «Monitoring» and «Diagnostics».

## Common tasks

| Task | Where |
| --- | --- |
| Find a customer, extend, change the plan, refund | Users → Shop customers → customer card |
| Create or change a plan | Plans and payments → Plans, Plan builder |
| Turn on sign-in with Google, Yandex ID, VK ID | System → Settings without restart, OAuth group |
| Connect a payment gateway | System → Settings without restart (keys), then Plans and payments → Payment gateways (enable, queue order, check) |
| Connect Remnawave | System → Settings without restart: `REMNAWAVE_URL`, `REMNAWAVE_TOKEN`; then Servers → Remnawave: panel — or install it from the panel ([Remnawave guide](REMNAWAVE.md)) |
| Add or restart a node | Servers → Servers |
| Bot texts, buttons, banners, documents; app texts | Bot and cabinet; Android and iOS |
| Show or hide the «Apps» block in the cabinet | Android and iOS → «Apps» block in the cabinet |
| Backup and restore | Security → Backups, Restore |
| Update the shop | System → Updates: check the release, auto-update on a schedule or with a button |
| Who changed what | Security → Action log: search by administrator, action, object and period |

## What still needs the server

| What | Why |
| --- | --- |
| The first installation of the shop | There are no containers yet. Remnawave itself is installed from the panel: «Servers → Remnawave installation» |
| A one-time install of the auto-update agent (`scripts/auto-update.sh install`) on shops installed before v28.74.0 | The agent runs on the host; a container cannot install a systemd service, on purpose. Newer installers enable it themselves |
| The shop's own domains (`ADMIN_DOMAIN`, `API_DOMAIN`…), the database and Redis connection | Read from `.env` when the containers start. Gateway keys, Remnawave, Cloudflare, mail and `BOT_TOKEN` change without a restart in «Settings without restart»; subscription portal domains in «Servers → Domains and certificates» |

All 30 modules are managed from the panel. There are no mock-ups without a function in it.

## Security

- The server checks permissions on every request ([RBAC](../../ru/new/RBAC.md)).
- Changes go to the action log.
- System operations — backup, restore check, update, node restart — run through separate routes with validated input; commands on the host are run by the agent, which accepts only requests of a known format.
- The node terminal needs the `nodes.terminal` permission and works only on nodes where the owner enabled it (`AGENT_TERMINAL=1`).
