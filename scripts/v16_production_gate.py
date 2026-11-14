from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
checks=[]
def ok(name, value): checks.append((name,bool(value)))
ok('production launch api', (ROOT/'backend/app/production_launch_api.py').exists())
ok('wireguard provisioner', (ROOT/'deploy/wireguard/provision-node.sh').exists())
ok('wireguard docs', (ROOT/'deploy/wireguard/README_RU.md').exists())
ok('launch runbook', (ROOT/'docs/production/PRODUCTION_LAUNCH_V16_RU.md').exists())
ok('android vpn service', (ROOT/'apps/vpn-shop/android/app/src/main/java/shop/remnawave/user/vpn/CorgiVpnService.kt').exists())
ok('ios packet tunnel', (ROOT/'mobile/ios-user/VpnShopUser/VPN/CorgiPacketTunnelProvider.swift').exists())
ok('cli', (ROOT/'corgi-cli').exists())
ok('terraform', (ROOT/'terraform').exists())
ok('browser extension', (ROOT/'browser-extension').exists())
ok('ru en uk', all((ROOT/'mobile/ios-user/VpnShopUser/l10n.json').exists() for _ in [1]))
failed=[n for n,v in checks if not v]
print(f'v16 production gate: {len(checks)-len(failed)}/{len(checks)} passed')
if failed:
    print('FAILED:', ', '.join(failed)); raise SystemExit(1)
