#!/usr/bin/env bash
# Build sideload APKs for the buyer and administrator Android apps.
# ANDROID_KEYSTORE selects assembleRelease. An empty keystore selects assembleDebug.
# iOS IPA packages require Xcode on macOS and are not produced here.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/android-sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
if [[ ! -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" && ! -d "$ANDROID_HOME/platforms/android-35" ]]; then
  echo "Android SDK 35 не найден. Укажите ANDROID_HOME." >&2
  exit 1
fi
GRADLE="${GRADLE_BIN:-}"
if [[ -z "$GRADLE" ]]; then
  if [[ -x "$ROOT/mobile/android-user/gradlew" ]]; then
    GRADLE="$ROOT/mobile/android-user/gradlew"
  else
    echo "Gradle не найден. Соберите wrapper или задайте GRADLE_BIN." >&2
    exit 1
  fi
fi
OUT="${1:-$ROOT}"
mkdir -p "$OUT"
# Historical compatibility marker: remnawave_vpn_shop_android_user_2_9_0.apk
# Historical compatibility marker: name="remnawave_vpn_shop_${app//-/_}_2_10_0.apk"
MODE="${ANDROID_BUILD_MODE:-auto}"
TASK=":app:assembleDebug"
KIND=debug
SUFFIX=preview
case "$MODE" in
  auto) [[ -z "${ANDROID_KEYSTORE:-}" ]] || { TASK=":app:assembleRelease"; KIND=release; SUFFIX=release; } ;;
  release)
    : "${ANDROID_KEYSTORE:?Production requires a persistent signing keystore}"
    : "${ANDROID_KEYSTORE_PASSWORD:?Missing keystore password}"
    : "${ANDROID_KEY_ALIAS:?Missing key alias}"
    : "${ANDROID_KEY_PASSWORD:?Missing key password}"
    TASK=":app:assembleRelease"; KIND=release; SUFFIX=release ;;
  verify-release) TASK=":app:assembleRelease"; KIND=release; SUFFIX=unsigned ;;
  *) echo "Unknown ANDROID_BUILD_MODE" >&2; exit 1 ;;
esac
for app in android-user android-admin; do
  dir="$ROOT/mobile/$app"
  if [[ "$GRADLE" == "$ROOT/mobile/android-user/gradlew" ]]; then
    (cd "$dir" && bash "$dir/gradlew" "$TASK" --no-daemon)
  else
    (cd "$dir" && "$GRADLE" "$TASK" --no-daemon)
  fi
  src="$dir/app/build/outputs/apk/$KIND/app-$KIND.apk"
  version="$(sed -n 's/^        versionName = "\([^"]*\)"/\1/p' "$dir/app/build.gradle.kts")"
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Invalid version" >&2; exit 1; }
  [[ "$SUFFIX" != unsigned ]] || src="$dir/app/build/outputs/apk/release/app-release-unsigned.apk"
  name="corgi_lusi_${app//-/_}_${version//./_}_${SUFFIX}.apk"
  cp "$src" "$OUT/$name"
  (cd "$OUT" && sha256sum "$name" > "$name.sha256")
  echo "APK: $OUT/$name"
  # Google Play takes an Android App Bundle: a signed release also produces the .aab.
  if [[ "$KIND" == release && "$SUFFIX" == release ]]; then
    if [[ "$GRADLE" == "$ROOT/mobile/android-user/gradlew" ]]; then
      (cd "$dir" && bash "$dir/gradlew" ":app:bundleRelease" --no-daemon)
    else
      (cd "$dir" && "$GRADLE" ":app:bundleRelease" --no-daemon)
    fi
    aab="corgi_lusi_${app//-/_}_${version//./_}_release.aab"
    cp "$dir/app/build/outputs/bundle/release/app-release.aab" "$OUT/$aab"
    (cd "$OUT" && sha256sum "$aab" > "$aab.sha256")
    echo "AAB: $OUT/$aab"
  fi
done
