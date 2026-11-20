#!/usr/bin/env bash
# Build the engine of the iOS packet tunnel (apps/vpn-shop/ios/CorgiTunnel) on macOS:
#   * LibXray.xcframework — Xray-core bound with gomobile by XTLS/libXray (MIT; Xray-core MPL-2.0);
#   * HevSocks5Tunnel.xcframework — hev-socks5-tunnel (MIT), packets of the tunnel → SOCKS of Xray.
#
#   bash scripts/ios/build-tunnel-frameworks.sh   # → apps/vpn-shop/ios/Frameworks/*.xcframework
#
# Needs Xcode with the iOS and iOS Simulator SDKs, Go (the version of libXray's go.mod) and Python 3.
# Both sources are pinned to the commits below; override with LIBXRAY_COMMIT / HEV_COMMIT.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LIBXRAY_COMMIT="${LIBXRAY_COMMIT:-5a0f7d8d1c28b34afb5727b04b26a10f6dbac7e3}"
HEV_COMMIT="${HEV_COMMIT:-75dbc1e9ace6c70d3d1b94df7c283efe1de7effc}"
OUT="$ROOT/apps/vpn-shop/ios/Frameworks"
verify() {
  grep -Fxq "libXray $LIBXRAY_COMMIT" "$OUT/SOURCES.txt"
  grep -Fxq "hev-socks5-tunnel $HEV_COMMIT" "$OUT/SOURCES.txt"
  python3 "$ROOT/scripts/ios/verify_tunnel_frameworks.py" "$OUT"
}

if [[ ${1:-} == --verify ]]; then verify; exit 0; fi
mkdir -p "$OUT"
WORK="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/corgi-ios-tunnel.XXXXXXXX")"
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/output"
mkdir "$STAGE"

fetch() {  # fetch <dir> <repo> <commit>
  if [[ ! -d "$1/.git" ]]; then git init -q "$1"; git -C "$1" remote add origin "$2"; fi
  [[ "$3" =~ ^[0-9a-f]{40}$ ]] || { echo "Expected a full commit for $2" >&2; return 1; }
  [[ "$(git -C "$1" remote get-url origin)" == "$2" ]]
  git -C "$1" fetch -q --depth 1 origin "$3"
  git -C "$1" checkout -q --detach FETCH_HEAD
  [[ "$(git -C "$1" rev-parse HEAD)" == "$3" ]]
}

# --- hev-socks5-tunnel (only the iOS slices: device and simulator) ---
fetch "$WORK/hev" https://github.com/heiher/hev-socks5-tunnel "$HEV_COMMIT"
git -C "$WORK/hev" submodule sync -q --recursive
git -C "$WORK/hev" submodule update -q --init --depth 1 --recursive
git -C "$WORK/hev" submodule status --recursive > "$STAGE/submodules.txt"
if grep -Eq '^[-+U]' "$STAGE/submodules.txt"; then echo "Submodule differs from its gitlink" >&2; exit 1; fi
(
  cd "$WORK/hev"
  build() {  # build <sdk> <arch>
    make clean >/dev/null
    make PP="xcrun --sdk $1 clang" CC="xcrun --sdk $1 clang" CFLAGS="-arch $2 -m${1/iphonesimulator/ios-simulator}-version-min=15.0" \
         LFLAGS="-arch $2 -m${1/iphonesimulator/ios-simulator}-version-min=15.0" static -j"$(sysctl -n hw.ncpu)"
    mkdir -p "slices/$1-$2"
    libtool -static -o "slices/$1-$2/libhev-socks5-tunnel.a" bin/libhev-socks5-tunnel.a third-part/lwip/bin/liblwip.a \
            third-part/yaml/bin/libyaml.a third-part/hev-task-system/bin/libhev-task-system.a
  }
  rm -rf slices HevSocks5Tunnel.xcframework
  build iphoneos arm64
  build iphonesimulator arm64
  build iphonesimulator x86_64
  mkdir -p slices/iphonesimulator
  lipo -create slices/iphonesimulator-arm64/libhev-socks5-tunnel.a slices/iphonesimulator-x86_64/libhev-socks5-tunnel.a \
       -output slices/iphonesimulator/libhev-socks5-tunnel.a
  mkdir -p slices/include/HevSocks5Tunnel
  cp src/hev-main.h module.modulemap slices/include/HevSocks5Tunnel/
  xcodebuild -create-xcframework \
    -library slices/iphoneos-arm64/libhev-socks5-tunnel.a -headers slices/include \
    -library slices/iphonesimulator/libhev-socks5-tunnel.a -headers slices/include \
    -output HevSocks5Tunnel.xcframework
)
cp -R "$WORK/hev/HevSocks5Tunnel.xcframework" "$STAGE/"

# --- libXray (gomobile) ---
fetch "$WORK/libxray" https://github.com/XTLS/libXray "$LIBXRAY_COMMIT"
(
  cd "$WORK/libxray"
  export PATH="$(go env GOPATH)/bin:$PATH"
  # Use the versions actually selected by this checkout, including an explicit commit override.
  mobile_version="$(go list -mod=readonly -m -f '{{.Version}}' golang.org/x/mobile)"
  [[ "$mobile_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]]
  export LIBXRAY_GOMOBILE_VERSION="$mobile_version"
  go list -mod=readonly -m -f '{{.Path}} {{.Version}}' github.com/xtls/xray-core golang.org/x/mobile > "$STAGE/go-modules.txt"
  python3 build/main.py apple gomobile
)
cp -R "$WORK/libxray/LibXray.xcframework" "$STAGE/"
{
  printf 'libXray %s\nhev-socks5-tunnel %s\n' "$LIBXRAY_COMMIT" "$HEV_COMMIT"
  cat "$STAGE/go-modules.txt" "$STAGE/submodules.txt"
  go version
  xcodebuild -version
  for sdk in iphoneos iphonesimulator; do printf '%s %s\n' "$sdk" "$(xcrun --sdk "$sdk" --show-sdk-version)"; done
} > "$STAGE/SOURCES.txt"
python3 "$ROOT/scripts/ios/verify_tunnel_frameworks.py" --record "$STAGE"
# SOURCES.txt is the completion marker for the cache and signing workflows.
rm -f "$OUT/SOURCES.txt"
for framework in LibXray HevSocks5Tunnel; do
  rm -rf "$OUT/$framework.xcframework"
  mv "$STAGE/$framework.xcframework" "$OUT/"
done
mv "$STAGE/ios-sha256.txt" "$OUT/"
mv "$STAGE/SOURCES.txt" "$OUT/"
cat "$OUT/SOURCES.txt" "$OUT/ios-sha256.txt"
