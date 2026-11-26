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
COMMIT="${XRAY_AAR_COMMIT:-e23aca42e775ea9c31dc4e37a3472927caa3b9cf}"
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
# Build in a fresh export so a failed dependency update cannot alter the cached checkout or the next run.
staged_source="$(mktemp -d "${RUNNER_TEMP:-/tmp}/xray-aar-source.XXXXXXXX")"
trap 'rm -rf "$staged_source"' EXIT
git archive "$COMMIT" | tar -xf - -C "$staged_source"
cd "$staged_source"
export PATH="$(go env GOPATH)/bin:$PATH"
go install "golang.org/x/mobile/cmd/gomobile@${MOBILE_VERSION}"
go install "golang.org/x/mobile/cmd/gobind@${MOBILE_VERSION}"
gomobile init
go mod download
# The latest stable Gorilla tag v1.5.3 predates its mask-key fix (GO-2026-6278).
# Only replace that selected version. Preserve a future upstream upgrade or removal.
ws_module=github.com/gorilla/websocket
ws_selected="$(go list -mod=readonly -m -f '{{if not .Replace}}{{.Path}} {{.Version}}{{end}}' all |
  awk -v name="$ws_module" '$1 == name {print $2}')"
if [[ "$ws_selected" == v1.5.3 ]]; then
  ws_fixed=v1.5.4-0.20240701034025-d67f41855da4
  ws_sum='h1:PYKzliEgITjLJoJqbV90S0YRaG8LNAsICH6fp6MApC0='
  ws_mod_sum='h1:r4w70xmWCQKmi1ONH4KIaBptdivuRPyosB9RmPlGEwA='
  go mod edit -require="$ws_module@$ws_fixed"
  go mod download "$ws_module@$ws_fixed"
  resolved="$(go list -mod=readonly -m -f '{{.Version}} {{.Sum}} {{.GoModSum}}{{if .Replace}} replaced{{end}}' "$ws_module")"
  if [[ "$resolved" != "$ws_fixed $ws_sum $ws_mod_sum" ]]; then
    echo "Unexpected version or checksum for $ws_module" >&2
    exit 1
  fi
fi
gomobile bind -v -target=android -androidapi 26 -trimpath -ldflags='-s -w -buildid= -checklinkname=0' -o libv2ray.aar ./
python3 "$CHECK" stamp "$COMMIT" libv2ray.aar
mkdir -p "$OUT"
cp libv2ray.aar "$OUT/libv2ray.aar"
sha256sum "$OUT/libv2ray.aar"
echo "$COMMIT" > "$OUT/libv2ray.commit"
