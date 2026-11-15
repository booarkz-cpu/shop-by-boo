#!/usr/bin/env bash
set -euo pipefail
APP="${1:-/opt/support-pro-2}"
cd "$APP"
DOMAIN=$(sed -n 's/^DOMAIN=//p' .env | head -n 1)
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || { echo 'Invalid DOMAIN' >&2; exit 1; }
certbot renew --quiet
install -m 644 "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" nginx/certs/fullchain.pem
install -m 640 -g 101 "/etc/letsencrypt/live/$DOMAIN/privkey.pem" nginx/certs/privkey.pem
docker compose exec -T nginx nginx -t
docker compose exec -T nginx nginx -s reload
