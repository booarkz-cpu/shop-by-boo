"""v28.28.0: the native customer apps show the family plan and the service status in ru/en/uk."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = (ROOT / "mobile/android-user/app/src/main/java/shop/remnawave/user/MainActivity.kt").read_text()
IOS = (ROOT / "mobile/ios-user/VpnShopUser/ContentView.swift").read_text()
KEYS = ["family", "family_owned", "family_seats", "family_invite", "family_code", "family_join", "family_joined", "family_member_of",
        "family_none", "family_remove", "family_leave", "family_synced", "family_pending", "family_owner", "status", "status_ok",
        "status_degraded", "status_down", "status_unknown", "status_servers", "status_incidents", "status_none", "stars_hint"]


def test_every_new_string_is_translated():
    catalog = json.loads((ROOT / "mobile/l10n/user.json").read_text())
    for lang in ("ru", "en", "uk"):
        missing = [k for k in KEYS if not catalog[lang].get(k)]
        assert not missing, (lang, missing)
    assert catalog["ru"]["family"] != catalog["en"]["family"] != catalog["uk"]["family"]


def test_both_apps_have_family_and_status_tabs_on_the_shop_api():
    # Since 3.0.0 the sections come from the layout (GET /api/mobile/layout); family and status are sections of it.
    layout = json.loads((ROOT / "mobile/android-user/app/src/main/assets/default_layout.json").read_text())
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
    for project, name in (("ios-user/VpnShopUser.xcodeproj", "Corgi Lusi"), ("ios-admin/VpnShopAdmin.xcodeproj", "Corgi Lusi Admin")):
        assert f'CFBundleDisplayName = "{name}"' in (ROOT / "mobile" / project / "project.pbxproj").read_text()


def test_admin_apps_show_launch_readiness_and_alerts():
    android = (ROOT / "mobile/android-admin/app/src/main/java/shop/remnawave/admin/MainActivity.kt").read_text()
    ios = (ROOT / "mobile/ios-admin/VpnShopAdmin/ContentView.swift").read_text()
    catalog = json.loads((ROOT / "mobile/l10n/admin.json").read_text())
    for source in (android, ios):
        assert '"overview", "launch", "plans"' in source
        for path in ("/api/admin/ops/readiness", "/api/admin/ops/alerts", "/api/admin/ops/alerts/test"):
            assert path in source
    for lang in ("ru", "en", "uk"):
        assert all(catalog[lang].get(k) for k in ("launch", "launch_ready", "launch_missing", "alerts_test", "no_problems"))


def test_apps_are_version_3_0_0():
    for gradle in ("mobile/android-user/app/build.gradle.kts", "mobile/android-admin/app/build.gradle.kts"):
        text = (ROOT / gradle).read_text()
        assert "versionCode = 3000" in text and 'versionName = "3.0.0"' in text
    for project in ("ios-user/VpnShopUser.xcodeproj", "ios-admin/VpnShopAdmin.xcodeproj"):
        assert "MARKETING_VERSION = 3.0.0" in (ROOT / "mobile" / project / "project.pbxproj").read_text()
