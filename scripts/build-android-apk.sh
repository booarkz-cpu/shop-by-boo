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
MODE="${ANDROID_BUILD_MODE:-auto}"
# v28.77.0: the shop's API address baked into both apps (CORGI_SHOP_URL wins over mobile/shop-url.txt).
CORGI_SHOP_URL="${CORGI_SHOP_URL:-$(grep -v '^#' "$ROOT/mobile/shop-url.txt" 2>/dev/null | tr -d '[:space:]' | head -c 200 || true)}"
export CORGI_SHOP_URL
[[ -z "$CORGI_SHOP_URL" || "$CORGI_SHOP_URL" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?/?$ ]] || { echo "CORGI_SHOP_URL must be https://host" >&2; exit 1; }
echo "Shop address baked into the apps: ${CORGI_SHOP_URL:-(none — the apps keep the address field)}"
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
# Release packages must be signed with the owner's key: its certificate SHA-256 is kept in the repository
# (mobile/android-signing-cert.sha256, a public value) or given as ANDROID_SIGNING_CERT_SHA256.
EXPECTED_CERT="${ANDROID_SIGNING_CERT_SHA256:-$(grep -v '^#' "$ROOT/mobile/android-signing-cert.sha256" 2>/dev/null | tr -d ' :\n' || true)}"
EXPECTED_CERT="$(printf '%s' "$EXPECTED_CERT" | tr -d ' :' | tr 'A-F' 'a-f')"
verify_signature() {
  local file="$1" kind="$2" got
  [[ -n "$EXPECTED_CERT" ]] || { echo "No expected signing certificate: skipping the check of $file" >&2; return 0; }
  if [[ "$kind" == apk ]]; then
    local signer
    # The build-tools the release workflows install (35.0.0), else the newest present.
    signer="$ANDROID_HOME/build-tools/35.0.0/apksigner"
    [[ -x "$signer" ]] || signer="$(ls -d "$ANDROID_HOME"/build-tools/*/ | sort -V | tail -1)apksigner"
    # --verbose: without it newer apksigner versions print no certificate digests.
    got="$("$signer" verify --verbose --print-certs "$file" | sed -n 's/^Signer[^:]*certificate SHA-256 digest: //p' | head -1)"
  else
    # An Android App Bundle carries a JAR signature.
    jarsigner -verify "$file" >/dev/null
    got="$(keytool -printcert -jarfile "$file" | sed -n 's/^[[:space:]]*SHA256: //p' | head -1 | tr -d ':' | tr 'A-F' 'a-f')"
  fi
  if [[ "$got" != "$EXPECTED_CERT" ]]; then
    echo "Signing certificate of $(basename "$file") is ${got:-missing}, expected $EXPECTED_CERT" >&2
    exit 1
  fi
  echo "Signed with the expected key: $(basename "$file")"
}
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
  # Google Play takes an Android App Bundle: every release build also produces the .aab
  # (signed with the release key, or unsigned for signing later in Play Console / by the owner).
  if [[ "$KIND" == release ]]; then
    if [[ "$GRADLE" == "$ROOT/mobile/android-user/gradlew" ]]; then
      (cd "$dir" && bash "$dir/gradlew" ":app:bundleRelease" --no-daemon)
    else
      (cd "$dir" && "$GRADLE" ":app:bundleRelease" --no-daemon)
    fi
    aab="corgi_lusi_${app//-/_}_${version//./_}_${SUFFIX}.aab"
    cp "$dir/app/build/outputs/bundle/release/app-release.aab" "$OUT/$aab"
    (cd "$OUT" && sha256sum "$aab" > "$aab.sha256")
    echo "AAB: $OUT/$aab"
  fi
  if [[ "$SUFFIX" == release ]]; then
    verify_signature "$OUT/$name" apk
    verify_signature "$OUT/$aab" aab
    # A permanent name for releases/latest/download/<name> links (README, cabinet, bot).
    stable="corgi-lusi-android.apk"; [[ "$app" == android-admin ]] && stable="corgi-lusi-android-admin.apk"
    cp "$OUT/$name" "$OUT/$stable"
    (cd "$OUT" && sha256sum "$stable" > "$stable.sha256")
    # v28.119.0: the app's own update check reads this manifest (shop.remnawave.*.update.AppUpdate).
    code="$(sed -n 's/^ *versionCode = \([0-9][0-9]*\).*/\1/p' "$dir/app/build.gradle.kts" | head -1)"
    [[ "$code" =~ ^[0-9]+$ ]] || { echo "No versionCode in $dir/app/build.gradle.kts" >&2; exit 1; }
    printf '{"versionCode":%s,"versionName":"%s","sha256":"%s","apk":"https://github.com/%s/releases/latest/download/%s"}\n' \
      "$code" "$version" "$(cut -d' ' -f1 "$OUT/$stable.sha256")" "${GITHUB_REPOSITORY:-booarkz-cpu/shop-by-boo}" "$stable" > "$OUT/${stable%.apk}.json"
    echo "APK (permanent name): $OUT/$stable"
  fi
done
