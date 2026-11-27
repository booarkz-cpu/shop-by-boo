from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v290_apk_script_notes_and_clients():
    script = (ROOT / "scripts/build-android-apk.sh").read_text()
    assert "android-user" in script and "android-admin" in script
    notes = (ROOT / "docs/archive/root/RELEASE_NOTES_V2_9_0.md").read_text()
    assert "2.9.0" in notes and "APK" in notes
    instruction = (ROOT / "docs/archive/INSTRUCTION_BEFORE_ALPHA_6.md").read_text()
    assert "9.8" in instruction and "9.7" in instruction and "9.6" in instruction
    mobile = (ROOT / "docs/archive/MOBILE_BEFORE_ALPHA_6.md").read_text()
    assert "2.9.0" in mobile and "Русский" in mobile and "English" in mobile
    assert "RemnawaveShop-Android-User/2.9.0" in mobile
    user = (ROOT / "apps/vpn-shop/android/app/src/main/java/shop/remnawave/user/MainActivity.kt").read_text()
    (ROOT / "apps/lucy-admin/android/app/src/main/java/shop/remnawave/admin/MainActivity.kt").read_text()
    ios_user = (ROOT / "apps/vpn-shop/ios/VpnShopUser/VpnShopUserApp.swift").read_text()
    (ROOT / "apps/lucy-admin/ios/VpnShopAdmin/VpnShopAdminApp.swift").read_text()
    assert "externalUrlAllowed" in user
    assert "private let localHttpHosts" not in ios_user
    assert "localHttpHosts" in (ROOT / "apps/vpn-shop/ios/VpnShopUser/ContentView.swift").read_text()
    assert "scripts/package-source.py" in (ROOT / "scripts/build-release.sh").read_text()
