#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="${APP_DIR:-/opt/vpn-shop}"
cd "$APP_DIR"
[[ -f .env ]] || { echo "Missing $APP_DIR/.env" >&2; exit 2; }
umask 077
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ROLLBACK_DIR="${ROLLBACK_DIR:-$APP_DIR/.rollback}"
mkdir -p "$ROLLBACK_DIR"
SNAPSHOT="$ROLLBACK_DIR/pre-update-$STAMP.tar.gz"
DB_DUMP="$ROLLBACK_DIR/pre-update-$STAMP.sql"
# Never copy environment secrets into rollback archives.
tar --exclude='./.rollback' --exclude='./.control' --exclude='./.git' --exclude='./.env' --exclude='./.env.*' --exclude='*/.env' --exclude='*/.env.*' --exclude='*/node_modules' -czf "$SNAPSHOT" .
if docker compose up -d db >/dev/null 2>&1; then
  docker compose exec -T db pg_dump -U vpnshop -d vpnshop --clean --if-exists --no-owner --no-privileges > "$DB_DUMP" || { rm -f "$DB_DUMP"; echo 'Pre-update DB dump failed; update cancelled' >&2; exit 1; }
else
  echo "Database did not start; update cancelled" >&2
  exit 1
fi
[[ -s "$DB_DUMP" ]] || { echo "Database dump is empty; update cancelled" >&2; exit 1; }
ln -sfn "$(basename "$SNAPSHOT")" "$ROLLBACK_DIR/latest.tar.gz"
ln -sfn "$(basename "$DB_DUMP")" "$ROLLBACK_DIR/latest.sql" 2>/dev/null || true
rollback(){
  echo "Update failed; entering recovery mode and restoring pre-update snapshots..." >&2
  touch "$ROLLBACK_DIR/RECOVERY_MODE"
  docker compose down --remove-orphans || true
  tmp="$(mktemp -d)"
  tar -xzf "$SNAPSHOT" -C "$tmp"
  # Snapshots omit nested secrets, so carry every installed environment file.
  find . -path './.rollback' -prune -o -path './.git' -prune -o \
    -type f \( -name '.env' -o -name '.env.*' \) -exec cp --parents -p -- {} "$tmp" \;
  # .control holds the auto-update requests and status of the admin panel: kept as is.
  find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name '.env' ! -name '.env.*' ! -name '.git' ! -name '.rollback' ! -name '.control' -exec rm -rf {} +
  cp -a "$tmp"/. "$APP_DIR"/
  rm -rf "$tmp"
  if [[ -s "$DB_DUMP" ]]; then
    docker compose up -d db redis
    cat "$DB_DUMP" | docker compose exec -T db psql -U vpnshop -d vpnshop -v ON_ERROR_STOP=1 || { echo "DATABASE RESTORE FAILED; production remains stopped." >&2; exit 1; }
  else
    echo "DATABASE SNAPSHOT MISSING; production remains stopped." >&2
    exit 1
  fi
  docker compose up -d --remove-orphans
  bash scripts/doctor.sh
  rm -f "$ROLLBACK_DIR/RECOVERY_MODE"
}
trap rollback ERR
# A GitHub update passes the verified tree here. The snapshot above is the
# previous install. Copy only after that snapshot exists.
if [[ -n "${UPDATE_STAGE:-}" ]]; then
  [[ -d "$UPDATE_STAGE" && -f "$UPDATE_STAGE/backend/app/main.py" ]] || { echo "UPDATE_STAGE is not a shop release" >&2; exit 1; }
  tar --exclude='./.env' --exclude='./.env.*' --exclude='*/.env' --exclude='*/.env.*' --exclude='./.rollback' --exclude='*/.rollback' --exclude='./.control' --exclude='./.git' --exclude='*/.git' -C "$UPDATE_STAGE" -cf - . | tar -C "$APP_DIR" -xf -
fi
# v28.23.0+: move PostgreSQL 16 data to the PostgreSQL 18 volumes once (no-op afterwards).
bash scripts/upgrade-postgres.sh
bash deploy/build-production.sh
bash scripts/doctor.sh
trap - ERR
printf 'Update completed. Rollback snapshot: %s (database: %s)\n' "$SNAPSHOT" "$DB_DUMP"
