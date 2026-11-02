#!/usr/bin/env bash
# Move REDIS_IMAGE and CADDY_IMAGE pinned in .env / .env.images to the versions this release ships (v28.64.0).
#
# scripts/pin-images.sh writes immutable digests into .env, and .env overrides the defaults of
# docker-compose.yml. Without this step an update would keep running the image the install was pinned to
# (for example Redis 7.4 after the release moved to Redis 8.10). Only the image name and tag are compared:
# the same tag keeps its digest, another tag is replaced by the release default (tag + digest).
#
# KEEP_PINNED_IMAGES=1 keeps the owner's pins untouched (an image chosen on purpose).
# Redis reads the data of older versions (AOF/RDB); after it writes them, an older Redis cannot read them
# back. The shop keeps only short-lived state in Redis (locks, rate limits, one-time tickets), so a
# rollback starts the old Redis on an empty volume if needed: docker volume rm <project>_redis_data.
set -Eeuo pipefail
APP_DIR="${APP_DIR:-/opt/vpn-shop}"
cd "$APP_DIR"
[[ "${KEEP_PINNED_IMAGES:-0}" == 1 ]] && { echo "KEEP_PINNED_IMAGES=1: pinned images left as they are"; exit 0; }
[[ -f docker-compose.yml ]] || { echo "docker-compose.yml not found in $APP_DIR" >&2; exit 2; }

repin(){
  local key="$1" default file value
  default="$(sed -nE "s/.*\\\$\\{${key}:-([^}]+)\\}.*/\\1/p" docker-compose.yml | head -1)"
  [[ "$default" =~ ^[a-z0-9./_-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$ ]] || { echo "docker-compose.yml has no pinned default for $key" >&2; exit 2; }
  for file in .env .env.images; do
    [[ -f "$file" ]] || continue
    value="$(sed -nE "s/^${key}=(.*)$/\\1/p" "$file" | tail -1)"
    [[ -n "$value" ]] || continue
    # Same name:tag (digest pinned by pin-images.sh on this server) — nothing to do.
    [[ "${value%%@*}" == "${default%%@*}" ]] && continue
    # A bare digest without a tag (redis@sha256:…) cannot be compared: leave it and say so.
    if [[ "${value%%@*}" != *:* ]]; then
      echo "$file: $key=${value%%@*}@… has no tag; left as is (set ${default%%@*} by hand or run scripts/pin-images.sh)"
      continue
    fi
    sed -i -E "s|^${key}=.*$|${key}=${default}|" "$file"
    echo "$file: $key ${value%%@*} -> ${default%%@*}"
  done
}
repin REDIS_IMAGE
repin CADDY_IMAGE
