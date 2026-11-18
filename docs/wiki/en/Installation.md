# Install the shop

## Prepare the server and DNS

Connect to an Ubuntu or Debian server over SSH as root. For each hostname you plan to enter during installation, create an A record pointing to the server’s IPv4 address. If you use IPv6, check the AAAA record as well.

The installer suggests `api`, `admin`, `app`, `cabinet` and `support` under your base domain. Check DNS for each name you choose, including any additional names you use for the bot, Mini App and panel.

```bash
dig +short api.example.com
```

## Install the published version

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v28.161.0/install.sh -o /root/shop-install.sh &&
  BRANCH=v28.161.0 bash /root/shop-install.sh
```

Run the commands in your SSH session. The installer prompts for domains and credentials, creates `.env` and starts the services. The default installation directory is `/opt/vpn-shop`. When configuring UFW, the installer accounts for the SSH port and adds rules for TCP 80/443 and UDP 443.

## Settings and first sign-in

The installer generates `APP_SECRET` and `DB_PASSWORD`. Keep the generated `.env` with your backup. Open the admin address printed at the end of the installation and sign in with `ADMIN_EMAIL` and `ADMIN_PASSWORD`. Leaving the password blank at the prompt generates one.

`PUBLIC_BASE_URL` contains the public HTTPS address of the API. The customer account uses a separate domain. To provision access through Remnawave, supply its panel address and token. The Telegram bot requires `BOT_TOKEN`. Open Security to configure 2FA and Plans to select the Internal Squad.

## Verify the installation

Run the diagnostic script from the installation directory. It checks the Compose configuration, calls the backend’s `/health/ready` endpoint inside its container, then checks HTTP responses from the admin panel, Mini App and customer account.

```bash
cd /opt/vpn-shop && bash scripts/doctor.sh
```

On success, the output includes `API health: OK`, `admin HTTP: OK`, `miniapp HTTP: OK` and `cabinet HTTP: OK`. For the external check, replace `api.example.com` with your API hostname.

```bash
curl -fsS https://api.example.com/health/ready
```

If the internal check passes but the public address is unreachable, check DNS and the Caddy logs. For a backend failure, start with `docker compose logs --tail=100 backend` in the installation directory.

## Related guides

[Payments](Payments.md) · [Troubleshooting](Troubleshooting.md) · [Updates](Updates.md) · [Home](Home.md)
