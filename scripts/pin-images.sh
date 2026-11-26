#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="${APP_DIR:-/opt/vpn-shop}"
cd "$APP_DIR"
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 2; }
umask 077

# Install the exact multi-platform image that this release was tested with.
release_image() {
  local key="$1" image installed
  image="$(sed -nE '/^[[:space:]]*#/d; s/.*[$][{]'"$key"':-([^}]+)[}].*/\1/p' docker-compose.yml | sort -u)"
  [[ "$image" =~ ^[a-z0-9./_:-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$ ]] || {
    echo "No immutable digest for $key in docker-compose.yml" >&2
    return 1
  }
  docker pull "$image" >/dev/null || return 1
  installed="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$image")" || return 1
  grep -Eq "@${image##*@}$" <<<"$installed" || {
    echo "No immutable digest matching $image in the local image store" >&2
    return 1
  }
  printf '%s\n' "$image"
}

pins="$(mktemp .env.images.XXXXXX)"
tmp=""
trap 'rm -f -- "$pins" "$tmp"' EXIT
for key in REDIS_IMAGE POSTGRES_IMAGE CADDY_IMAGE PYTHON_BASE_IMAGE NODE_BASE_IMAGE NGINX_BASE_IMAGE; do
  image="$(release_image "$key")"
  printf '%s=%s\n' "$key" "$image" >> "$pins"
done

# Compose reads .env automatically. Replace only the six release image settings.
if [[ -f .env ]]; then
  tmp="$(mktemp .env.pins.XXXXXX)"
  awk '!/^(REDIS_IMAGE|POSTGRES_IMAGE|CADDY_IMAGE|PYTHON_BASE_IMAGE|NODE_BASE_IMAGE|NGINX_BASE_IMAGE)=/' .env > "$tmp"
  cat "$pins" >> "$tmp"
fi
mv -f -- "$pins" .env.images
if [[ -n "$tmp" ]]; then mv -f -- "$tmp" .env; fi
printf 'Pinned images written to %s/.env.images and .env\n' "$APP_DIR"
