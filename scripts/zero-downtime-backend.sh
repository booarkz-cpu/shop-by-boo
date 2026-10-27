#!/usr/bin/env bash
# Zero-downtime backend switch, run by deploy/build-production.sh during an update.
#
# 1. The new release starts as `backend_standby` (same image, own ingress address) next to the running backend.
# 2. Nothing else changes until the standby answers /health/ready with 200; if it never does, it is removed
#    and the old backend keeps serving untouched (the update then fails and update.sh rolls back).
# 3. `backend` is recreated on the new image. Caddy (deploy/Caddyfile, backend_lb) prefers `backend` and sends
#    requests to the standby while it restarts; requests that could not be delivered are retried for 20 s.
# 4. When the new `backend` answers 200 the standby is stopped and removed.
#
# Database migrations run in the standby first (entrypoint: alembic upgrade head), so they must stay
# backward compatible with the release being replaced (expand → migrate → contract), as all migrations here do.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
TIMEOUT="${ZERO_DOWNTIME_TIMEOUT:-240}"
compose() { docker compose --profile standby "$@"; }

ready() {
  compose exec -T "$1" python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=3)' >/dev/null 2>&1
}

wait_ready() {
  local service="$1" waited=0
  until ready "$service"; do
    sleep 3; waited=$((waited + 3))
    if (( waited >= TIMEOUT )); then return 1; fi
  done
}

drop_standby() { compose stop -t 30 backend_standby >/dev/null 2>&1 || true; compose rm -fsv backend_standby >/dev/null 2>&1 || true; }

if ! docker compose ps --status running --services 2>/dev/null | grep -qx backend; then
  echo "zero-downtime: no running backend (first install); a regular start is enough"
  exit 0
fi

echo "zero-downtime: starting the new release as backend_standby"
compose build backend_standby
compose up -d --no-deps --force-recreate backend_standby
if ! wait_ready backend_standby; then
  compose logs --tail=120 backend_standby >&2 || true
  drop_standby
  echo "zero-downtime: the new release did not answer /health/ready; the running backend was not touched" >&2
  exit 1
fi
echo "zero-downtime: standby answers 200; recreating backend (traffic goes to the standby meanwhile)"
docker compose up -d --no-deps backend
if ! wait_ready backend; then
  compose logs --tail=120 backend >&2 || true
  echo "zero-downtime: the recreated backend is not ready; the standby keeps serving until the rollback" >&2
  exit 1
fi
drop_standby
echo "zero-downtime: done, backend serves the new release"
