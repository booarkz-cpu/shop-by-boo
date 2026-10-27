#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f .env ]] || { echo "Missing .env. Run deploy/install-vps.sh first."; exit 2; }
python3 scripts/harden-env.py
bash scripts/preflight.sh
if command -v docker >/dev/null 2>&1; then
  if [[ -f .env.images ]]; then set -a; . ./.env.images; set +a; fi
  docker compose config >/dev/null
  # Auto-update agent (scripts/auto_update.py): the .control dir shared with the admin panel must exist before
  # Docker mounts it; a server updated from an older release gets nightly auto-update once (this script is run
  # from the new release, unlike update.sh); an owner's «disable» or the installer's «no» is kept.
  APP_DIR="$ROOT" python3 scripts/auto_update.py ensure || echo "WARNING: auto-update agent not refreshed" >&2
  # Each Dockerfile is built once (scripts/compose-build.sh): backend, worker and mail_receiver share one.
  if [[ "${FULL_REBUILD:-1}" == "1" ]]; then bash scripts/compose-build.sh fresh; else bash scripts/compose-build.sh cached; fi
  # Updates: the new backend must answer 200 next to the old one before the old one is replaced
  # (scripts/zero-downtime-backend.sh). ZERO_DOWNTIME=0 restores the plain restart.
  if [[ "${ZERO_DOWNTIME:-1}" == "1" ]]; then bash scripts/zero-downtime-backend.sh; fi
  docker compose up -d --remove-orphans
  for i in {1..80}; do
    if docker compose exec -T backend python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=3)' >/dev/null 2>&1; then
      for svc in admin miniapp cabinet; do
        docker compose exec -T "$svc" curl -fsS http://127.0.0.1/ >/dev/null || { docker compose logs --tail=80 "$svc" >&2; echo "$svc did not serve HTTP" >&2; exit 1; }
      done
      docker compose ps
      exit 0
    fi
    sleep 3
  done
  docker compose ps
  docker compose logs --tail=120 backend worker
  echo "Backend did not become healthy" >&2
  exit 1
else
  echo "Docker daemon unavailable: static preflight passed; container runtime build skipped." >&2
fi
