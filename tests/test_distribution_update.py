"""Distribution upgrades verify identity even when the API version is unchanged."""
import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("distribution_fetch", ROOT / "scripts/github_release_fetch.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)
TAG = "v28.30.0"
ARCHIVE = "remnawave_vpn_shop_v28_30_0_full_release.zip"
MANIFEST = ARCHIVE.removesuffix(".zip") + "_manifest.json"
COMMIT = "a" * 40


def release_fixture(tmp_path, monkeypatch, **overrides):
    installed = tmp_path / "installed"
    (installed / "backend/app").mkdir(parents=True)
    (installed / "backend/app/main.py").write_text('APP_VERSION = "21.5.1"\n')
    stage = tmp_path / "stage"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("backend/app/main.py", 'APP_VERSION = "21.5.1"\n')
        archive.writestr("release-manifest.template.json", json.dumps({"version": "21.5.1", "distribution_tag": TAG}))
    blob = stream.getvalue()
    sha = hashlib.sha256(blob).hexdigest()
    manifest = {"version": "21.5.1", "distribution_tag": TAG, "artifact": ARCHIVE, "sha256": sha, "commit": COMMIT}
    manifest.update(overrides)
    data = {ARCHIVE: blob, ARCHIVE + ".sha256": f"{sha}  {ARCHIVE}\n".encode(), MANIFEST: json.dumps(manifest).encode()}
    release = {"tag_name": TAG, "draft": False, "prerelease": False, "assets": [
        {"name": name, "browser_download_url": f"{updater.DOWNLOAD_PREFIX}{TAG}/{name}"} for name in data
    ]}
    def fetch(url):
        if "/git/ref/tags/" in url:
            return {"object": {"type": "commit", "sha": COMMIT}}
        return release
    monkeypatch.setattr(updater, "fetch_json", fetch)
    monkeypatch.setattr(updater, "download", lambda url: data[url.rsplit("/", 1)[1]])
    monkeypatch.setattr(sys, "argv", ["updater", str(installed), str(stage)])
    monkeypatch.delenv("RELEASE_TAG", raising=False)
    return installed, stage, release


def test_distribution_upgrade_preserves_api_version(tmp_path, monkeypatch):
    _, stage, _ = release_fixture(tmp_path, monkeypatch)
    updater.main()
    assert updater.current_version(stage) == "21.5.1"
    assert updater.current_distribution(stage) == "28.30.0"


@pytest.mark.parametrize("override", [
    {"commit": "b" * 40}, {"sha256": "0" * 64}, {"version": "99.0.0"},
    {"distribution_tag": "v28.31.0"}, {"artifact": "different.zip"}
])
def test_mismatched_detached_manifest_is_rejected(tmp_path, monkeypatch, override):
    release_fixture(tmp_path, monkeypatch, **override)
    with pytest.raises(SystemExit) as error:
        updater.main()
    assert error.value.code == 1


def test_distribution_requires_detached_manifest(tmp_path, monkeypatch):
    _, _, release = release_fixture(tmp_path, monkeypatch)
    release["assets"] = release["assets"][:2]
    with pytest.raises(SystemExit) as error:
        updater.main()
    assert error.value.code == 1


def test_current_distribution_does_not_stage_same_release(tmp_path, monkeypatch):
    installed, stage, _ = release_fixture(tmp_path, monkeypatch)
    (installed / "release-manifest.template.json").write_text(json.dumps({"version": "21.5.1", "distribution_tag": TAG}))
    with pytest.raises(SystemExit) as error:
        updater.main()
    assert error.value.code == 0
    assert not stage.exists()


def test_status_uses_distribution_and_requires_its_manifest():
    from app.github_update import release_status, DOWNLOAD_PREFIX
    names = [ARCHIVE, ARCHIVE + ".sha256", MANIFEST]
    payload = {"tag_name": TAG, "assets": [{"name": name, "browser_download_url": f"{DOWNLOAD_PREFIX}{TAG}/{name}"} for name in names]}
    assert release_status("21.5.1", payload, "v28.0.0")["update_available"]
    assert not release_status("21.5.1", payload, TAG)["update_available"]
    payload["assets"].pop()
    assert not release_status("21.5.1", payload, "v28.0.0")["update_available"]


@pytest.mark.parametrize("flag", ["draft", "prerelease"])
def test_status_does_not_advertise_unpublished_or_preview_distribution(flag):
    from app.github_update import release_status, DOWNLOAD_PREFIX
    names = [ARCHIVE, ARCHIVE + ".sha256", MANIFEST]
    payload = {"tag_name": TAG, flag: True, "assets": [{"name": name, "browser_download_url": f"{DOWNLOAD_PREFIX}{TAG}/{name}"} for name in names]}
    assert not release_status("21.5.1", payload, "v28.0.0")["update_available"]
