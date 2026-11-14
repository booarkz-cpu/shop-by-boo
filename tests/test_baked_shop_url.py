"""v28.77.0: customers and administrators never type the API address — every app build bakes it in."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_one_source_for_every_build():
    assert (ROOT / "mobile/shop-url.txt").is_file()
    for script in ("build-android-apk.sh", "build-ios-packages.sh", "build-ios-signed.sh"):
        text = (ROOT / "scripts" / script).read_text()
        assert "mobile/shop-url.txt" in text and "CORGI_SHOP_URL" in text, script
        assert "^https://" in text, script  # only an https host is accepted
    for script in ("build-ios-packages.sh", "build-ios-signed.sh"):
        text = (ROOT / "scripts" / script).read_text()
        assert text.count('CORGI_SHOP_URL="$CORGI_SHOP_URL"') >= 1, script


def test_release_workflows_pass_the_repository_variable():
    for wf in ("mobile-release.yml", "build-mobile.yml"):
        text = (ROOT / ".github/workflows" / wf).read_text()
        assert text.count("CORGI_SHOP_URL: ${{ vars.CORGI_SHOP_URL }}") == 3, wf


def test_all_four_apps_use_the_baked_address():
    user_android = (ROOT / "apps/vpn-shop/android/app/src/main/java/shop/remnawave/user/MainActivity.kt").read_text()
    assert "BuildConfig.SHOP_URL" in user_android and "showBase = bakedBase.isBlank()" in user_android
    admin_gradle = (ROOT / "apps/lucy-admin/android/app/build.gradle.kts").read_text()
    assert 'buildConfigField("String", "SHOP_URL"' in admin_gradle and "buildConfig = true" in admin_gradle
    admin_android = (ROOT / "apps/lucy-admin/android/app/src/main/java/shop/remnawave/admin/MainActivity.kt").read_text()
    assert admin_android.count("BuildConfig.SHOP_URL") >= 2  # the first profile and every new one
    user_ios = (ROOT / "mobile/ios-user/VpnShopUser/ContentView.swift").read_text()
    assert "if bakedShopURL.isEmpty { InputField(title: t(\"server\")" in user_ios
    admin_ios = (ROOT / "mobile/ios-admin/VpnShopAdmin/ContentView.swift").read_text()
    assert admin_ios.count("bakedShopURL") >= 2
    for plist in ("ios-user/VpnShopUser/Info.plist", "ios-admin/VpnShopAdmin/Info.plist"):
        assert re.search(r"<key>CorgiShopURL</key>\s*<string>\$\(CORGI_SHOP_URL\)</string>", (ROOT / "mobile" / plist).read_text())
