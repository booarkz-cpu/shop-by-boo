#!/usr/bin/env bash
set -euo pipefail
APP="${SUPPORT_INSTALL_DIR:-/opt/support-pro-2}"
[ "$(id -u)" = 0 ] || { echo 'Запустите: sudo bash install.sh'; exit 1; }
command -v docker >/dev/null || { echo 'Установите Docker Engine и Compose v2, затем повторите.'; exit 1; }
docker compose version >/dev/null
command -v certbot >/dev/null || { echo 'Установите certbot, затем повторите.'; exit 1; }
command -v python3 >/dev/null
if [ -f "$APP/.env" ]; then
  echo 'Найдена существующая установка. Используйте UPGRADE.md, чтобы сохранить данные и конфигурацию.'
  exit 1
fi
mkdir -p "$APP"
if [ "$(pwd -P)" != "$(cd "$APP" && pwd -P)" ]; then
  cp -a . "$APP/"
fi
cd "$APP"
mkdir -p nginx/certbot/www nginx/certs backups
chown 10001:10001 backups
cp .env.example .env
chmod 600 .env
read -rp 'BOT_TOKEN: ' SUPPORT_BOT_TOKEN
read -rp 'DOMAIN: ' SUPPORT_DOMAIN
read -rp "Let's Encrypt email: " SUPPORT_EMAIL
export SUPPORT_BOT_TOKEN SUPPORT_DOMAIN SUPPORT_EMAIL
python3 - <<'PY'
import os,re,secrets
from pathlib import Path
values={'BOT_TOKEN':os.environ['SUPPORT_BOT_TOKEN'],'DOMAIN':os.environ['SUPPORT_DOMAIN'],
        'LETSENCRYPT_EMAIL':os.environ['SUPPORT_EMAIL'],'POSTGRES_PASSWORD':secrets.token_hex(32),
        'REDIS_PASSWORD':secrets.token_hex(32),'SESSION_SECRET':secrets.token_hex(32),'ADMIN_PASSWORD':secrets.token_urlsafe(24),
        'PUBLIC_ORIGIN':'https://'+os.environ['SUPPORT_DOMAIN']}
if not re.fullmatch(r'[A-Za-z0-9.-]+',values['DOMAIN']): raise SystemExit('Некорректный домен')
if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+',values['BOT_TOKEN']): raise SystemExit('Некорректный токен')
if any('\n' in x or '\r' in x for x in values.values()): raise SystemExit('Некорректное значение')
p=Path('.env');p.write_text('\n'.join(line.split('=',1)[0]+'='+values[line.split('=',1)[0]] if line.split('=',1)[0] in values else line for line in p.read_text().splitlines())+'\n')
PY
docker compose build
docker compose up -d db redis
docker compose run --rm migrate
docker compose run --rm --no-deps app python -m app.cli init
docker compose up -d app worker bot backup nginx
certbot certonly --webroot -w "$APP/nginx/certbot/www" -d "$SUPPORT_DOMAIN" --email "$SUPPORT_EMAIL" --agree-tos --non-interactive
install -m 644 "/etc/letsencrypt/live/$SUPPORT_DOMAIN/fullchain.pem" nginx/certs/fullchain.pem
install -m 640 -g 101 "/etc/letsencrypt/live/$SUPPORT_DOMAIN/privkey.pem" nginx/certs/privkey.pem
python3 - <<'PY'
import os
from pathlib import Path
domain=os.environ['SUPPORT_DOMAIN']
Path('nginx/nginx.conf').write_text('''server {
 listen 80; server_name DOMAIN;
 location /.well-known/acme-challenge/ { root /var/www/certbot; }
 location / { return 301 https://$host$request_uri; }
}
server {
 listen 443 ssl; server_name DOMAIN; client_max_body_size 52m;
 access_log off; # Portal recovery URLs are bearer credentials.
 ssl_certificate /etc/letsencrypt/fullchain.pem;
 ssl_certificate_key /etc/letsencrypt/privkey.pem;
 add_header Strict-Transport-Security "max-age=31536000" always;
 location / {
  proxy_pass http://app:8000; proxy_http_version 1.1;
  proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade";
  proxy_set_header Host $host; proxy_set_header X-Forwarded-Proto https;
  proxy_set_header X-Forwarded-For $remote_addr;
  proxy_read_timeout 75s;
 }
}
'''.replace('DOMAIN',domain))
PY
docker compose exec -T nginx nginx -t
docker compose exec -T nginx nginx -s reload
printf '%s\n' "Панель: https://$SUPPORT_DOMAIN"
python3 - <<'PY'
from pathlib import Path
for line in Path('.env').read_text().splitlines():
 if line.startswith(('ADMIN_LOGIN=','ADMIN_PASSWORD=')): print(line)
PY
printf '%s\n' 'Сохраните пароль и TOTP. Настройте ежедневный запуск scripts/renew-cert.sh и внешний backup uploads.'
