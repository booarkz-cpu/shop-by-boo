#!/usr/bin/env bash
# Move shop and Support Pro databases from PostgreSQL 18 volumes to PostgreSQL 19.
#
# PostgreSQL 19 cannot open a PostgreSQL 18 data directory. This script:
#   1. stops the stack;
#   2. refuses to start when the work directory has less free space than asked;
#   3. dumps the PostgreSQL 18 cluster (pg_dump -Fc) and counts rows;
#   4. restores into a new PostgreSQL 19 volume, compares row counts, runs ANALYZE;
#   5. keeps the dump and leaves the PostgreSQL 18 volume untouched for rollback.
# It never deletes a volume. A failed restore exits before any later step and
# prints that the PostgreSQL 18 volume is unchanged.
#
#   APP_DIR=/opt/vpn-shop bash scripts/upgrade-postgres19.sh
#   PG19_UPGRADE_FORCE=1 ...  replace rows already written on the empty-looking 19 volume
#   PG19_MIN_FREE_BYTES=...   refuse when the work directory is smaller than this
#   PG19_ROLLBACK=1 ...       only check that the PostgreSQL 18 volume is still readable
set -Eeuo pipefail
APP_DIR="${APP_DIR:-/opt/vpn-shop}"
cd "$APP_DIR"
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 2; }
command -v python3 >/dev/null || { echo "Python 3 is required" >&2; exit 2; }
umask 077
PG18_IMAGE="${PG18_IMAGE:-postgres:18.7-alpine@sha256:ff64c9e3bdf8e2120107d3559de8db314e8305f7e38c5105903c6295876738ff}"
PG19_IMAGE="${PG19_IMAGE:-postgres:19.0-alpine@sha256:cac45fb483caee3668946088a1c0532db89d5285c28dbfeac889b4068296e06f}"
MARKER=/var/lib/postgresql/.migrated-from-postgres18
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
KEEP_DIR="${ROLLBACK_DIR:-$APP_DIR/.rollback}"
mkdir -p "$KEEP_DIR"
project="$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
services="$(docker compose config --services)"
work="$(mktemp -d)"
temp=""
dest=""
cleanup(){ [[ -n "$temp" ]] && docker rm -f "$temp" >/dev/null 2>&1 || true; [[ -n "$dest" ]] && docker rm -f "$dest" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT
COUNT_SQL="SELECT format('SELECT %L || '' '' || count(*) FROM %I.%I', schemaname || '.' || tablename, schemaname, tablename) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY schemaname, tablename \\gexec"

free_bytes(){ df -B1 -P "$work" | awk 'NR==2 {print $4}'; }

password_of(){
  PG_SVC="$1" docker compose config --format json | python3 -c 'import json,os,sys
env=(json.load(sys.stdin).get("services") or {}).get(os.environ["PG_SVC"],{}).get("environment") or {}
if isinstance(env, list):
    env=dict(item.split("=",1) for item in env if "=" in item)
print(env.get("POSTGRES_PASSWORD",""))'
}

stopped=0
stop_stack(){
  if (( ! stopped )); then
    echo "PostgreSQL 19: stopping the stack before moving data"
    docker compose down --remove-orphans
    stopped=1
  fi
}

version_of(){
  local volume="$1" version
  version="$(docker run --rm --entrypoint cat -v "$volume":/old:ro "$PG18_IMAGE" /old/18/docker/PG_VERSION 2>/dev/null || true)"
  if [[ -z "$version" ]]; then
    version="$(docker run --rm --entrypoint cat -v "$volume":/old:ro "$PG18_IMAGE" /old/PG_VERSION 2>/dev/null || true)"
  fi
  printf '%s' "$version"
}

ready(){
  local name="$1" user="$2" db="$3" _
  for _ in $(seq 1 60); do
    docker exec "$name" pg_isready -U "$user" -d "$db" >/dev/null 2>&1 && return 0
    sleep 2
  done
  docker logs --tail=50 "$name" >&2
  return 1
}

move(){
  local service="$1" old_volume="$2" new_volume="$3" user="$4" db="$5"
  grep -qx "$service" <<<"$services" || return 0
  local old="${project}_${old_volume}" new="${project}_${new_volume}"
  if ! docker volume inspect "$old" >/dev/null 2>&1; then
    echo "$service: no PostgreSQL 18 volume ($old) — nothing to move"
    return 0
  fi
  local avail need="${PG19_MIN_FREE_BYTES:-0}"
  avail="$(free_bytes)"
  if (( need > 0 && avail < need )); then
    echo "$service: not enough free space (have $avail, need $need). No data was moved." >&2
    exit 1
  fi
  if [[ "${PG19_ROLLBACK:-0}" == "1" ]]; then
    local version
    version="$(version_of "$old")"
    [[ "$version" == "18" ]] || { echo "$service: rollback baseline $old is not PostgreSQL 18 (PG_VERSION='$version')" >&2; exit 1; }
    echo "$service: PostgreSQL 18 volume $old is intact for rollback"
    return 0
  fi
  local version
  version="$(version_of "$old")"
  if [[ "$version" != "18" ]]; then
    echo "$service: $old holds no PostgreSQL 18 cluster (PG_VERSION='$version') — skipped"
    return 0
  fi
  if docker volume inspect "$new" >/dev/null 2>&1 &&
     docker run --rm --entrypoint test -v "$new":/new:ro "$PG19_IMAGE" -f "/new/${MARKER##*/}"; then
    echo "$service: already moved to PostgreSQL 19"
    return 0
  fi
  local source_bytes
  source_bytes="$(docker run --rm --entrypoint du -v "$old":/old:ro "$PG18_IMAGE" -sb /old | awk '{print $1}')"
  avail="$(free_bytes)"
  if [[ "$source_bytes" =~ ^[0-9]+$ ]] && (( avail < source_bytes )); then
    echo "$service: not enough free space for the dump (have $avail, source $source_bytes). No data was moved." >&2
    exit 1
  fi
  stop_stack
  local password
  password="$(password_of "$service")"
  [[ -n "$password" ]] || { echo "$service: POSTGRES_PASSWORD is empty" >&2; exit 2; }
  dest="pg19-upgrade-${service}-$$"
  docker run -d --name "$dest" --network none \
    -e POSTGRES_USER="$user" -e POSTGRES_PASSWORD="$password" -e POSTGRES_DB="$db" \
    -v "$new":/var/lib/postgresql "$PG19_IMAGE" >/dev/null
  ready "$dest" "$user" "$db" || { echo "$service: PostgreSQL 19 did not start" >&2; exit 1; }
  local rows
  rows="$(docker exec "$dest" psql -U "$user" -d "$db" -At -v ON_ERROR_STOP=1 -c "SELECT coalesce(sum(n_live_tup),0) FROM pg_stat_user_tables WHERE relname <> 'alembic_version'")"
  if [[ "${rows:-0}" != "0" && "${PG19_UPGRADE_FORCE:-0}" != "1" ]]; then
    echo "$service: PostgreSQL 19 already contains ${rows} rows written before the move." >&2
    echo "Check them; to replace them with the PostgreSQL 18 data run again with PG19_UPGRADE_FORCE=1." >&2
    exit 1
  fi
  echo "$service: dumping PostgreSQL 18 data from $old"
  temp="pg18-dump-${service}-$$"
  docker run -d --name "$temp" --network none -v "$old":/var/lib/postgresql "$PG18_IMAGE" >/dev/null
  ready "$temp" "$user" "$db" || { echo "$service: PostgreSQL 18 did not start for the dump" >&2; exit 1; }
  docker exec "$temp" pg_dump -U "$user" -d "$db" -Fc > "$work/$service.dump"
  docker exec -i "$temp" psql -U "$user" -d "$db" -At -v ON_ERROR_STOP=1 <<<"$COUNT_SQL" > "$work/$service.before"
  docker rm -f "$temp" >/dev/null; temp=""
  [[ -s "$work/$service.dump" ]] || { echo "$service: empty dump" >&2; exit 1; }
  cp "$work/$service.dump" "$KEEP_DIR/postgres18-${service}-${STAMP}.dump"
  echo "$service: restoring into PostgreSQL 19"
  docker exec "$dest" psql -U "$user" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" -c "CREATE DATABASE \"$db\" OWNER \"$user\"" >/dev/null
  if ! docker exec -i "$dest" pg_restore -U "$user" -d "$db" --no-owner --role="$user" --exit-on-error < "$work/$service.dump"; then
    echo "$service: restore failed; PostgreSQL 18 volume $old is untouched" >&2
    exit 1
  fi
  docker exec "$dest" psql -U "$user" -d "$db" -At -v ON_ERROR_STOP=1 <<<"$COUNT_SQL" > "$work/$service.after"
  if ! diff -u "$work/$service.before" "$work/$service.after"; then
    echo "$service: row counts differ after restore; PostgreSQL 18 data is untouched in $old" >&2
    exit 1
  fi
  docker exec "$dest" vacuumdb -U "$user" -d "$db" --analyze-only --quiet
  docker exec "$dest" sh -c "echo moved > $MARKER"
  docker rm -f "$dest" >/dev/null
  dest=""
  echo "$service: moved to PostgreSQL 19 ($(wc -l < "$work/$service.after") tables, row counts match). Dump kept: $KEEP_DIR/postgres18-${service}-${STAMP}.dump. Volume $old was not deleted."
}

SPEC="${PG19_UPGRADE_SPEC:-db:postgres18_data:postgres19_data:vpnshop:vpnshop,support_db:support_postgres18_data:support_postgres19_data:support:support}"
IFS=',' read -ra entries <<<"$SPEC"
for entry in "${entries[@]}"; do
  IFS=':' read -r service old_volume new_volume user db extra <<<"$entry"
  [[ -z "${extra:-}" && "$service" =~ ^[a-z0-9_-]+$ && "$old_volume" =~ ^[a-z0-9_-]+$ && "$new_volume" =~ ^[a-z0-9_-]+$ && "$user" =~ ^[A-Za-z0-9_]+$ && "$db" =~ ^[A-Za-z0-9_]+$ ]] || { echo "Bad PG19_UPGRADE_SPEC entry: $entry" >&2; exit 2; }
  move "$service" "$old_volume" "$new_volume" "$user" "$db"
done
if (( stopped )); then
  docker compose down --remove-orphans
fi
echo "PostgreSQL 19 check finished"
