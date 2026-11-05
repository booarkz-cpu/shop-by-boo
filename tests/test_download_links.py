"""v28.77.0: permanent download links (releases/latest/download/<name>) point to names the release build produces."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"https://github\.com/booarkz-cpu/shop-by-boo/releases/latest/download/([A-Za-z0-9._-]+)")


def _produced() -> set[str]:
    script = (ROOT / "scripts/build-android-apk.sh").read_text()
    names = set(re.findall(r'stable="([a-z0-9.-]+\.apk)"', script)) | set(re.findall(r'stable="([a-z0-9.-]+\.apk)"; \[\[', script))
    names |= set(re.findall(r'&& stable="([a-z0-9.-]+\.apk)"', script))
    # v28.79.0: the third app «Корги Люси: клиент» is built by mobile-release.yml itself.
    names |= set(re.findall(r"cp \"\$client\" dist/mobile/([a-z0-9.-]+\.apk)", (ROOT / ".github/workflows/mobile-release.yml").read_text()))
    return names


def test_build_script_names_both_apps():
    assert _produced() == {"corgi-lusi-android.apk", "corgi-lusi-android-admin.apk", "corgi-lusi-client.apk"}


def test_release_workflow_publishes_the_permanent_names():
    workflow = (ROOT / ".github/workflows/mobile-release.yml").read_text()
    pattern = re.search(r"/\^corgi-lusi-\(\?:android\(\?:-admin\)\?\|client\)\\\.apk\(\?:\\\.sha256\)\?\$/", workflow)
    assert pattern, "mobile-release.yml must attach the permanent APK names"


def test_every_download_link_points_to_a_produced_file():
    docs = [ROOT / "README.md", ROOT / "README.en.md", ROOT / "README.uk.md", *sorted((ROOT / "docs/wiki").glob("*/Mobile.md"))]
    produced = _produced()
    seen = set()
    for doc in docs:
        for name in LINK.findall(doc.read_text()):
            assert name in produced, f"{doc.name}: {name} is not built by the release"
            seen.add(name)
    assert seen == produced


def test_signing_certificate_is_pinned():
    lines = [l for l in (ROOT / "mobile/android-signing-cert.sha256").read_text().splitlines() if l and not l.startswith("#")]
    assert len(lines) == 1 and re.fullmatch(r"[0-9a-f]{64}", lines[0])
    assert "verify_signature" in (ROOT / "scripts/build-android-apk.sh").read_text()
