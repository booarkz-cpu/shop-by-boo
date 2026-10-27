#!/usr/bin/env bash
# Prepare the server for automatic deployment from GitHub Actions («Corgi Lusi Production Deploy»).
#
#   sudo bash scripts/setup-auto-deploy.sh            # on the shop server, as root
#
# Creates an SSH key that only GitHub uses (/root/.ssh/github_deploy), authorises it for root and
# prints the four secrets to add in GitHub → Settings → Environments → production → Environment
# secrets: DEPLOY_HOST, DEPLOY_USER, DEPLOY_SSH_KEY, DEPLOY_PATH (and DEPLOY_PORT if SSH is not 22).
# Running it again keeps the existing key. Remove the key line from authorized_keys to revoke.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Запустите от root: sudo bash scripts/setup-auto-deploy.sh" >&2; exit 1; }
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
[[ -f "$APP_DIR/.env" && -f "$APP_DIR/scripts/update-from-github.sh" ]] || { echo "Не найден магазин в $APP_DIR (нужны .env и scripts/update-from-github.sh)" >&2; exit 1; }
KEY=/root/.ssh/github_deploy
install -d -m 700 /root/.ssh
if [[ ! -f "$KEY" ]]; then
  ssh-keygen -q -t ed25519 -f "$KEY" -N "" -C "github-deploy@$(hostname)"
fi
touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
grep -qxF "$(cat "$KEY.pub")" /root/.ssh/authorized_keys || cat "$KEY.pub" >> /root/.ssh/authorized_keys
HOST="$(curl -4 -fsS --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
PORT="$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}')"
cat <<TXT

Готово. Добавьте в GitHub → Settings → Environments → production → Environment secrets:

  DEPLOY_HOST     = ${HOST}
  DEPLOY_USER     = root
  DEPLOY_PATH     = ${APP_DIR}
TXT
[[ -n "$PORT" && "$PORT" != 22 ]] && echo "  DEPLOY_PORT     = ${PORT}"
cat <<TXT
  DEPLOY_SSH_KEY  = весь текст ниже, от BEGIN до END включительно:

$(cat "$KEY")

Никому не пересылайте этот ключ — только в секрет GitHub. Затем Actions → «Corgi Lusi Production Deploy»
→ Run workflow с тегом текущего выпуска. Автодеплой работает при переменной репозитория AUTO_DEPLOY=true.
TXT
