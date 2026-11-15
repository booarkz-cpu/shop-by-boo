#!/usr/bin/env bash
# Continue an install that stopped at pin-images.sh, without replacing credentials.
set -Eeuo pipefail
ROOT="${APP_DIR:-/opt/vpn-shop}"
export APP_DIR="$ROOT"
cd "$ROOT"
[[ $EUID -eq 0 ]] || { echo "Run with sudo" >&2; exit 1; }
[[ -f .env && -f support-pro/.env && -f docker-compose.yml ]] || {
  echo "Expected a partial install with .env, support-pro/.env and docker-compose.yml in $ROOT" >&2
  exit 1
}
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 1; }
umask 077

bash scripts/pin-images.sh
resolve_build() {
  local image="$1" digest
  docker pull "$image" >/dev/null
  digest="$(docker image inspect "$image" --format '{{index .RepoDigests 0}}')"
  [[ "$digest" =~ ^[^[:space:]]+@sha256:[0-9a-f]{64}$ ]] || { echo "No digest for $image" >&2; exit 1; }
  printf '%s' "$digest"
}
PYTHON_BASE_IMAGE="$(resolve_build python:3.14-slim)"
NODE_BASE_IMAGE="$(resolve_build node:26-alpine)"
NGINX_BASE_IMAGE="$(resolve_build nginx:1.30-alpine)"
temp_env="$(mktemp "$ROOT/.env.resume.XXXXXX")"
trap 'rm -f "$temp_env"' EXIT
awk '!/^(PYTHON_BASE_IMAGE|NODE_BASE_IMAGE|NGINX_BASE_IMAGE)=/' .env > "$temp_env"
printf 'PYTHON_BASE_IMAGE=%s\nNODE_BASE_IMAGE=%s\nNGINX_BASE_IMAGE=%s\n' \
  "$PYTHON_BASE_IMAGE" "$NODE_BASE_IMAGE" "$NGINX_BASE_IMAGE" >> "$temp_env"
chmod 600 "$temp_env"
mv "$temp_env" .env

docker compose config --quiet
docker compose build --pull --no-cache
docker compose up -d
ready=0
for _ in {1..80}; do
  if docker compose exec -T backend python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=3)' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 3
done
if [[ "$ready" != 1 ]]; then
  docker compose ps >&2 || true
  docker compose logs --tail=120 backend worker >&2 || true
  echo "API did not become ready" >&2
  exit 1
fi
for svc in admin miniapp cabinet; do
  ready=0
  for _ in {1..15}; do
    if docker compose exec -T "$svc" curl -fsS http://127.0.0.1/ >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  [[ "$ready" == 1 ]] || { docker compose logs --tail=80 "$svc" >&2 || true; exit 1; }
done
docker compose exec -T support_pro python -m app.cli init
docker compose ps
printf 'Install resumed. Existing credentials remain in %s/.env and %s/support-pro/.env\n' "$ROOT" "$ROOT"
