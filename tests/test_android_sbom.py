"""Regression tests for the Android release graph, licence check and local AAR attribution."""
import copy
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "scripts/ci/android-sbom.py"))
AAR = Path("/example/shared/libv2ray.aar")
COMMIT = "a" * 40


def inputs(product="vpn-shop"):
    app = MODULE["PRODUCTS"][product]
    bom = {"bomFormat": "CycloneDX", "specVersion": "1.7",
           "metadata": {"component": {"type": "application", "bom-ref": "app", "name": app, "version": "1"}},
           "components": [{"type": "library", "bom-ref": ref, "group": "example.group", "name": ref, "version": "1",
                           "licenses": [{"license": {"id": "Apache-2.0"}}]} for ref in ("api", "runtime")],
           "dependencies": [{"ref": "app", "dependsOn": ["api"]}, {"ref": "api", "dependsOn": ["runtime"]}]}
    model = {"applicationId": app, "version": "1", "files": [] if product == "lucy-admin" else [str(AAR)],
             "edges": {"@app": ["example.group:api:1"], "example.group:api:1": ["example.group:runtime:1"],
                       "example.group:runtime:1": []}}
    return bom, model


@pytest.mark.parametrize("product", MODULE["PRODUCTS"])
def test_products_preserve_direct_transitive_and_shared_engine(product):
    bom, model = inputs(product)
    source, edges = MODULE["android_graph"](product, bom, model, AAR)
    edges = {row["ref"]: row["dependsOn"] for row in edges}
    api, runtime = [item["bom-ref"] for item in source["components"]]
    assert api in edges[source["bom-ref"]]
    assert edges[api] == [runtime]
    assert (MODULE["ENGINE_REF"] in edges[source["bom-ref"]]) == (product != "lucy-admin")
    assert bom["metadata"]["component"]["bom-ref"] == "app"


@pytest.mark.parametrize("defect", ["component", "edge", "duplicate", "unresolved", "foreign", "files", "amount", "identity",
                                    "licence", "unknown", "empty", "strong"])
def test_incomplete_or_unlicensed_release_is_rejected(defect):
    bom, model = inputs()
    if defect == "component":
        bom["components"].pop()
    elif defect == "edge":
        bom["dependencies"].pop()
    elif defect == "duplicate":
        bom["components"].append(bom["components"][0])
    elif defect == "unresolved":
        bom["dependencies"][0]["dependsOn"].append("absent")
    elif defect == "foreign":
        bom["dependencies"].append({"ref": "other"})
    elif defect == "files":
        model["files"].append("/tmp/untracked.aar")
    elif defect == "amount":
        model["edges"]["example.group:another:1"] = []
    elif defect == "identity":
        model["applicationId"] = "another.product"
    else:
        licence = {"licence": "GPL-3.0-only", "unknown": "NOASSERTION", "strong": "Apache-2.0 AND GPL-3.0-only"}.get(defect)
        bom["components"][0]["licenses"] = [{"expression": licence}] if licence else []
    with pytest.raises(ValueError):
        MODULE["android_graph"]("vpn-shop", bom, model, AAR)


def test_two_apps_cannot_shadow_each_others_gradle_refs():
    ids = []
    for product in MODULE["PRODUCTS"]:
        app, _ = MODULE["android_graph"](product, *inputs(product), AAR)
        ids.extend(c["bom-ref"] for c in [app, *app["components"]])
    assert len(ids) == len(set(ids))


def test_repository_retains_original_components_and_links_all_three_apps(monkeypatch):
    repo = {"metadata": {"component": {"bom-ref": "root"}}, "components": [{"bom-ref": "web"}],
            "dependencies": [{"ref": "root", "dependsOn": ["web"]}], "vulnerabilities": [{"id": "example"}]}
    native = [{"type": "file", "bom-ref": MODULE["ENGINE_REF"], "name": "libv2ray.aar"}]
    combine = MODULE["combine"]
    monkeypatch.setitem(combine.__globals__, "engine_inventory", lambda aar, commit: (native, []))
    output = combine(repo, {p: inputs(p) for p in MODULE["PRODUCTS"]}, AAR, COMMIT)
    refs = {f"corgi:android:{p}:app" for p in MODULE["PRODUCTS"]}
    assert set(output["dependencies"][0]["dependsOn"]) == refs | {"web"}
    assert output["components"][0]["bom-ref"] == "web"
    assert output["components"].count(native[0]) == 1
    assert output["vulnerabilities"] == [{"id": "example"}]


def test_manifest_requires_all_apps():
    with pytest.raises(ValueError, match="all three"):
        MODULE["combine"]({}, {"vpn-shop": inputs()}, AAR, COMMIT)


def test_pom_licence_names_and_spdx_choices():
    check = MODULE["check_licenses"]
    for value in ("GNU Lesser General Public License v3.0", "GNU Library General Public License"):
        check({"name": "example", "licenses": [{"license": {"name": value}}]})
    for value in ("GPL-3.0-only OR Apache-2.0", "MIT OR (GPL-3.0-only AND AGPL-3.0-only)"):
        check({"name": "example", "licenses": [{"expression": value}]})
    for value in ("(MIT OR GPL-3.0-only) AND AGPL-3.0-only", "MIT OR", "(MIT"):
        with pytest.raises(ValueError):
            check({"name": "example", "licenses": [{"expression": value}]})
    with pytest.raises(ValueError, match="review Android licence"):
        check({"name": "example", "licenses": [{"license": {"name": "GNU General Public License version 3"}}]})


