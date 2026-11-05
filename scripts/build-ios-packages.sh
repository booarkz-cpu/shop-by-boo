#!/usr/bin/env bash
# Device packages deliberately remain unsigned until an Apple identity is supplied.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/dist/mobile}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# v28.77.0: the shop's API address baked into both apps (CORGI_SHOP_URL wins over mobile/shop-url.txt).
CORGI_SHOP_URL="${CORGI_SHOP_URL:-$(grep -v '^#' "$ROOT/mobile/shop-url.txt" 2>/dev/null | tr -d '[:space:]' | head -c 200 || true)}"
[[ -z "$CORGI_SHOP_URL" || "$CORGI_SHOP_URL" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?/?$ ]] || { echo "CORGI_SHOP_URL must be https://host" >&2; exit 1; }
for role in user admin; do
  project=VpnShopUser
  [[ "$role" != admin ]] || project=VpnShopAdmin
  dir="$ROOT/mobile/ios-$role"
  version="$(sed -n 's/.*MARKETING_VERSION = \([^;]*\);.*/\1/p' "$dir/$project.xcodeproj/project.pbxproj" | head -1)"
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
  base="corgi_lusi_ios_${role}_${version//./_}"
  xcodebuild -project "$dir/$project.xcodeproj" -scheme "$project" \
    -configuration Release -sdk iphoneos -destination 'generic/platform=iOS' \
    -archivePath "$WORK/$project.xcarchive" CODE_SIGNING_ALLOWED=NO CORGI_SHOP_URL="$CORGI_SHOP_URL" archive
  app="$WORK/$project.xcarchive/Products/Applications/$project.app"
  test -d "$app"
  test "$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$app/Info.plist")" = "$version"
  # An unsigned IPA is a container for subsequent signing, not an installable iPhone app.
  mkdir -p "$WORK/$role/Payload"
  cp -R "$app" "$WORK/$role/Payload/"
  (cd "$WORK/$role" && zip -qry "$OUT/${base}_unsigned.ipa" Payload)
  xcodebuild -project "$dir/$project.xcodeproj" -scheme "$project" \
    -configuration Release -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
    -derivedDataPath "$WORK/simulator-$role" CODE_SIGNING_ALLOWED=NO CORGI_SHOP_URL="$CORGI_SHOP_URL" build
  ditto -c -k --keepParent "$WORK/simulator-$role/Build/Products/Release-iphonesimulator/$project.app" \
    "$OUT/${base}_simulator.zip"
  (cd "$OUT" && shasum -a 256 "${base}_unsigned.ipa" > "${base}_unsigned.ipa.sha256" \
    && shasum -a 256 "${base}_simulator.zip" > "${base}_simulator.zip.sha256")
done
