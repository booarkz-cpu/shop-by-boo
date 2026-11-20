#!/usr/bin/env bash
# Build the embedded VPN engine of the Android app: Xray-core (MPL-2.0) bound with gomobile by
# AndroidLibXrayLite (LGPL-3.0) into libv2ray.aar. The app loads the library when it is present
# (app/libs/libv2ray.aar) and otherwise hands the subscription to Happ/v2rayNG/Hiddify.
#
#   bash scripts/mobile/build-xray-aar.sh            # → apps/vpn-shop/android/app/libs/libv2ray.aar
#
# Needs Go (the version of the pinned go.mod), the Android SDK and NDK (ANDROID_NDK_HOME or
# ANDROID_NDK_LATEST_HOME). The library is a separate .so in the APK, so it can be replaced as
# the LGPL requires; its sources are the pinned commit below.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REPO="https://github.com/2dust/AndroidLibXrayLite"
COMMIT="${XRAY_AAR_COMMIT:-b5a377087e74eaa34e86718710b04c50f4b767f5}"
MOBILE_VERSION="v0.0.0-20261011034528-197770444867"
OUT="$ROOT/apps/vpn-shop/android/app/libs"
CHECK="$ROOT/scripts/mobile/xray-artifact.py"
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo "XRAY_AAR_COMMIT must be a full commit" >&2; exit 1; }
if [[ ${1:-} == --verify-apk ]]; then
  shift
  exec python3 "$CHECK" verify "$COMMIT" "$OUT/libv2ray.aar" "$@"
fi
WORK="${RUNNER_TEMP:-/tmp}/xray-aar-$COMMIT"
export ANDROID_NDK_HOME="${ANDROID_NDK_HOME:-${ANDROID_NDK_LATEST_HOME:-}}"
[[ -n "$ANDROID_NDK_HOME" ]] || { echo "ANDROID_NDK_HOME is not set" >&2; exit 1; }
if [[ ! -d "$WORK/.git" ]]; then
  git init -q "$WORK"
  git -C "$WORK" remote add origin "$REPO"
fi
git -C "$WORK" fetch -q --depth 1 origin "$COMMIT"
git -C "$WORK" checkout -q FETCH_HEAD
cd "$WORK"
[[ "$(git rev-parse HEAD)" == "$COMMIT" ]] || { echo "Fetched source does not match $COMMIT" >&2; exit 1; }
export PATH="$(go env GOPATH)/bin:$PATH"
go install "golang.org/x/mobile/cmd/gomobile@${MOBILE_VERSION}"
go install "golang.org/x/mobile/cmd/gobind@${MOBILE_VERSION}"
gomobile init
go mod download
gomobile bind -v -target=android -androidapi 26 -trimpath -ldflags='-s -w -buildid= -checklinkname=0' -o libv2ray.aar ./
python3 "$CHECK" stamp "$COMMIT" libv2ray.aar
mkdir -p "$OUT"
cp libv2ray.aar "$OUT/libv2ray.aar"
sha256sum "$OUT/libv2ray.aar"
echo "$COMMIT" > "$OUT/libv2ray.commit"
