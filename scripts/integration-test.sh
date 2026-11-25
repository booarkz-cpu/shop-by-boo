#!/usr/bin/env bash
# Test the tracked working tree in a private Compose project on the local Docker engine.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
endpoint="${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}' "$(docker context show)")}"
case "$endpoint" in
  unix://*|npipe://*) ;;
  *) echo "Integration tests require a local Docker socket." >&2; exit 1 ;;
esac

work="$(mktemp -d "${TMPDIR:-/tmp}/corgi-integration.XXXXXXXX")"
project="corgi-integration-$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
engine=(env -i "HOME=$HOME" "PATH=$PATH" "DOCKER_HOST=$endpoint")
if [[ -n "${DOCKER_CONFIG:-}" ]]; then engine+=("DOCKER_CONFIG=$DOCKER_CONFIG"); fi
engine+=(docker)
compose=("${engine[@]}" compose --project-name "$project" --profile integration-tests --env-file .env -f docker-compose.yml -f docker-compose.integration.yml)
started=0
cleanup() {
  local status=$?
  trap - EXIT
  if (( started )); then "${compose[@]}" down --volumes --rmi local || status=1; fi
  rm -rf -- "$work"
  exit "$status"
}
trap cleanup EXIT

# Clone only tracked content; replay tracked edits for the ordinary pre-commit workflow.
# The caller's ignored .env files, uploads and control directory stay outside the backend mount.
base="$(git -C "$ROOT" rev-parse HEAD)"
(umask 022; git -c advice.detachedHead=false clone --quiet --local --no-hardlinks "$ROOT" "$work/source")
cd "$work/source"
git -c advice.detachedHead=false checkout -q --detach "$base"
git -C "$ROOT" diff --binary "$base" -- | git apply --allow-empty -
python3 - <<'PY'
import os
import secrets
from pathlib import Path

os.umask(0o077)
text = Path(".env.test.example").read_text()
for placeholder in ("CHANGE_ME_DB_PASSWORD", "CHANGE_ME_APP_SECRET_AT_LEAST_32_CHARS", "CHANGE_ME_ADMIN_PASSWORD"):
    text = text.replace(placeholder, secrets.token_hex(32))
text = text.replace("REDIS_PASSWORD=\n", f"REDIS_PASSWORD={secrets.token_hex(32)}\n")
for name in ("SUPPORT_PRO_DB_PASSWORD", "SUPPORT_PRO_SSO_SECRET", "SUPPORT_REDIS_PASSWORD"):
    text += f"\n{name}={secrets.token_hex(32)}"
Path(".env").write_text(text + "\nSUPPORT_PRO_DOMAIN=support.example.test\nINTEGRATION_API_PORT=\n")
Path("support-pro/.env").write_text("")
PY

# Refuse to adopt either running or stopped resources. Register teardown before 'up'
# so that it also handles partial starts, but never a stack discovered on the daemon.
for kind in container network volume; do
  args=("$kind" ls -q --filter "label=com.docker.compose.project=$project")
  if [[ "$kind" == container ]]; then args+=(-a); fi
  existing="$("${engine[@]}" "${args[@]}")"
  [[ -z "$existing" ]] || { echo "Integration project name already in use." >&2; exit 1; }
done

"${compose[@]}" config --quiet
started=1
"${compose[@]}" build backend worker
"${compose[@]}" up -d --wait --wait-timeout 240 db redis backend worker
"${compose[@]}" exec -T backend alembic current --check-heads
address="$("${compose[@]}" port backend 8000)"
[[ "$address" =~ ^127\.0\.0\.1:[0-9]+$ ]]
curl --fail --max-time 10 "http://$address/health" >/dev/null
# The suite can recreate tables. Give it a separate database from the API and worker.
"${compose[@]}" exec -T db createdb -U vpnshop integration_pytest
"${compose[@]}" run --rm --build --no-deps -T --workdir /app --entrypoint alembic integration_tests upgrade head
"${compose[@]}" run --rm --no-deps -T integration_tests "$@"
printf 'Integration smoke test passed.\n'
