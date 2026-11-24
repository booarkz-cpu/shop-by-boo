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
# Existing destination relations are never overwritten.
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

free_bytes(){ df -B1 -P "${1:-$work}" | awk 'NR==2 {print $4}'; }

password_of(){
  docker compose config --format json | python3 -c 'import json,sys
svc=sys.argv[1]
env=(json.load(sys.stdin).get("services") or {}).get(svc,{}).get("environment") or {}
if isinstance(env, list):
    env=dict(item.split("=",1) for item in env if "=" in item)
print(env.get("POSTGRES_PASSWORD",""))' "$1"
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
  [[ "$old" != "$new" ]] || { echo "$service: source and destination volumes must differ" >&2; exit 2; }
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
    echo "$service: PostgreSQL 18 volume $old is intact for rollback (version marker only; recovery not verified)"
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
    local target_version
    target_version="$(docker run --rm --entrypoint cat -v "$new":/new:ro "$PG19_IMAGE" /new/19/docker/PG_VERSION 2>/dev/null || true)"
    if [[ "$target_version" != "19" ]]; then
      echo "$service: migration marker exists but destination PG_VERSION is not 19 (\x27$target_version\x27). Refusing to skip migration." >&2
      exit 1
    fi
    echo "$service: already moved to PostgreSQL 19 (version marker verified; recovery not verified)"
    return 0
  fi
  local source_bytes
  source_bytes="$(docker run --rm --entrypoint du -v "$old":/old:ro "$PG18_IMAGE" -sb /old | awk '{print $1}')"
  avail="$(free_bytes)"
  local keep_avail
  keep_avail="$(free_bytes "$KEEP_DIR")"
  [[ "$source_bytes" =~ ^[0-9]+$ && "$avail" =~ ^[0-9]+$ && "$keep_avail" =~ ^[0-9]+$ ]] || { echo "$service: cannot determine storage capacity" >&2; exit 1; }
  if (( avail < source_bytes || keep_avail < source_bytes )); then
    echo "$service: not enough free space for the dump (have $avail, source $source_bytes). No data was moved." >&2
    exit 1
  fi
  # The temporary dump and retained backup coexist until cleanup.
  # When both directories share a filesystem, reserve space for both.
  local work_device keep_device
  work_device="$(stat -c %d "$work")"
  keep_device="$(stat -c %d "$KEEP_DIR")"
  if [[ "$work_device" == "$keep_device" ]] && (( avail / 2 < source_bytes )); then
    echo "$service: insufficient shared filesystem capacity for dump and backup" >&2
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
  local target_avail
  target_avail="$(docker exec "$dest" df -Pk /var/lib/postgresql | awk 'NR==2 {print $4}')"
  [[ "$target_avail" =~ ^[0-9]+$ ]] || { echo "$service: cannot determine destination capacity" >&2; exit 1; }
  if (( target_avail < (source_bytes + 1023) / 1024 )); then
    echo "$service: insufficient destination storage" >&2; exit 1
  fi
  local rows
  # Statistics are estimates, not a safe guard for a destructive restore.
  # Refuse any existing user relation, including migration metadata and empty tables.
  rows="$(docker exec "$dest" psql -U "$user" -d "$db" -At -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp_%' AND c.relkind IN ('r','p','v','m','S','f')")"
  [[ "$rows" =~ ^[0-9]+$ ]] || { echo "$service: cannot establish destination state" >&2; exit 1; }
  if [[ "${rows:-0}" != "0" ]]; then
    echo "$service: PostgreSQL 19 already contains ${rows} user relations before the move." >&2
    echo "Existing destination data will not be overwritten. Use a separate empty destination volume." >&2
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
  keep_avail="$(free_bytes "$KEEP_DIR")"
  local dump_bytes
  dump_bytes="$(wc -c < "$work/$service.dump" | tr -d '[:space:]')"
  [[ "$keep_avail" =~ ^[0-9]+$ && "$dump_bytes" =~ ^[0-9]+$ ]] && (( keep_avail >= dump_bytes )) || { echo "$service: insufficient rollback storage" >&2; exit 1; }
  local backup
  backup="$(mktemp "$KEEP_DIR/postgres18-${service}-${STAMP}-XXXXXX.dump")"
  cp "$work/$service.dump" "$backup"
  cmp -s "$work/$service.dump" "$backup" || { echo "$service: backup verification failed" >&2; exit 1; }
  echo "$service: restoring into PostgreSQL 19"
  if ! docker exec -i "$dest" pg_restore -U "$user" -d "$db" --no-owner --role="$user" --single-transaction --exit-on-error < "$work/$service.dump"; then
    echo "$service: restore failed; PostgreSQL 18 volume $old is untouched" >&2
    exit 1
  fi
  docker exec -i "$dest" psql -U "$user" -d "$db" -At -v ON_ERROR_STOP=1 <<<"$COUNT_SQL" > "$work/$service.after"
  if ! diff -u "$work/$service.before" "$work/$service.after"; then
    echo "$service: row counts differ after restore; PostgreSQL 18 data is untouched in $old" >&2
    exit 1
  fi
  docker exec "$dest" vacuumdb -U "$user" -d "$db" --analyze-only --quiet
  docker exec "$dest" sh -c "echo moved > $MARKER"
  docker rm -f "$dest" >/dev/null
  dest=""
  echo "$service: moved to PostgreSQL 19 ($(wc -l < "$work/$service.after") tables, row counts match). Dump kept: $backup. Volume $old was not deleted."
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