def test_native_modules_use_embedded_version_and_preserve_go_checksum():
    deps = [{"Path": "github.com/2dust/AndroidLibXrayLite", "Version": "v0.0.0", "Replace": {"Path": "/tmp/engine", "Version": "(devel)"}},
            {"Path": "github.com/xtls/xray-core", "Version": "v1", "Sum": "h1:example"}]
    modules = MODULE["go_modules"]({"Deps": deps}, COMMIT)
    wrapper, xray = modules.values()
    assert wrapper["version"] == COMMIT
    assert wrapper["externalReferences"][0]["url"].endswith(COMMIT)
    assert xray["properties"][0]["value"] == "h1:example"
    assert xray["licenses"][0]["license"]["id"] == "MPL-2.0"
    for changed in (deps[:1], [*deps, deps[-1]], [*deps, {"Path": "local/unpinned", "Version": "(devel)"}]):
        with pytest.raises(ValueError):
            MODULE["go_modules"]({"Deps": copy.deepcopy(changed)}, COMMIT)


def test_go_source_evidence_preserves_unmodified_terms_and_ancillary_notices(tmp_path):
    import base64
    import hashlib
    from zipfile import ZipFile

    source = tmp_path / "module.zip"
    files = {"LICENSE": b"Licence including a special exception.\r\n", "NOTICE": b"Attribution\n",
             "sub/COPYING": b"Additional terms.\n", "license_test.go": b"package demo\n",
             "LICENSES/generate.py": b"print('generator')\n"}
    prefix = "example.com/demo@v1.0.0/"
    with ZipFile(source, "w") as archive:
        for path, data in reversed(list(files.items())):
            archive.writestr(prefix + path, data)
    lines = [hashlib.sha256(data).hexdigest() + "  " + prefix + path + "\n" for path, data in sorted(files.items())]
    expected = "h1:" + base64.b64encode(hashlib.sha256("".join(lines).encode()).digest()).decode()
    evidence, properties = MODULE["go_source_evidence"](source, prefix, expected)
    assert {x["license"]["name"]: base64.b64decode(x["license"]["text"]["content"]) for x in evidence} == {
        path: files[path] for path in ("LICENSE", "sub/COPYING")
    }
    assert {p["name"]: p["value"] for p in properties} == {
        f"go:source-file:sha256:{path}": hashlib.sha256(files[path]).hexdigest()
        for path in ("LICENSE", "NOTICE", "sub/COPYING")
    }
    with pytest.raises(ValueError, match="checksum"):
        MODULE["go_source_evidence"](source, prefix, "h1:unrelated")
    with ZipFile(source, "a") as archive:
        archive.writestr(prefix + "extra.go", "package demo\n")
    with pytest.raises(ValueError, match="checksum"):
        MODULE["go_source_evidence"](source, prefix, expected)


@pytest.mark.parametrize("change,wrapper,error", [
    ({"Path": "other.example/module"}, False, "source module"),
    ({"Version": "v1.0.1"}, False, "source version"),
    ({"Sum": "h1:different"}, False, "checksum"),
    ({"Origin": {"Hash": "b" * 40}}, True, "wrapper revision"),
])
def test_go_source_lookup_rejects_mismatched_provenance(monkeypatch, change, wrapper, error):
    import json

    name = "github.com/2dust/AndroidLibXrayLite" if wrapper else "example.com/demo"
    component = {"name": name, "version": COMMIT if wrapper else "v1.0.0",
                 "properties": [{"name": "go:module:h1", "value": "h1:expected"}]}

    def output(*args, **kwargs):
        return json.dumps({"Path": name, "Version": "v1.0.0", "Sum": "h1:expected",
                           "Origin": {"Hash": COMMIT}, **change})

    monkeypatch.setattr(MODULE["subprocess"], "check_output", output)
    with pytest.raises(ValueError, match=error):
        MODULE["add_go_license_evidence"](component, COMMIT)


@pytest.mark.parametrize("damage", ["repository-only", "detached", "missing-engine", "missing-abi", "no-maven"])
def test_packaging_requires_all_android_apps_and_native_links(damage):
    validator = runpy.run_path(str(ROOT / "scripts/ci/check-sbom.py"))
    shared = MODULE["ENGINE_REF"]
    abis = {f"{shared}/{abi}" for abi in MODULE["XRAY"]["ABIS"]}
    apps = [{"type": "application", "name": name, "bom-ref": product,
             "components": [{"purl": "pkg:maven/example/lib@1", "bom-ref": product + "-lib"}]}
            for product, name in MODULE["PRODUCTS"].items()]
    files = [{"type": "file", "bom-ref": ref} for ref in [shared, *sorted(abis)]]
    links = [{"ref": "root", "dependsOn": [app["bom-ref"] for app in apps]},
             {"ref": shared, "dependsOn": sorted(abis)}]
    for product in MODULE["PRODUCTS"]:
        links.append({"ref": product, "dependsOn": [product + "-lib"] + ([] if product == "lucy-admin" else [shared])})
    bom = {"bomFormat": "CycloneDX", "specVersion": "1.7", "metadata": {"component": {"bom-ref": "root"}},
           "components": apps + files, "dependencies": links}
    validator["require_release_inventory"](bom)
    if damage == "repository-only":
        bom["components"] = files
    elif damage == "detached":
        links[0]["dependsOn"].pop()
    elif damage == "missing-engine":
        links[2]["dependsOn"].remove(shared)
    elif damage == "missing-abi":
        links[1]["dependsOn"].pop()
    else:
        apps[0]["components"] = []
    with pytest.raises(ValueError):
        validator["require_release_inventory"](bom)
