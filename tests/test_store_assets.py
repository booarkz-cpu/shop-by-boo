"""Store listings of the apps: texts within the store limits, icons and screenshots of the right size."""
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def android_dir(role: str) -> Path:
    return ROOT / ("apps/vpn-client/android" if role == "client" else f"mobile/android-{role}")
STORE = ROOT / "mobile/store"
LIMITS = {"google-play/{l}/title.txt": 30, "google-play/{l}/short_description.txt": 80, "google-play/{l}/full_description.txt": 4000,
          "app-store/{a}/name.txt": 30, "app-store/{a}/subtitle.txt": 30, "app-store/{a}/keywords.txt": 100,
          "app-store/{a}/promotional_text.txt": 170, "app-store/{a}/description.txt": 4000, "app-store/{a}/release_notes.txt": 4000}


@pytest.mark.parametrize("pattern,limit", LIMITS.items())
@pytest.mark.parametrize("play,apple", [("ru-RU", "ru"), ("en-US", "en-US")])
def test_texts_fit_the_store_limits(pattern, limit, play, apple):
    text = (STORE / pattern.format(l=play, a=apple)).read_text(encoding="utf-8").strip()
    assert 0 < len(text) <= limit


def test_icons_and_graphics_have_store_sizes():
    for name, size in (("icons/icon-1024.png", (1024, 1024)), ("icons/icon-512.png", (512, 512)), ("google-play/feature-graphic.png", (1024, 500))):
        image = Image.open(STORE / name)
        assert image.size == size and image.mode == "RGB", name  # App Store rejects icons with alpha
    for platform, size in (("android", (1080, 1920)), ("ios", (1320, 2868))):
        shots = sorted((STORE / "screenshots" / platform).glob("*.png"))
        assert len(shots) >= 4, platform
        assert all(Image.open(p).size == size for p in shots), platform


def test_launcher_icons_are_wired():
    for role in ("user", "admin"):
        manifest = (android_dir(role) / "app/src/main/AndroidManifest.xml").read_text()
        assert 'android:icon="@mipmap/ic_launcher"' in manifest
        for density, px in (("mdpi", 48), ("xxxhdpi", 192)):
            assert Image.open(android_dir(role) / f"app/src/main/res/mipmap-{density}/ic_launcher.png").size == (px, px)
    for role, app in (("user", "VpnShopUser"), ("admin", "VpnShopAdmin")):
        assert "ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon" in (ROOT / f"mobile/ios-{role}/{app}.xcodeproj/project.pbxproj").read_text()
        assert Image.open(ROOT / f"mobile/ios-{role}/{app}/Assets.xcassets/AppIcon.appiconset/icon-1024.png").size == (1024, 1024)


def test_adaptive_launcher_icons_of_all_three_apps():
    """v28.137.0: adaptive icons, so a launcher's mask cuts only the background (owner's screenshot of 2026-11-13)."""
    names = {"client": ("ic_launcher", "ic_launcher_night", "ic_launcher_mint"), "user": ("ic_launcher",), "admin": ("ic_launcher",)}
    for role, icons in names.items():
        res = android_dir(role) / "app/src/main/res"
        for name in icons:
            xml = (res / f"mipmap-anydpi-v26/{name}.xml").read_text()
            assert f'@mipmap/{name}_bg' in xml and "@mipmap/ic_launcher_fg" in xml
            for density, scale in (("mdpi", 1), ("xxxhdpi", 4)):
                assert Image.open(res / f"mipmap-{density}/{name}_bg.png").size == (108 * scale, 108 * scale)
        fg = Image.open(res / "mipmap-xxxhdpi/ic_launcher_fg.png")
        assert fg.size == (432, 432) and fg.mode == "RGBA"
        box = fg.getchannel("A").getbbox()
        # The art stays in the middle part a launcher shows (72 of 108 dp); nothing is drawn near the layer's edge.
        assert box[0] >= 432 * 0.15 and box[2] <= 432 * 0.85 and box[1] >= 432 * 0.15 and box[3] <= 432 * 0.85, box
    # The picker in «Оформление» draws previews: painterResource cannot draw an adaptive icon.
    code = (ROOT / "apps/vpn-client/android/app/src/main/java/shop/corgi/client/ui/SettingsScreens.kt").read_text()
    assert "R.mipmap." not in code
    for key in ("corgi", "night", "mint"):
        assert f"R.drawable.icon_preview_{key}" in code
        assert (ROOT / f"apps/vpn-client/android/app/src/main/res/drawable-nodpi/icon_preview_{key}.png").is_file()
