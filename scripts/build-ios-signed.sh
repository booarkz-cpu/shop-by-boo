#!/usr/bin/env bash
# Manual Apple signing. Private identities and profiles are temporary, never assets.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:?Output directory required}"
: "${IOS_CERTIFICATE_BASE64:?Apple P12 certificate required}"
: "${IOS_CERTIFICATE_PASSWORD:?P12 password required}"
: "${IOS_USER_PROFILE_BASE64:?Buyer provisioning profile required}"
: "${IOS_ADMIN_PROFILE_BASE64:?Administrator provisioning profile required}"
: "${IOS_TEAM_ID:?Apple Team ID required}"
METHOD="${IOS_EXPORT_METHOD:-release-testing}"
case "$METHOD" in release-testing|debugging|app-store-connect|enterprise) ;; *) echo 'Unsupported export method' >&2; exit 1;; esac
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
WORK="$(mktemp -d)"
KEYCHAIN="$WORK/signing.keychain-db"
PROFILE_DIR="$HOME/Library/MobileDevice/Provisioning Profiles"
XCODE_PROFILE_DIR="$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles"
mkdir -p "$PROFILE_DIR" "$XCODE_PROFILE_DIR"
cleanup() {
  security delete-keychain "$KEYCHAIN" >/dev/null 2>&1 || true
  for name in user admin; do
    rm -f "$PROFILE_DIR/corgi-ci-$name.mobileprovision" "$XCODE_PROFILE_DIR/corgi-ci-$name.mobileprovision"
  done
  rm -rf "$WORK"
}
trap cleanup EXIT
umask 077
printf '%s' "$IOS_CERTIFICATE_BASE64" | base64 --decode > "$WORK/signing.p12"
KEYCHAIN_PASSWORD="$(openssl rand -hex 32)"
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security set-keychain-settings -lut 21600 "$KEYCHAIN"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security import "$WORK/signing.p12" -P "$IOS_CERTIFICATE_PASSWORD" -A -t cert -f pkcs12 -k "$KEYCHAIN" >/dev/null
security set-key-partition-list -S apple-tool:,apple: -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN" >/dev/null
security list-keychains -d user -s "$KEYCHAIN" "$HOME/Library/Keychains/login.keychain-db"
IDENTITY="$(security find-identity -v -p codesigning "$KEYCHAIN" | sed -n 's/.*) \([A-F0-9]\{40\}\) .*/\1/p' | head -1)"
test -n "$IDENTITY"
for role in user admin; do
  project=VpnShopUser; profile="$IOS_USER_PROFILE_BASE64"
  [[ "$role" != admin ]] || { project=VpnShopAdmin; profile="$IOS_ADMIN_PROFILE_BASE64"; }
  path="$PROFILE_DIR/corgi-ci-$role.mobileprovision"
  printf '%s' "$profile" | base64 --decode > "$path"
  cp "$path" "$XCODE_PROFILE_DIR/corgi-ci-$role.mobileprovision"
  security cms -D -i "$path" > "$WORK/profile.plist"
  UUID="$(python3 - "$WORK/profile.plist" "$IOS_TEAM_ID" "shop.remnawave.$role" <<'PY'
import datetime, plistlib, sys
p=plistlib.load(open(sys.argv[1],'rb'))
assert sys.argv[2] in p['TeamIdentifier'], 'Wrong signing team'
assert p['Entitlements']['application-identifier'].endswith('.'+sys.argv[3]), 'Wrong bundle ID'
assert p['ExpirationDate'] > datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), 'Expired profile'
print(p['UUID'])
PY
)"
  python3 - "$WORK/export.plist" "$METHOD" "$IOS_TEAM_ID" "$IDENTITY" "shop.remnawave.$role" "$UUID" <<'PY'
import plistlib,sys
_,path,method,team,identity,bundle,profile=sys.argv
with open(path,'wb') as f:
 plistlib.dump({'method':method,'destination':'export','teamID':team,'signingStyle':'manual',
               'signingCertificate':identity,'provisioningProfiles':{bundle:profile}},f)
PY
  xcodebuild -project "$ROOT/mobile/ios-$role/$project.xcodeproj" -scheme "$project" \
    -configuration Release -sdk iphoneos -destination 'generic/platform=iOS' \
    -archivePath "$WORK/$project.xcarchive" CODE_SIGNING_ALLOWED=YES CODE_SIGN_STYLE=Manual \
    CODE_SIGN_IDENTITY="$IDENTITY" DEVELOPMENT_TEAM="$IOS_TEAM_ID" PROVISIONING_PROFILE_SPECIFIER="$UUID" \
    CORGI_ASSOCIATED_DOMAIN="${CORGI_ASSOCIATED_DOMAIN:-cabinet.example.com}" archive
  xcodebuild -exportArchive -archivePath "$WORK/$project.xcarchive" \
    -exportOptionsPlist "$WORK/export.plist" -exportPath "$WORK/export-$role"
  ipa="$WORK/export-$role/$project.ipa"
  test -f "$ipa"
  mkdir "$WORK/verify-$role"
  unzip -q "$ipa" -d "$WORK/verify-$role"
  app="$WORK/verify-$role/Payload/$project.app"
  codesign --verify --deep --strict "$app"
  test -f "$app/embedded.mobileprovision"
  test "$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$app/Info.plist")" = 3.0.0
  name="corgi_lusi_ios_${role}_2_15_0_signed.ipa"
  cp "$ipa" "$OUT/$name"
  (cd "$OUT" && shasum -a 256 "$name" > "$name.sha256")
done
