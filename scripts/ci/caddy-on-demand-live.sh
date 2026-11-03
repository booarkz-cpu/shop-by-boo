#!/usr/bin/env bash
# v28.67.0 (stage 11): the real deploy/Caddyfile in the pinned Caddy image gives a portal domain of the Domain
# Manager a certificate on demand and refuses any other name (tests/live/test_caddy_on_demand.py).
set -Eeuo pipefail
cd "${GITHUB_WORKSPACE:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel)}"
CADDY_IMAGE="$(sed -n 's/^ARG CADDY_BASE_IMAGE=//p' deploy/caddy/Dockerfile)"
docker pull -q "$CADDY_IMAGE" >/dev/null
CADDY_LIVE=1 CADDY_IMAGE="$CADDY_IMAGE" python -m pytest -q -s -rfE tests/live/test_caddy_on_demand.py -p no:cacheprovider
