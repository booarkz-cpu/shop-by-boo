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
for attempt in 2 3; do
  [[ $status -eq 0 ]] && break
  # CI emulators sometimes stall on cold starts («failed to attach»): warm the app up again and give the whole
  # suite another try (two at most), so a slow emulator does not fail the job while a real regression still does.
  echo "Maestro failed; warm-up and attempt $attempt" >&2
  if command -v adb >/dev/null; then
    adb shell am force-stop shop.remnawave.user.preview || true
    adb shell am start -W -n shop.remnawave.user.preview/shop.remnawave.user.MainActivity --ez corgi_demo true >/dev/null 2>&1 || true
    sleep 10
    adb shell am force-stop shop.remnawave.user.preview || true
  fi
  status=0
  maestro test --format junit --output "$REPORT" --test-output-dir "$ROOT/screenshots/mobile/maestro" flows/ || status=$?
done
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
