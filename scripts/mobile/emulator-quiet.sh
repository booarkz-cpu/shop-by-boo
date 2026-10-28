#!/usr/bin/env bash
# Prepare a CI Android emulator for screenshots and Maestro: wait until the system has fully booted, let the
# launcher settle, and hide crash/ANR dialogs of other apps («Pixel Launcher isn't responding» used to cover the
# app on every screenshot and failed Maestro asserts). Safe to call again before each screenshot:
#
#   bash scripts/mobile/emulator-quiet.sh          # once after boot
#   bash scripts/mobile/emulator-quiet.sh dismiss  # only close a system dialog that is open now
set -uo pipefail
if [[ "${1:-}" != "dismiss" ]]; then
  adb wait-for-device
  for _ in $(seq 1 60); do
    [[ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]] && break
    sleep 2
  done
  # Settings.Global.HIDE_ERROR_DIALOGS: the system keeps crash and ANR dialogs to itself.
  adb shell settings put global hide_error_dialogs 1 || true
  adb shell settings put global anr_show_background 0 || true
  adb shell input keyevent KEYCODE_WAKEUP || true
  adb shell wm dismiss-keyguard || true
  sleep 15   # the launcher finishes its first start before the app takes the foreground
fi
adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS >/dev/null 2>&1 || true
if adb shell uiautomator dump /sdcard/quiet.xml >/dev/null 2>&1 && adb shell cat /sdcard/quiet.xml 2>/dev/null | grep -q "isn't responding\|не отвечает"; then
  # A dialog that slipped through: «Wait» keeps the foreground app as it is.
  adb shell cat /sdcard/quiet.xml | python3 -c '
import re, sys
xml = sys.stdin.read()
m = re.search(r"text=\"(?:Wait|Подождать)\"[^>]*bounds=\"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\"", xml)
if m:
    x1, y1, x2, y2 = map(int, m.groups())
    print((x1 + x2) // 2, (y1 + y2) // 2)' | while read -r x y; do adb shell input tap "$x" "$y"; sleep 1; done
fi
exit 0
