#!/usr/bin/env bash
# v28.79.0 (stage 18): the wizard's TinyAuth files with the real TinyAuth and Caddy images
# (tests/live/test_tinyauth_live.py).
set -Eeuo pipefail
cd "${GITHUB_WORKSPACE:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel)}"
TINYAUTH_LIVE=1 python -m pytest -q -s -rfE tests/live/test_tinyauth_live.py -p no:cacheprovider
