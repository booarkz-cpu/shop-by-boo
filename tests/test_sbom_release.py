"""The release SBOM contains the repository and every Android dependency graph."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest
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


def test_sbom_plugin_classpath_uses_the_central_mirror_for_transitive_modules():
    script = (ROOT / "scripts/ci/android-sbom.gradle").read_text()
    repositories = script.split("initscript {", 1)[1].split("dependencies {", 1)[0]
    mirror = "https://maven-central.storage-download.googleapis.com/maven2/"
    assert mirror in repositories
    assert repositories.index(mirror) < repositories.index("mavenCentral()")
    portal = repositories.split("gradlePluginPortal {", 1)[1].split("}", 1)[0]
    assert "content {" in portal
    assert set(re.findall(r"includeModule\('([^']+)', '([^']+)'\)", portal)) == {
        ("org.cyclonedx.bom", "org.cyclonedx.bom.gradle.plugin"),
        ("org.cyclonedx", "cyclonedx-gradle-plugin"),
    }


def test_ci_builds_full_android_sbom_and_release_downloads_exact_ci_artifact():
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = ci["jobs"]["release-sbom"]
    run = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "org.cyclonedx.bom.gradle.plugin:3.6.1" in (ROOT / "scripts/ci/android-sbom.gradle").read_text()
    assert 'for product in vpn-shop vpn-client lucy-admin' in run and '"apps/$product/android"' in run
    assert "android-sbom.py" in run and "check-sbom.py --release" in run
    assert "release-sbom" in ci["jobs"]["gate"]["needs"]
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
    assert download["with"]["digest-mismatch"] == "error"
    assert any("--sbom-checksum" in step.get("run", "") for step in release["jobs"]["release"]["steps"])


def test_scanner_identity_is_stable_and_vulnerability_targets_follow_components():
    builder = load_script()
    def scan(root_ref, package_ref, vuln_ref):
        document = bom({"type": "application", "name": "release", "version": "123", "bom-ref": root_ref},
                       [component(package_ref, "dep", "1", "pkg:npm/dep@1", "MIT")],
                       [{"ref": root_ref, "dependsOn": [package_ref]}])
        document["metadata"]["tools"] = {"components": [{"type": "application", "name": "trivy"}]}
        document["vulnerabilities"] = [{"id": "test-advisory", "bom-ref": vuln_ref,
                                        "affects": [{"ref": package_ref}]}]
        return document

    first = builder.merge_documents([scan("run1", "dep1", "vuln1")], source_date_epoch=1)
    second = builder.merge_documents([scan("run2", "dep2", "vuln2")], source_date_epoch=1)
    assert first == second
    assert first["vulnerabilities"][0]["affects"][0]["ref"] == first["components"][0]["bom-ref"]
    assert first["metadata"]["tools"]["components"][0]["name"] == "trivy"
    broken = scan("run", "dep", "vuln")
    broken["dependencies"][0]["dependsOn"].append("unresolved")
    with pytest.raises(ValueError, match="unresolved CycloneDX dependency"):
        builder.merge_documents([broken], source_date_epoch=1)


def test_reordered_scanner_aliases_do_not_change_the_release_identity():
    builder = load_script()
    purl = "pkg:pypi/sqlalchemy@2.1.9"
    aliases = [component("id-one", "SQLAlchemy", "2.1.9", purl, "MIT"),
               component("id-two", "sqlalchemy", "2.1.9", purl, "MIT")]
    root = {"type": "application", "name": "repo", "bom-ref": "repository"}
    edges = [{"ref": "repository", "dependsOn": ["id-one", "id-two"]}]
    result = builder.merge_documents([bom(root, aliases, edges)], source_date_epoch=1)
    assert len(result["components"]) == 1
    assert builder.merge_documents([bom(root, aliases[::-1], edges)], source_date_epoch=1) == result



def test_equal_package_versions_preserve_distinct_resolved_dependencies():
    builder = load_script()

    def scan(prefix):
        def ref(name):
            return prefix + name

        apps = [{"type": "application", "name": f"{name}/package-lock.json", "bom-ref": ref(name)}
                for name in ("admin", "cabinet")]
        components = list(apps)
        edges = [{"ref": ref("repo"), "dependsOn": [app["bom-ref"] for app in apps]}]
        for name in ("admin", "cabinet"):
            for package in ("wrapper", "next", "react"):
                components.append(component(ref(name + package), package, "1", f"pkg:npm/{package}@1"))
            edges.append({"ref": ref(name), "dependsOn": [ref(name + "wrapper")]})
            edges.append({"ref": ref(name + "wrapper"), "dependsOn": [ref(name + "next")]})
            children = [ref(name + "react"), ref(name + "wrapper")]
            if name == "admin":
                children.append(ref("playwright"))
            edges.append({"ref": ref(name + "next"), "dependsOn": children})
        components.append(component(ref("playwright"), "playwright", "1", "pkg:npm/playwright@1"))
        report = bom({"type": "application", "name": "repo", "bom-ref": ref("repo")}, components, edges)
        report["vulnerabilities"] = [{"id": "sample", "affects": [{"ref": ref("adminnext")}]}]
        return report

    report = builder.merge_documents([scan("first-")], source_date_epoch=1)
    reordered = scan("fresh-")
    reordered["components"].reverse()
    reordered["dependencies"].reverse()
    assert builder.merge_documents([reordered], source_date_epoch=1) == report

    nodes = {item["bom-ref"]: item for item in report["components"]}
    links = {row["ref"]: row["dependsOn"] for row in report["dependencies"]}
    next_refs = {}
    for app in ("admin", "cabinet"):
        manifest, = [ref for ref, item in nodes.items() if item["name"] == f"{app}/package-lock.json"]
        wrapper, = links[manifest]
        next_ref, = links[wrapper]
        next_refs[app] = next_ref
        children = {nodes[child]["name"] for child in links[next_ref]}
        assert children == ({"react", "wrapper", "playwright"} if app == "admin" else {"react", "wrapper"})
        assert wrapper in links[next_ref]
    assert next_refs["admin"] != next_refs["cabinet"]
    assert report["vulnerabilities"][0]["affects"] == [{"ref": next_refs["admin"]}]
    assert sum(item["name"] == "react" for item in nodes.values()) == 1
