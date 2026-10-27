#!/usr/bin/env bash
# Автообновление магазина с GitHub без участия владельца и без секретов GitHub.
#
#   sudo bash scripts/auto-update.sh install   # включить (установщик делает это сам)
#   sudo bash scripts/auto-update.sh status    # версия, расписание, итог последнего запуска
#   sudo bash scripts/auto-update.sh run       # проверить и обновить сейчас
#   sudo bash scripts/auto-update.sh disable   # выключить
#
# Каждую ночь (по умолчанию 03:00 МСК) сервер сам проверяет новый стабильный выпуск на GitHub и ставит
# его через scripts/update-from-github.sh (SHA-256, снимок и дамп базы, проверка здоровья, откат).
# Включение, время и «Обновить сейчас» доступны в админ-панели → «Обновления». Логика — scripts/auto_update.py.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Запустите от root: sudo bash $0 ${1:-install}" >&2; exit 1; }
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
export APP_DIR
command -v systemctl >/dev/null || { echo "Нужен systemd" >&2; exit 1; }
exec python3 "$APP_DIR/scripts/auto_update.py" "${1:-status}"
