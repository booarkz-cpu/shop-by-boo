from pathlib import Path
import json, xml.etree.ElementTree as ET, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
checks=[]
def ok(name, cond):
    checks.append((name, bool(cond)))

for lang in ('ru','en','uk'):
    p=ROOT/'mobile'/'l10n'/('user.json' if lang else '')
    # JSON catalogs contain language keys rather than separate files.
    data=json.loads((ROOT/'mobile'/'l10n'/'user.json').read_text())
    ok(f'user locale {lang}', lang in data)
for p in [ROOT/'mobile/android-user/app/src/main/AndroidManifest.xml', ROOT/'mobile/android-admin/app/src/main/AndroidManifest.xml', ROOT/'mobile/ios-user/VpnShopUser/Info.plist', ROOT/'mobile/ios-admin/VpnShopAdmin/Info.plist']:
    try: ET.parse(p); ok(f'XML {p.name}', True)
    except Exception: ok(f'XML {p.name}', False)
ok('production api', (ROOT/'backend/app/production_api.py').exists())
ok('android vpn service', (ROOT/'mobile/android-user/app/src/main/java/shop/remnawave/user/vpn/CorgiVpnService.kt').exists())
ok('ios packet tunnel provider', (ROOT/'mobile/ios-user/VpnShopUser/VPN/CorgiPacketTunnelProvider.swift').exists())
ok('browser extension', (ROOT/'browser-extension/manifest.json').exists())
ok('desktop contracts', all((ROOT/'desktop'/x/'README.md').exists() for x in ('windows','macos','linux')))
ok('terraform contract', (ROOT/'terraform/corgi/main.tf').exists())
ok('privacy launch policy', (ROOT/'docs/archive/root/PRODUCTION_LAUNCH_V15.md').exists())
failed=[n for n,v in checks if not v]
print(f'v15 quality: {len(checks)-len(failed)}/{len(checks)} passed')
if failed:
    print('\n'.join('FAIL '+x for x in failed)); sys.exit(1)
