#!/usr/bin/env bash
# Move the shop and Support Pro databases from PostgreSQL 16 volumes to PostgreSQL 18.
#
# PostgreSQL 18 cannot open data files of an older major version, and the official
# postgres:18 image keeps data in /var/lib/postgresql/18/docker. Releases from v28.24.0
# therefore use new volumes (postgres18_data, support_postgres18_data). This script:
#   1. stops the stack and starts the old data once in a temporary postgres:16 container;
#   2. dumps it (pg_dump -Fc) and counts rows in every table;
#   3. starts the PostgreSQL 18 service on its new volume and restores the dump;
#   4. compares row counts table by table, runs ANALYZE and writes a marker.
# The PostgreSQL 16 volume is never changed or removed: it stays for rollback and can be
# deleted by hand later (docker volume rm <project>_postgres_data).
#
# Safe to run repeatedly: it does nothing on fresh installs and after a finished move.
#   APP_DIR=/opt/vpn-shop bash scripts/upgrade-postgres.sh
#   PG_UPGRADE_FORCE=1 ...  replace data written to PostgreSQL 18 before the move
set -Eeuo pipefail
APP_DIR="${APP_DIR:-/opt/vpn-shop}"
cd "$APP_DIR"
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 2; }
umask 077
OLD_IMAGE="${PG_OLD_IMAGE:-postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea}"
MARKER=/var/lib/postgresql/.migrated-from-postgres16
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
KEEP_DIR="${ROLLBACK_DIR:-$APP_DIR/.rollback}"
mkdir -p "$KEEP_DIR"
project="$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
services="$(docker compose config --services)"
work="$(mktemp -d)"
temp=""
cleanup(){ [[ -n "$temp" ]] && docker rm -f "$temp" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT

# Installs pinned before v28.24.0 keep POSTGRES_IMAGE=postgres:16… in .env and .env.images.
# Docker Compose would start PostgreSQL 16 on the new volume; switch them to the
# PostgreSQL 18 digest from docker-compose.yml first.
repin_postgres(){
  local default file value
  default="$(sed -nE 's/.*\$\{POSTGRES_IMAGE:-([^}]+)\}.*/\1/p' docker-compose.yml | head -1)"
  [[ "$default" == postgres:18* ]] || { echo "docker-compose.yml has no PostgreSQL 18 default image" >&2; exit 2; }
  for file in .env .env.images; do
    [[ -f "$file" ]] || continue
    value="$(sed -nE 's/^POSTGRES_IMAGE=(.*)$/\1/p' "$file" | tail -1)"
    if [[ -n "$value" && "$value" != postgres:18* ]]; then
      sed -i -E "s|^POSTGRES_IMAGE=.*$|POSTGRES_IMAGE=${default}|" "$file"
      echo "$file: POSTGRES_IMAGE ${value%%@*} -> ${default%%@*}"
    fi
  done
}
repin_postgres
export POSTGRES_IMAGE="$(sed -nE 's/^POSTGRES_IMAGE=(.*)$/\1/p' .env.images 2>/dev/null | tail -1)"
[[ -n "$POSTGRES_IMAGE" ]] || unset POSTGRES_IMAGE

# psql \gexec prints "schema.table count" for every user table, sorted.
COUNT_SQL="SELECT format('SELECT %L || '' '' || count(*) FROM %I.%I', schemaname || '.' || tablename, schemaname, tablename) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY schemaname, tablename \\gexec"

stopped=0
stop_stack(){
  if (( ! stopped )); then
    echo "PostgreSQL 18: stopping the stack before moving data"
    docker compose down --remove-orphans
    stopped=1
  fi
}

move(){
  local service="$1" old_volume="$2" new_volume="$3" user="$4" db="$5"
  grep -qx "$service" <<<"$services" || return 0
  local old="${project}_${old_volume}"
  if ! docker volume inspect "$old" >/dev/null 2>&1; then
    echo "$service: no PostgreSQL 16 volume ($old) — nothing to move"
    return 0
  fi
  local version
  version="$(docker run --rm --entrypoint cat -v "$old":/old:ro "$OLD_IMAGE" /old/PG_VERSION 2>/dev/null || true)"
  if [[ "$version" != "16" ]]; then
    echo "$service: $old holds no PostgreSQL 16 cluster (PG_VERSION='${version}') — skipped"
    return 0
  fi
  if docker volume inspect "${project}_${new_volume}" >/dev/null 2>&1 &&
     docker run --rm --entrypoint test -v "${project}_${new_volume}":/new:ro "$OLD_IMAGE" -f "/new/${MARKER##*/}"; then
    echo "$service: already moved to PostgreSQL 18"
    return 0
  fi
  stop_stack
  docker compose up -d --wait "$service" >/dev/null
  # Anything in the new cluster before the marker comes from a service that started
  # before the move (for example migrations on an empty database). Real data there is
  # not discarded silently.
  local rows
  rows="$(docker compose exec -T "$service" psql -U "$user" -d "$db" -At -v ON_ERROR_STOP=1 -c "SELECT coalesce(sum(n_live_tup),0) FROM pg_stat_user_tables WHERE relname <> 'alembic_version'")"
  if [[ "${rows:-0}" != "0" && "${PG_UPGRADE_FORCE:-0}" != "1" ]]; then
    echo "$service: PostgreSQL 18 already contains ${rows} rows written before the move." >&2
    echo "Check them; to replace them with the PostgreSQL 16 data run again with PG_UPGRADE_FORCE=1." >&2
    exit 1
  fi
  docker compose stop "$service" >/dev/null

  echo "$service: dumping PostgreSQL 16 data from $old"
  temp="pg16-upgrade-${service}-$$"
  docker run -d --name "$temp" --network none -e POSTGRES_PASSWORD=upgrade-only -v "$old":/var/lib/postgresql/data "$OLD_IMAGE" >/dev/null
  for _ in $(seq 1 60); do
    docker exec "$temp" pg_isready -U "$user" -d "$db" >/dev/null 2>&1 && break
    sleep 2
  done
  docker exec "$temp" pg_isready -U "$user" -d "$db" >/dev/null || { docker logs --tail=50 "$temp" >&2; echo "$service: PostgreSQL 16 did not start" >&2; exit 1; }
  docker exec "$temp" pg_dump -U "$user" -d "$db" -Fc > "$work/$service.dump"
  docker exec -i "$temp" psql -U "$user" -d "$db" -At -v ON_ERROR_STOP=1 <<<"$COUNT_SQL" > "$work/$service.before"
  docker rm -f "$temp" >/dev/null; temp=""
  [[ -s "$work/$service.dump" ]] || { echo "$service: empty dump" >&2; exit 1; }
  cp "$work/$service.dump" "$KEEP_DIR/postgres16-${service}-${STAMP}.dump"

  echo "$service: restoring into PostgreSQL 18"
  docker compose up -d --wait "$service" >/dev/null
  docker compose exec -T "$service" psql -U "$user" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" -c "CREATE DATABASE \"$db\" OWNER \"$user\"" >/dev/null
  docker compose exec -T "$service" pg_restore -U "$user" -d "$db" --no-owner --role="$user" --exit-on-error < "$work/$service.dump"
  docker compose exec -T "$service" psql -U "$user" -d "$db" -At -v ON_ERROR_STOP=1 <<<"$COUNT_SQL" > "$work/$service.after"
  if ! diff -u "$work/$service.before" "$work/$service.after"; then
    echo "$service: row counts differ after restore; PostgreSQL 16 data is untouched in $old" >&2
    exit 1
  fi
  docker compose exec -T "$service" vacuumdb -U "$user" -d "$db" --analyze-only --quiet
  docker compose exec -T "$service" sh -c "echo 'moved $STAMP: $(wc -l < "$work/$service.after") tables' > $MARKER"
  echo "$service: moved to PostgreSQL 18 ($(wc -l < "$work/$service.after") tables, row counts match). Dump kept: $KEEP_DIR/postgres16-${service}-${STAMP}.dump"
}

# service:old_volume:new_volume:user:database, comma-separated. The default matches this
# repository's docker-compose.yml; standalone Support Pro uses
# PG_UPGRADE_SPEC="db:pgdata:pgdata18:<POSTGRES_USER>:<POSTGRES_DB>".
SPEC="${PG_UPGRADE_SPEC:-db:postgres_data:postgres18_data:vpnshop:vpnshop,support_db:support_postgres_data:support_postgres18_data:support:support}"
IFS=',' read -ra entries <<<"$SPEC"
for entry in "${entries[@]}"; do
  IFS=':' read -r service old_volume new_volume user db <<<"$entry"
  [[ "$service" =~ ^[a-z0-9_-]+$ && "$old_volume" =~ ^[a-z0-9_-]+$ && "$new_volume" =~ ^[a-z0-9_-]+$ && "$user" =~ ^[A-Za-z0-9_]+$ && "$db" =~ ^[A-Za-z0-9_]+$ ]] || { echo "Bad PG_UPGRADE_SPEC entry: $entry" >&2; exit 2; }
  move "$service" "$old_volume" "$new_volume" "$user" "$db"
done
if (( stopped )); then
  docker compose down --remove-orphans
fi
echo "PostgreSQL 18 check finished"
