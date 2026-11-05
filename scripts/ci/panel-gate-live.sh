#!/usr/bin/env bash
# v28.79.0 (stage 18): «Вход через магазин» — the wizard's Caddyfile in the pinned Caddy image asks the shop's
# panel_gate router (tests/live/test_panel_gate_live.py).
set -Eeuo pipefail
cd "${GITHUB_WORKSPACE:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel)}"
GATE_LIVE=1 python -m pytest -q -s -rfE tests/live/test_panel_gate_live.py -p no:cacheprovider
