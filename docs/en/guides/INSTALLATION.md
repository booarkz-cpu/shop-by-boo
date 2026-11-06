# Installing the shop

You need a terminal once: for the first deployment of the shop's containers. Everything else is done in the admin panel — settings without a restart, updates, Remnawave, backups.

Russian original: [INSTALLATION_GUIDE](../../ru/new/INSTALLATION_GUIDE.md). Other guides: [index](README.md).

## Requirements

| What | Minimum |
| --- | --- |
| OS | Ubuntu 22.04 / 24.04 / 26.04 or Debian 12 / 13 (others with a warning) |
| Resources | 2 CPU, 4 GB RAM, 30 GB disk |
| Access | root over SSH; the shop's domains pointing at the server (A/AAAA) |
| Ports | 80 and 443 (Caddy); 25 only if receiving mail is enabled |

## One-command install

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v28/install.sh | sudo bash
```

`install.sh` installs `git`, `curl` and Docker (`deploy/install-docker.sh`), clones the release to `/opt/vpn-shop-src` and hands over to `deploy/install-vps.sh`, which:

1. **Checks the system:** OS, root, free ports, a terminal for questions. Without a terminal set `INSTALL_NONINTERACTIVE=1` and the environment variables.
2. **Configures:** asks for the domains, the Let's Encrypt e-mail, the bot token and the SSH port; generates the secrets (`APP_SECRET`, database passwords); writes `.env` with mode 600 (`scripts/harden-env.py`).
3. **Firewall:** opens the SSH port, 80 and 443. PostgreSQL, Redis, the API and the panels are never exposed.
4. **Images:** pins the base images by digest (`scripts/pin-images.sh`, file `.env.images`).
5. **Builds and starts:** `deploy/build-production.sh`, then waits for the API and the migrations (`alembic upgrade head` runs when the backend starts).
6. **Support Pro:** creates the first operator and shows the TOTP secret.
7. **Auto-update:** enables the agent `scripts/auto-update.sh install` ([AUTO_UPDATE](../../ru/new/AUTO_UPDATE.md)).

Running the installer again on an installed shop breaks nothing: `install.sh` refuses to replace a directory with another release and offers an update instead.

## Diagnostics

| Command | What it checks |
| --- | --- |
| `bash scripts/preflight.sh` | script syntax, Python build, pinned digests, `docker compose config` |
| `bash scripts/doctor.sh` | containers, API `/health/ready`, the admin panel, cabinet and Mini App answering |
| Admin panel → «System status» | every part of the shop separately ([admin panel guide](ADMIN_PANEL.md#system-status)) |
| Admin panel → «Automation Center» | all automation ([AUTOMATION_CENTER](../../ru/new/AUTOMATION_CENTER.md)) |

## Updates, backups and restore

| What | From the admin panel | From the server (if the panel is down) |
| --- | --- | --- |
| Update the shop | «Updates → Check and update now» | `sudo bash scripts/auto-update.sh run` |
| Roll back | automatically when an update fails | `sudo bash scripts/rollback.sh` (latest snapshot) |
| Backup | «Backups»: schedule, «Create», verify, upload to Telegram | `bash scripts/backup.sh` (both databases, files and `.env`, encrypted) |
| Restore | «Backups → Restore» (with confirmation) | the steps in [BACKUP_CURRENT](../../ru/BACKUP_CURRENT.md) |
| Remnawave | «Updates → Remnawave auto-update» | — |

Update snapshots live in `.rollback/` and contain no secrets (`.env`). `.env` and the auto-update agent's `.control` directory are kept through both updates and rollbacks.

Every pull request runs a **restore drill** in CI: data in a running shop → an encrypted copy with `scripts/backup.sh` → every volume and both `.env` files lost → restore from the copy alone → every table, subscription, payment and administrator is back and the administrator signs in.

More on Docker: [DOCKER_GUIDE](../../ru/new/DOCKER_GUIDE.md).
