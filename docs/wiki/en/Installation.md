# Installation

From a bare server to the first customer. Every step says what to do, why, and how to check the result.

## 1. Prepare the server

You need a VDS on Ubuntu 22.04+ (verified on 24.04): 2 cores, 4 GB RAM, 20 GB SSD.

```bash
ssh root@YOUR_IP
apt update && apt upgrade -y
```

**Why:** the installer pulls Docker and packages from `apt`; on an outdated system the repositories may fail.

## 2. Point the domain at the server

Create records at your DNS provider:

| Type | Name | Value |
| --- | --- | --- |
| A | `admin` | server IP |
| A | `lk` | server IP |
| A | `app` | server IP |

**Why:** Caddy issues a TLS certificate only when the domain already points at the server.

Check it (it must return your IP):

```bash
dig +short admin.your-domain.com
```

## 3. Install the shop

One command:

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v28.56.0/install.sh -o /root/shop-install.sh
BRANCH=v28.56.0 bash /root/shop-install.sh
```

The installer asks for domains, prices and the administrator password, installs Docker, builds images, applies
migrations and starts the services. It does **not** report success if any service failed to start.

**Why this way:** the installer opens only 22, 80 and 443 — the database, Redis and the API stay closed.

## 4. Fill in `.env`

The installer creates the file. Required fields:

| Variable | Purpose | Where to get it |
| --- | --- | --- |
| `APP_SECRET` | signs sessions and tokens | `openssl rand -hex 32` |
| `DB_PASSWORD` | PostgreSQL password | choose a long one |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | admin panel sign-in | choose your own |
| `REMNAWAVE_URL`, `REMNAWAVE_TOKEN` | access delivery | Remnawave panel → API |
| `BOT_TOKEN` | Telegram bot | [@BotFather](https://t.me/BotFather) |
| `PUBLIC_BASE_URL` | shop address | your domain |

Apply the changes:

```bash
docker compose up -d
```

## 5. Verify everything is alive

```bash
bash scripts/doctor.sh
```

It checks the Compose configuration, the containers and whether `/health` answers. Expected: `API health: OK`.

```bash
curl -s localhost:8000/health
# {"ok":true,"version":"21.5.1","redis":true,"database":true,...}
```

## 6. First sign-in

1. Open `https://admin.your-domain.com`.
2. Sign in with `ADMIN_EMAIL` and `ADMIN_PASSWORD` from `.env`.
3. Change the password and enable 2FA under "Security".
4. Create plans under "Plans" and pick the Remnawave Internal Squad.
5. Connect a payment provider — see [Payments](Payments.md).

## If something is off

| Symptom | What to check |
| --- | --- |
| `doctor.sh` says API health: FAILED | `docker compose logs backend` |
| A container keeps restarting | `docker compose logs <service>`, `free -h` |
| No certificate | DNS record, ports 80 and 443, `docker compose logs caddy` |
| The panel opens but is empty | `curl -s localhost:8000/health`, then the browser console |

Full table: [Troubleshooting](Troubleshooting.md).

## Updating an installed shop

```bash
bash scripts/backup.sh
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.56.0 bash /opt/vpn-shop/scripts/update-from-github.sh
```

Details: [Updates](Updates.md).

[← Back to home](Home.md)
