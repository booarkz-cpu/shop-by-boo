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
REPORT="$ROOT/screenshots/mobile/maestro/report.xml"
status=0
# Screenshots of takeScreenshot land in the test output folder.
maestro test --format junit --output "$REPORT" --test-output-dir "$ROOT/screenshots/mobile/maestro" flows/ || status=$?
if [[ $status -ne 0 ]]; then
  # CI emulators sometimes stall on the first cold starts: the whole suite gets one more try.
  echo "Maestro failed once; retrying the flows" >&2
  status=0
  maestro test --format junit --output "$REPORT" --test-output-dir "$ROOT/screenshots/mobile/maestro" flows/ || status=$?
fi
ls -1 "$ROOT/screenshots/mobile/maestro"
if [[ $status -ne 0 ]] && command -v adb >/dev/null; then
  # What the emulator showed and why: the top activity and crashes reach the run's annotations.
  adb shell dumpsys activity activities 2>/dev/null | grep -m3 -E "mResumedActivity|topResumedActivity" | sed 's/^ */::error title=Maestro top activity::/' || true
  adb logcat -d -b crash 2>/dev/null | head -30 | tr '\n' ' ' | cut -c1-900 | sed 's/^/::error title=Maestro crash log::/' || true
  adb logcat -d 2>/dev/null | grep -E "AndroidRuntime|FATAL|ANR in|shop.remnawave" | tail -15 | sed 's/^/::warning title=Maestro logcat::/' || true
fi
if [[ $status -ne 0 && -f "$REPORT" ]]; then
  # CI logs are not always readable: surface each failing flow as an annotation.
  python3 - "$REPORT" <<'PY'
import sys, xml.etree.ElementTree as ET
for case in ET.parse(sys.argv[1]).getroot().iter("testcase"):
    for failure in list(case.findall("failure")) + list(case.findall("error")):
        text = " ".join((failure.get("message") or failure.text or "").split())[:900]
        print(f"::error title=Maestro {case.get('name')}::{text}")
PY
fi
exit $status
