#!/usr/bin/env bash
# Build the production images, each Dockerfile once.
#
#   bash scripts/compose-build.sh          # fresh: --pull --no-cache (default of deploy and install)
#   bash scripts/compose-build.sh cached   # --pull, reuse layers
#
# backend, worker and mail_receiver share backend/Dockerfile and its context. A plain
# `docker compose build --no-cache` ran that whole build (apt, PostgreSQL client, pip) three
# times; here the backend image is built fresh once and the other two are served from its
# layers. Every other service is built as before.
set -Eeuo pipefail
mode="${1:-fresh}"
flags=(--pull)
[[ "$mode" == "fresh" ]] && flags+=(--no-cache)
fresh=(); shared=()
while IFS= read -r service; do
  case "$service" in
    worker|mail_receiver) shared+=("$service") ;;
    *) fresh+=("$service") ;;
  esac
done < <(docker compose config --services)
docker compose build "${flags[@]}" "${fresh[@]}"
if [[ ${#shared[@]} -gt 0 ]]; then
  docker compose build "${shared[@]}"
fi
