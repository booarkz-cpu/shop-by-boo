# Installing the shop

You need a terminal once: for the first deployment of the shop's containers. Everything else is done in the admin panel — settings without a restart, updates, Remnawave, backups.

Russian original: [INSTALLATION_GUIDE](../../ru/new/INSTALLATION_GUIDE.md). Other guides: [index](README.md).

## Requirements

| What | Recommended setup |
| --- | --- |
| OS | Ubuntu 24.04 or Debian 12 |
| Resources | 4 vCPUs, 8 GB RAM, 40 GB disk for building all images |
| Access | root over SSH; the shop's domains pointing at the server (A/AAAA) |
| Ports | 80 and 443 (Caddy); 25 only if receiving mail is enabled |

## One-command install

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v28.161.0/install.sh -o /root/shop-install.sh &&
  BRANCH=v28.161.0 bash /root/shop-install.sh
```

`install.sh` installs `git`, `curl` and Docker (`infrastructure/deployment/install-docker.sh`), clones the release to `/opt/vpn-shop-src` and hands over to `infrastructure/deployment/install-vps.sh`, which:

1. **Checks the system:** OS, root, free ports, a terminal for questions. Without a terminal set `INSTALL_NONINTERACTIVE=1` and the environment variables.
2. **Configures:** asks for the domains, the Let's Encrypt e-mail, the bot token and the SSH port; generates the secrets (`APP_SECRET`, database passwords); writes `.env` with mode 600 (`scripts/harden-env.py`).
3. **Firewall:** opens the SSH port, 80 and 443. PostgreSQL, Redis, the API and the panels are never exposed.
4. **Images:** pins the base images by digest (`scripts/pin-images.sh`, file `.env.images`).
5. **Builds and starts:** `infrastructure/deployment/build-production.sh`, then waits for the API and the migrations (`alembic upgrade head` runs when the backend starts).
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

## Updates, backups and recovery

Schedule a maintenance window and save an encrypted `.vpb` backup before updating. Keep the file, its checksum and the release identity off-host. Keep the password separately.

Follow the [update guide](../../wiki/en/Updates.md) to select a published tag and check the result. The updater’s rollback snapshot covers the shop files and main database. The [full recovery procedure](../../wiki/en/Backup.md) also covers secrets, uploaded files and the Support Pro database when present.

[Docker guide in Russian](../../ru/new/DOCKER_GUIDE.md).
