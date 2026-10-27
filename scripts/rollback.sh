#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="${APP_DIR:-/opt/vpn-shop}"
ROLLBACK_DIR="${ROLLBACK_DIR:-$APP_DIR/.rollback}"
ARCHIVE="${1:-$ROLLBACK_DIR/latest.tar.gz}"
DB_ARCHIVE="${2:-$ROLLBACK_DIR/latest.sql}"
[[ -f "$ARCHIVE" ]] || { echo "Rollback archive not found: $ARCHIVE" >&2; exit 2; }
[[ -s "$DB_ARCHIVE" ]] || { echo "Database snapshot is required for a safe rollback." >&2; exit 2; }
tar -tzf "$ARCHIVE" >/dev/null || { echo "Rollback archive is unreadable; installation unchanged." >&2; exit 2; }
python3 "$(dirname "${BASH_SOURCE[0]}")/validate-rollback-archive.py" "$ARCHIVE"
cd "$APP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ROLLBACK_DIR"
tar --exclude='./.rollback' --exclude='./.git' --exclude='./.env' --exclude='./.env.*' --exclude='*/.env' --exclude='*/.env.*' --exclude='*/node_modules' -czf "$ROLLBACK_DIR/pre-rollback-$STAMP.tar.gz" .
touch "$ROLLBACK_DIR/RECOVERY_MODE"
docker compose --profile standby down --remove-orphans || true
tmp="$(mktemp -d)"
tar -xzf "$ARCHIVE" -C "$tmp"
# Snapshots exclude every nested environment file; carry the installed copies
# into the restored tree before removing it.
find . -path './.rollback' -prune -o -path './.git' -prune -o \
  -type f \( -name '.env' -o -name '.env.*' \) -exec cp --parents -p -- {} "$tmp" \;
find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name '.env' ! -name '.env.*' ! -name '.git' ! -name '.rollback' -exec rm -rf {} +
cp -a "$tmp"/. "$APP_DIR"/
rm -rf "$tmp"
docker compose up -d db redis
cat "$DB_ARCHIVE" | docker compose exec -T db psql -U vpnshop -d vpnshop -v ON_ERROR_STOP=1
bash deploy/build-production.sh
bash scripts/doctor.sh
rm -f "$ROLLBACK_DIR/RECOVERY_MODE"
printf 'Rollback completed from %s (database: %s)\n' "$ARCHIVE" "$DB_ARCHIVE"
