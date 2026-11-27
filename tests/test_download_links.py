"""v28.77.0: permanent download links (releases/latest/download/<name>) point to names the release build produces."""
import json
import os
import re
import runpy
import subprocess
import urllib.request
from pathlib import Path

import pytest

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
    pattern = re.search(r"/\^corgi-lusi-\(\?:android\(\?:-admin\)\?\|client\)\\\.apk\(\?:\\\.sha256\)\?\$", workflow)
    assert pattern, "mobile-release.yml must attach the permanent APK names"
    assert "^corgi-lusi-client\\.json$" in workflow and "corgi-lusi-client.json" in workflow, "the client's update manifest"
    assert "^corgi-lusi-android(?:-admin)?\\.json$" in workflow, "update manifests of the shop and admin apps"
    script = (ROOT / "scripts/build-android-apk.sh").read_text()
    assert '"$OUT/${stable%.apk}.json"' in script and '"versionCode":%s' in script, "the build writes those manifests"
    # «Build mobile apps for a release» replaces the stable APKs after the release: it must replace their manifests too,
    # otherwise the SHA-256 in the manifest is of another build and the apps refuse the download.
    rebuild = (ROOT / ".github/workflows/build-mobile.yml").read_text()
    assert "*.sha256 corgi-lusi-android.json corgi-lusi-android-admin.json" in rebuild


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


@pytest.mark.parametrize("label", ["Signer #1", "V2 Signer:", "V3 Signer:", "V3.1 Signer:"])
def test_release_certificate_digest_from_android_build_tools(label):
    parse = runpy.run_path(str(ROOT / "scripts/mobile/apk-signer-digest.py"))["signer_digest"]
    expected = "ab" * 32
    report = (f"Number of signers: 1\n{label} public key SHA-256 digest: {'cd' * 32}\n"
              f"{label} certificate SHA-256 digest: {expected.upper()}\n"
              f"Source Stamp Signer certificate SHA-256 digest: {'ef' * 32}\n")
    assert parse(report) == expected
    assert parse(report + f"V3 Signer: certificate SHA-256 digest: {expected}\n") == expected


@pytest.mark.parametrize("report", [
    "Number of signers: 1\nSource Stamp Signer certificate SHA-256 digest: " + "ab" * 32,
    "Number of signers: 1\nV2 Signer: public key SHA-256 digest: " + "ab" * 32,
    "Number of signers: 1\nSigner #1 certificate SHA-256 digest: 00",
    "Number of signers: 2\nSigner #1 certificate SHA-256 digest: " + "ab" * 32,
    "Number of signers: 1\nV2 Signer: certificate SHA-256 digest: " + "ab" * 32
    + "\nV3 Signer: certificate SHA-256 digest: " + "cd" * 32,
])
def test_release_certificate_requires_an_unambiguous_signer(report):
    parse = runpy.run_path(str(ROOT / "scripts/mobile/apk-signer-digest.py"))["signer_digest"]
    with pytest.raises(ValueError):
        parse(report)


@pytest.mark.parametrize("pin", [" : ", "ab12"])
def test_signed_build_rejects_a_missing_or_malformed_pin_before_gradle(tmp_path, pin):
    sdk = tmp_path / "sdk"
    (sdk / "platforms/android-35").mkdir(parents=True)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/build-android-apk.sh"), str(tmp_path / "out")],
        env={**os.environ, "ANDROID_HOME": str(sdk), "ANDROID_BUILD_MODE": "auto",
             "ANDROID_KEYSTORE": str(tmp_path / "unused.jks"), "ANDROID_SIGNING_CERT_SHA256": pin,
             "GRADLE_BIN": "/bin/false", "CORGI_SHOP_URL": "https://shop.example.test"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "Expected a SHA-256 signing certificate pin" in result.stderr


def test_mobile_packages_are_built_for_every_head_of_main():
    """The release belongs to the head of main: the packages must be built for it whatever files the last commit touched.

    v28.119.0 was published without the client and the update manifests because a CI-only commit became the head
    and the paths filter skipped «Mobile packages» for it.
    """
    import yaml

    triggers = yaml.safe_load((ROOT / ".github/workflows/mobile-release.yml").read_text())[True]
    assert triggers["push"] == {"branches": ["main"]}
    packaging_scripts = {
        "scripts/build-android-apk.sh",
        "scripts/mobile/apk-signer-digest.py",
        "scripts/mobile/build-xray-aar.sh",
        "scripts/mobile/xray-artifact.py",
    }
    assert packaging_scripts.issubset(triggers["pull_request"]["paths"])


class _RedirectRecorder(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        self.locations: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.locations.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _latest_release() -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "shop-by-boo-release-link-audit"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        "https://api.github.com/repos/booarkz-cpu/shop-by-boo/releases/latest",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _resolve_permanent_download(url: str) -> tuple[int, str, list[str]]:
    recorder = _RedirectRecorder()
    opener = urllib.request.build_opener(recorder)
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "shop-by-boo-release-link-audit"})
    with opener.open(request, timeout=60) as response:
        return response.status, response.geturl(), recorder.locations


@pytest.mark.skipif(os.environ.get("RUN_LIVE_RELEASE_LINK_CHECK") != "1", reason="explicit live GitHub check")
def test_live_readme_mobile_links_match_latest_published_release():
    """REQ-QA-0031: documentation links resolve to real, non-empty, digest-addressed release assets."""
    docs = [ROOT / "README.md", ROOT / "README.en.md", ROOT / "README.uk.md", *sorted((ROOT / "docs/wiki").glob("*/Mobile.md"))]
    documented = {name for doc in docs for name in LINK.findall(doc.read_text())}
    assert documented == _produced()

    release = _latest_release()
    assert not release["draft"] and not release["prerelease"]
    assert re.fullmatch(r"v[0-9]+(?:\.[0-9]+){2}", release["tag_name"])
    assets = {asset["name"]: asset for asset in release["assets"]}

    for name in sorted(documented):
        asset = assets[name]
        assert asset["size"] > 0
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", asset["digest"])
        permanent = f"https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/{name}"
        status, final_url, redirects = _resolve_permanent_download(permanent)
        assert status == 200
        assert redirects, f"{permanent} did not redirect to a versioned release asset"
        assert redirects[0] == asset["browser_download_url"]
        assert final_url != permanent
