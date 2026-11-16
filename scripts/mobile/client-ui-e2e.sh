#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
# The tunnel probes can outlast Android's screen timeout. Semantic clicks still work on a
# sleeping display, but clipboard access needs a focused foreground window.
adb shell settings put system screen_off_timeout 1800000
adb shell svc power stayon true
adb shell input keyevent KEYCODE_WAKEUP
adb shell wm dismiss-keyguard
bash scripts/mobile/client-vpn-e2e.sh apps/vpn-client/android/app/build/outputs/apk/debug/app-debug.apk "$RUNNER_TEMP/xray/xray"
cd apps/vpn-client/android
timeout 25m bash gradlew :app:connectedDebugAndroidTest --no-daemon || {
  adb shell dumpsys power | grep -E 'Wakefulness|Display Power|mWakefulness' || true
  adb shell dumpsys window | grep -E 'mCurrentFocus|mFocusedApp|mDreamingLockscreen|mShowingLockscreen' || true
  adb logcat -d | grep -E "TestRunner.{2}(started|finished|failed)" | tail -n 40 || true
  adb logcat -d | grep -E "ActivityTaskManager|ActivityManager|AndroidRuntime|corgi|TestRunner|ActivityScenario" | tail -n 120 || true
  exit 1
}
adb pull /data/local/tmp/client-screens "$GITHUB_WORKSPACE/client-screens" || echo "no screens"
