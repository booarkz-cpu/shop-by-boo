#!/usr/bin/env bash
# Build the engine of the iOS packet tunnel (mobile/ios-user/CorgiTunnel) on macOS:
#   * LibXray.xcframework — Xray-core bound with gomobile by XTLS/libXray (MIT; Xray-core MPL-2.0);
#   * HevSocks5Tunnel.xcframework — hev-socks5-tunnel (MIT), packets of the tunnel → SOCKS of Xray.
#
#   bash scripts/ios/build-tunnel-frameworks.sh   # → mobile/ios-user/Frameworks/*.xcframework
#
# Needs Xcode with the iOS and iOS Simulator SDKs, Go (the version of libXray's go.mod) and Python 3.
# Both sources are pinned to the commits below; override with LIBXRAY_COMMIT / HEV_COMMIT.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LIBXRAY_COMMIT="${LIBXRAY_COMMIT:-756ef80f41903eaf7bbeeb38a0a1f802ec204464}"
HEV_COMMIT="${HEV_COMMIT:-55cc2efc280f3a72ffc60ce856772b57f5122e9c}"
OUT="$ROOT/mobile/ios-user/Frameworks"
WORK="${RUNNER_TEMP:-/tmp}/corgi-ios-tunnel"
mkdir -p "$OUT" "$WORK"

fetch() {  # fetch <dir> <repo> <commit>
  if [[ ! -d "$1/.git" ]]; then git init -q "$1"; git -C "$1" remote add origin "$2"; fi
  git -C "$1" fetch -q --depth 1 origin "$3"
  git -C "$1" checkout -q FETCH_HEAD
}

# --- hev-socks5-tunnel (only the iOS slices: device and simulator) ---
fetch "$WORK/hev" https://github.com/heiher/hev-socks5-tunnel "$HEV_COMMIT"
git -C "$WORK/hev" submodule update -q --init --depth 1 --recursive
(
  cd "$WORK/hev"
  build() {  # build <sdk> <arch>
    make clean >/dev/null 2>&1 || true
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
rm -rf "$OUT/HevSocks5Tunnel.xcframework"
cp -R "$WORK/hev/HevSocks5Tunnel.xcframework" "$OUT/"

# --- libXray (gomobile) ---
fetch "$WORK/libxray" https://github.com/XTLS/libXray "$LIBXRAY_COMMIT"
(
  cd "$WORK/libxray"
  export PATH="$(go env GOPATH)/bin:$PATH"
  python3 build/main.py apple gomobile
)
rm -rf "$OUT/LibXray.xcframework"
cp -R "$WORK/libxray/LibXray.xcframework" "$OUT/"

printf 'libXray %s\nhev-socks5-tunnel %s\n' "$LIBXRAY_COMMIT" "$HEV_COMMIT" > "$OUT/SOURCES.txt"
ls -la "$OUT"
