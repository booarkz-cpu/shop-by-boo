#!/usr/bin/env bash
# Layout stage 4: the script lives in infrastructure/deployment/. This file keeps the old path working —
# installed servers (scripts/update.sh of an older release), older instructions and bookmarks call deploy/install-status.sh.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/infrastructure/deployment/install-status.sh"
