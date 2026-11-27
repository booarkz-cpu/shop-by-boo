"""v28.28.0: the native customer apps show the family plan and the service status in ru/en/uk."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = (ROOT / "apps/vpn-shop/android/app/src/main/java/shop/remnawave/user/MainActivity.kt").read_text()
IOS = (ROOT / "apps/vpn-shop/ios/VpnShopUser/ContentView.swift").read_text()
KEYS = ["family", "family_owned", "family_seats", "family_invite", "family_code", "family_join", "family_joined", "family_member_of",
        "family_none", "family_remove", "family_leave", "family_synced", "family_pending", "family_owner", "status", "status_ok",
        "status_degraded", "status_down", "status_unknown", "status_servers", "status_incidents", "status_none", "stars_hint"]


def test_every_new_string_is_translated():
    catalog = json.loads((ROOT / "packages/localization/user.json").read_text())
    for lang in ("ru", "en", "uk"):
        missing = [k for k in KEYS if not catalog[lang].get(k)]
        assert not missing, (lang, missing)
    assert catalog["ru"]["family"] != catalog["en"]["family"] != catalog["uk"]["family"]


def test_both_apps_have_family_and_status_tabs_on_the_shop_api():
    # Since 3.0.0 the sections come from the layout (GET /api/mobile/layout); family and status are sections of it.
    layout = json.loads((ROOT / "apps/vpn-shop/android/app/src/main/assets/default_layout.json").read_text())
    kinds = {s["kind"] for s in layout["ru"]["sections"]}
    assert {"family", "devices", "notifications", "status"} <= kinds
    for source in (ANDROID, IOS):
        for path in ("/api/me/family", "/api/public/service-status", "/api/me/family/join", "/api/me/family/members/"):
            assert path in source, path
        # An older shop without these endpoints must not break the rest of the app.
        assert "Shops on releases before v28.25.0" in source
    assert 'fun delete(path: String)' in ANDROID and '.delete("/api/me/family/members/' in ANDROID
    assert 'familyAction("DELETE", "/api/me/family/members/' in IOS


def test_store_display_names_carry_the_brand():
    for project, name in (("apps/vpn-shop/ios/VpnShopUser.xcodeproj", "Corgi Lusi"), ("apps/lucy-admin/ios/VpnShopAdmin.xcodeproj", "Corgi Lusi Admin")):
        assert f'CFBundleDisplayName = "{name}"' in (ROOT / project / "project.pbxproj").read_text()


def test_admin_apps_show_launch_readiness_and_alerts():
    android = (ROOT / "apps/lucy-admin/android/app/src/main/java/shop/remnawave/admin/MainActivity.kt").read_text()
    ios = (ROOT / "apps/lucy-admin/ios/VpnShopAdmin/ContentView.swift").read_text()
    catalog = json.loads((ROOT / "packages/localization/admin.json").read_text())
    for source in (android, ios):
        assert '"overview", "launch", "plans"' in source
        for path in ("/api/admin/ops/readiness", "/api/admin/ops/alerts", "/api/admin/ops/alerts/test"):
            assert path in source
    for lang in ("ru", "en", "uk"):
        assert all(catalog[lang].get(k) for k in ("launch", "launch_ready", "launch_missing", "alerts_test", "no_problems"))


def android_version(module):
    config = (ROOT / "apps" / module / "android/app/build.gradle.kts").read_text()
    name, = re.findall(r'^[ \t]*versionName = "(\d+\.\d+\.\d+)"$', config, re.M)
    code, = re.findall(r'^[ \t]*versionCode = ([1-9]\d*)$', config, re.M)
    return name, int(code)


def test_native_shop_and_admin_versions_match():
    name, code = android_version("vpn-shop")
    assert android_version("lucy-admin") == (name, code)
    for project in ("apps/vpn-shop/ios/VpnShopUser.xcodeproj", "apps/lucy-admin/ios/VpnShopAdmin.xcodeproj"):
        text = (ROOT / project / "project.pbxproj").read_text()
        assert set(re.findall(r'\bMARKETING_VERSION = ([^;]+);', text)) == {name}
        assert set(re.findall(r'\bCURRENT_PROJECT_VERSION = ([^;]+);', text)) == {str(code)}


def test_mobile_channel_builds_can_replace_the_previous_actions_packages():
    # Issue 509: those builds still read the old update feed and are already installed on some devices.
    for module, last_code in (("vpn-shop", 3910), ("lucy-admin", 3910), ("vpn-client", 1102)):
        assert android_version(module)[1] > last_code


def test_native_api_user_agents_do_not_embed_a_fixed_marketing_version():
    for module in ("vpn-shop", "lucy-admin"):
        app = ROOT / "apps" / module
        for source in [*(app / "android/app/src/main").rglob("*.kt"), *(app / "ios").rglob("*.swift")]:
            assert not re.search(r'"CorgiLusi-(Android|iOS)-(Admin|User)/\d', source.read_text()), source
