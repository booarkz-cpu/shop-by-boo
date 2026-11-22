#!/usr/bin/env bash
# Read-only inventory before a PostgreSQL 18 -> 19 migration.
# This script deliberately does not stop containers, start databases or change volumes.
set -Eeuo pipefail
APP_DIR="${APP_DIR:-/opt/vpn-shop}"
cd "$APP_DIR"
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 2; }
command -v python3 >/dev/null || { echo "Python 3 is required" >&2; exit 2; }
project="$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
[[ "$project" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "Invalid Compose project name" >&2; exit 2; }
services="$(docker compose config --services)"
spec="${PG19_PREFLIGHT_SPEC:-db:postgres18_data:postgres19_data,support_db:support_postgres18_data:support_postgres19_data}"
status=0
IFS=',' read -ra entries <<<"$spec"
[[ -n "$spec" && "$spec" != ,* && "$spec" != *, && "$spec" != *,,* ]] || { echo "Invalid PG19_PREFLIGHT_SPEC: empty entry" >&2; exit 2; }
# Validate the entire specification before querying any volumes. In particular,
# reject reused source/target names and cross-entry collisions.
declare -A seen_volumes=()
for entry in "${entries[@]}"; do
  IFS=':' read -r service source target extra <<<"$entry"
  if [[ -n "${extra:-}" || ! "$service" =~ ^[a-z0-9_-]+$ || ! "$source" =~ ^[a-z0-9_-]+$ || ! "$target" =~ ^[a-z0-9_-]+$ || "$source" == "$target" ]]; then
    echo "Invalid PG19_PREFLIGHT_SPEC entry: $entry" >&2
    exit 2
  fi
  for volume in "$source" "$target"; do
    if [[ -n "${seen_volumes[$volume]:-}" ]]; then
      echo "Invalid PG19_PREFLIGHT_SPEC: reused volume $volume" >&2
      exit 2
    fi
    seen_volumes[$volume]=1
  done
done
for entry in "${entries[@]}"; do
  IFS=':' read -r service source target extra <<<"$entry"
  if ! grep -qx "$service" <<<"$services"; then
    echo "$service: not present in this Compose profile; preflight cannot validate this entry" >&2
    status=1
    continue
  fi
  old="${project}_${source}"
  new="${project}_${target}"
  if ! docker volume inspect "$old" >/dev/null 2>&1; then
    echo "$service: source volume $old missing (fresh install or incorrect project)"
    status=1
    continue
  fi
  # docker volume inspect alone cannot prove PG_VERSION or backup integrity.
  # Do not mount or start an unknown data directory merely for preflight.
  echo "$service: source volume $old exists; verify PG_VERSION=18 and take a tested offline backup"
  if docker volume inspect "$new" >/dev/null 2>&1; then
    echo "$service: target volume $new already exists; inspect before any migration"
    status=1
  else
    echo "$service: target volume $new absent"
  fi
done
echo "Read-only preflight complete. No data migrated. Verify backup restore, extensions, clients and rollback before cutover."
exit "$status"
