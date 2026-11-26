"""The release SBOM contains the repository and every Android dependency graph."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ci/merge-cyclonedx.py"


def load_script():
    spec = importlib.util.spec_from_file_location("merge_cyclonedx", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def bom(component, components, dependencies):
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:random-input-is-removed",
        "version": 1,
        "metadata": {"timestamp": "2026-01-01T00:00:00Z", "component": component},
        "components": components,
        "dependencies": dependencies,
    }


def component(ref, name, version, purl, license_id=None):
    value = {"type": "library", "bom-ref": ref, "name": name, "version": version, "purl": purl}
    if license_id:
        value["licenses"] = [{"license": {"id": license_id}}]
    return value


def test_merge_is_deterministic_and_preserves_android_relationships_and_licenses(tmp_path):
    base = bom(
        {"type": "application", "bom-ref": "repo", "name": "shop-by-boo", "version": "28.161.0"},
        [component("base-okhttp", "okhttp", "5.3.2", "pkg:maven/com.squareup.okhttp3/okhttp@5.3.2")],
        [{"ref": "repo", "dependsOn": ["base-okhttp"]}],
    )
    android = bom(
        {"type": "application", "bom-ref": "app", "name": "vpn-client", "version": "1.10.1"},
        [
            component("android-okhttp", "okhttp", "5.3.2", "pkg:maven/com.squareup.okhttp3/okhttp@5.3.2", "Apache-2.0"),
            component("coroutines", "kotlinx-coroutines-android", "1.11.0", "pkg:maven/org.jetbrains.kotlinx/kotlinx-coroutines-android@1.11.0", "Apache-2.0"),
        ],
        [
            {"ref": "app", "dependsOn": ["android-okhttp", "coroutines"]},
            {"ref": "android-okhttp", "dependsOn": ["coroutines"]},
        ],
    )
    base_path, android_path = tmp_path / "base.json", tmp_path / "android.json"
    base_path.write_text(json.dumps(base))
    android_path.write_text(json.dumps(android))
    output = tmp_path / "sbom.cdx.json"

    module = load_script()
    module.merge([base_path, android_path], output, source_date_epoch=1_795_669_414)
    first = output.read_bytes()
    module.merge([android_path, base_path], output, source_date_epoch=1_795_669_414)
    assert output.read_bytes() == first

    merged = json.loads(first)
    assert merged["bomFormat"] == "CycloneDX" and merged["specVersion"] == "1.6"
    assert merged["serialNumber"].startswith("urn:uuid:")
    assert merged["metadata"]["timestamp"] == "2026-11-26T05:03:34Z"
    by_purl = {item.get("purl"): item for item in merged["components"] if item.get("purl")}
    assert set(by_purl) == {
        "pkg:maven/com.squareup.okhttp3/okhttp@5.3.2",
        "pkg:maven/org.jetbrains.kotlinx/kotlinx-coroutines-android@1.11.0",
    }
    assert by_purl["pkg:maven/com.squareup.okhttp3/okhttp@5.3.2"]["licenses"] == [
        {"license": {"id": "Apache-2.0"}}
    ]
    refs = {item["bom-ref"] for item in merged["components"]}
    refs.add(merged["metadata"]["component"]["bom-ref"])
    assert all(edge["ref"] in refs for edge in merged["dependencies"])
    assert all(set(edge["dependsOn"]) <= refs for edge in merged["dependencies"])

    checksum = output.with_suffix(output.suffix + ".sha256")
    assert checksum.read_text() == f"{hashlib.sha256(first).hexdigest()}  sbom.cdx.json\n"


def test_ci_builds_full_android_sbom_and_release_downloads_exact_ci_artifact():
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = ci["jobs"]["sbom"]
    run = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "org.cyclonedx.bom.gradle.plugin:3.6.1" in (ROOT / "scripts/ci/cyclonedx.init.gradle.kts").read_text()
    for project in ("apps/vpn-shop/android", "apps/vpn-client/android", "apps/lucy-admin/android"):
        assert project in run
    assert "merge-cyclonedx.py" in run and "sha256" in run
    upload = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/upload-artifact@"))
    assert upload["with"]["if-no-files-found"] == "error"
    paths = upload["with"]["path"].splitlines()
    assert any(path.endswith("/sbom.cdx.json") for path in paths)
    assert any(path.endswith("/sbom.cdx.json.sha256") for path in paths)

    release = yaml.safe_load((ROOT / ".github/workflows/publish-release.yml").read_text())
    download = next(step for step in release["jobs"]["release"]["steps"]
                    if str(step.get("uses", "")).startswith("actions/download-artifact@"))
    assert download["with"]["name"] == "sbom"
    assert download["with"]["run-id"] == "${{ steps.gate.outputs.ci_run_id }}"
    assert download["with"]["github-token"] == "${{ github.token }}"
