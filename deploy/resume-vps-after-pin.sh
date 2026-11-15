#!/usr/bin/env bash
# Layout stage 4: the script lives in infrastructure/deployment/. This file keeps the old path working —
# installed servers (scripts/update.sh of an older release), older instructions and bookmarks call deploy/resume-vps-after-pin.sh.
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/infrastructure/deployment/resume-vps-after-pin.sh" "$@"
