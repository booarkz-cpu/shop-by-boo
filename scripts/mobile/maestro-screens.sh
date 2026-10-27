#!/usr/bin/env bash
# Walk the customer app with Maestro and save screenshots (mobile/maestro/flows/*.yaml).
#
#   bash scripts/mobile/maestro-screens.sh   # needs a running emulator with the debug build installed
#
# Install Maestro once: curl -fsSL https://get.maestro.mobile.dev | bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PATH="$HOME/.maestro/bin:$PATH"
command -v maestro >/dev/null || { echo "Maestro is not installed: curl -fsSL https://get.maestro.mobile.dev | bash" >&2; exit 1; }
mkdir -p "$ROOT/screenshots/mobile/maestro"
cd "$ROOT/mobile/maestro"
maestro test --format junit --output "$ROOT/screenshots/mobile/maestro/report.xml" flows/
ls -1 "$ROOT/screenshots/mobile/maestro"
