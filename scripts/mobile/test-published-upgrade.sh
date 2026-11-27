#!/usr/bin/env bash
# Exercise Android's in-place upgrade from an immutable release on a clean, rootable CI emulator.
# Usage: bash scripts/mobile/test-published-upgrade.sh PREVIOUS_RELEASE_TAG SIGNED_ARTIFACT_DIR
set -Eeuo pipefail

fail() { echo "$*" >&2; exit 1; }
[[ $# == 2 ]] || fail "Expected a published release tag and the directory of signed Android packages"
tag=$1
[[ $tag =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || fail "Invalid release tag"
artifacts=$(cd "$2" && pwd)
root=$(cd "$(dirname "$0")/../.." && pwd)
tools="${ANDROID_HOME:?Android SDK required}/build-tools/35.0.0"
pin=$(grep -Ex '[0-9a-f]{64}' "$root/mobile/android-signing-cert.sha256")
previous=$(mktemp -d)
trap 'rm -rf "$previous"' EXIT
upgraded=0

# Limit privileged operations to an emulator. The signed apps are non-debuggable, so
# only a rootable image can place and read a marker in the real private data directory.
[[ $(adb shell getprop ro.kernel.qemu | tr -d '\r') == 1 ||
   $(adb shell getprop ro.boot.qemu | tr -d '\r') == 1 ]] || fail "Expected a disposable Android emulator"
adb root
timeout 60 adb wait-for-device
[[ $(adb shell id -u | tr -d '\r') == 0 ]] || fail "Use an AOSP or Google APIs emulator that supports adb root"

verify_pair() {
  local dir=$1 name=$2 package=$3 cert hash identity actual_id code version
  cert=$("$tools/apksigner" verify --verbose --print-certs "$dir/$name.apk" |
    python3 "$root/scripts/mobile/apk-signer-digest.py")
  [[ $cert == "$pin" ]] || fail "$name: signing certificate differs from the production pin"
  hash=$(sha256sum < "$dir/$name.apk")
  hash=${hash%% *}
  identity=$("$tools/aapt" dump badging "$dir/$name.apk" |
    sed -nE "s/^package: name='([^']+)' versionCode='([1-9][0-9]*)' versionName='([^']+)'.*$/\1 \2 \3/p")
  read -r actual_id code version <<< "$identity"
  [[ $actual_id == "$package" ]] || fail "$name: unexpected APK identity $identity"
  jq -e --arg sha "$hash" --argjson code "$code" --arg version "$version" \
    '.sha256 == $sha and .versionCode == $code and .versionName == $version' "$dir/$name.json" >/dev/null ||
    fail "$name: update manifest disagrees with the APK"
}

installed_identity() {
  local package=$1 code=$2 uid first
  adb shell pm list packages --show-versioncode "$package" | tr -d '\r' |
    grep -Fx "package:$package versionCode:$code" >/dev/null || fail "$package: installed versionCode differs from $code"
  uid=$(adb shell pm list packages -U "$package" | tr -d '\r' |
    awk -v app="package:$package" '$1 == app && $2 ~ /^uid:[0-9]+$/ {print substr($2, 5)}')
  first=$(adb shell dumpsys package "$package" | tr -d '\r' | sed -nE 's/^[[:space:]]*firstInstallTime=(.+)$/\1/p')
  [[ $uid =~ ^[0-9]+$ && -n $first ]] || fail "$package: missing installed UID or first install time"
  printf '%s %s\n' "$uid" "$first"
}

check_upgrade() {
  local module=$1 package=$2 name=$3 ext old_code new_code installed before after marker token
  for ext in json apk; do
    curl --fail --silent --show-error --location --retry 3 --connect-timeout 20 --max-time 300 \
      --proto '=https' --proto-redir '=https' \
      "https://github.com/booarkz-cpu/shop-by-boo/releases/download/$tag/$name.$ext" -o "$previous/$name.$ext"
  done
  verify_pair "$previous" "$name" "$package"
  verify_pair "$artifacts" "$name" "$package"
  old_code=$(jq -er .versionCode "$previous/$name.json")
  new_code=$(python3 "$root/scripts/mobile/check-apk-version.py" \
    "$root/apps/$module/android/app/build.gradle.kts" "$artifacts/$name.apk")
  (( new_code >= old_code )) || fail "$package: refusing downgrade from $old_code to $new_code"
  if (( new_code == old_code )); then
    [[ $(jq -er .versionName "$previous/$name.json") == "$(jq -er .versionName "$artifacts/$name.json")" ]] ||
      fail "$package: version name changed without increasing versionCode $old_code"
    echo "$package versionCode $old_code unchanged; no upgrade exercised"
    return
  fi

  installed=$(adb shell pm list packages "$package" | tr -d '\r')
  if grep -Fxq "package:$package" <<< "$installed"; then fail "$package: use a clean emulator"; fi
  adb install "$previous/$name.apk"
  before=$(installed_identity "$package" "$old_code")
  marker="/data/user/0/$package/.corgi-upgrade-ci"
  token="$package-$old_code-$new_code-$RANDOM"
  adb shell "printf '%s' '$token' > '$marker'"
  adb install -r "$artifacts/$name.apk"
  after=$(installed_identity "$package" "$new_code")
  [[ $before == "$after" ]] || fail "$package: UID or first install time changed"
  [[ $(adb shell cat "$marker" | tr -d '\r') == "$token" ]] || fail "$package: private app data lost"
  adb shell rm "$marker"
  upgraded=$((upgraded + 1))
  echo "$package $old_code -> $new_code: signature, installed version, UID, first install time and private data verified"
}

check_upgrade vpn-shop shop.remnawave.user corgi-lusi-android
check_upgrade lucy-admin shop.remnawave.admin corgi-lusi-android-admin
check_upgrade vpn-client shop.corgi.client corgi-lusi-client
if (( upgraded == 0 )); then
  echo "All three versions match $tag. No in-place upgrade was exercised."
  exit 3
fi
