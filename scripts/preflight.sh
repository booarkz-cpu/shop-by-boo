#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f .env.images ]]; then set -a; . ./.env.images; set +a; fi
# Host dependencies are not required on a fresh VDS; CI runs the full test suite.
bash -n install.sh deploy/install-docker.sh deploy/install-vps.sh deploy/build-production.sh scripts/update.sh scripts/pin-images.sh scripts/upgrade-postgres.sh
python3 -m compileall -q backend
if command -v docker >/dev/null 2>&1; then if [[ "${REQUIRE_PINNED_IMAGES:-1}" == "1" ]]; then
  [[ -f .env.images ]] || { echo "Missing .env.images: run ./scripts/pin-images.sh before production start." >&2; exit 2; }
  grep -Eq '^REDIS_IMAGE=.*@sha256:' .env.images || { echo "REDIS_IMAGE is not digest-pinned" >&2; exit 2; }
  grep -Eq '^POSTGRES_IMAGE=.*@sha256:' .env.images || { echo "POSTGRES_IMAGE is not digest-pinned" >&2; exit 2; }
  grep -Eq '^CADDY_IMAGE=.*@sha256:' .env.images || { echo "CADDY_IMAGE is not digest-pinned" >&2; exit 2; }
fi
docker compose config --quiet >/dev/null; fi
printf '\nPreflight: PASS (static/runtime-independent checks)\n'
