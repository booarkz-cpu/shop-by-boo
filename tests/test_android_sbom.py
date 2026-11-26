"""Regression tests for the Android release graph, licence check and local AAR attribution."""
import base64
import copy
import hashlib
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "scripts/ci/android-sbom.py"))
AAR = Path("/example/shared/libv2ray.aar")
COMMIT = "a" * 40
SOURCE_REVISION = "b" * 40


def test_inventory_summary_counts_nested_components_and_excludes_the_root(tmp_path, capsys):
    import json

    validator = runpy.run_path(str(ROOT / "scripts/ci/check-sbom.py"))
    product = {
        "type": "application", "name": "mobile", "bom-ref": "mobile",
        "components": [{"type": "library", "name": f"runtime-{i}"} for i in range(100)],
    }
    bom = {
        "bomFormat": "CycloneDX", "specVersion": "1.7", "version": 1,
        "metadata": {"component": {"type": "application", "name": "shop"}},
        "components": [{"type": "application", "name": "distribution", "components": [product]}],
    }
    path = tmp_path / "sbom.cdx.json"
    path.write_text(json.dumps(bom))
    validator["main"](path)
    assert "102 components" in capsys.readouterr().out
    del product["components"][-2:]
    path.write_text(json.dumps(bom))
    with pytest.raises(SystemExit, match="only 100 components"):
        validator["main"](path)


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
    repo = {"metadata": {"component": {"bom-ref": "root", "name": "/temporary/scan/path"}}, "components": [{"bom-ref": "web"}],
            "dependencies": [{"ref": "root", "dependsOn": ["web"]}], "vulnerabilities": [{"id": "example"}]}
    native = [{"type": "file", "bom-ref": MODULE["ENGINE_REF"], "name": "libv2ray.aar"}]
    combine = MODULE["combine"]
    monkeypatch.setitem(combine.__globals__, "engine_inventory", lambda aar, commit: (native, []))
    output = combine(repo, {p: inputs(p) for p in MODULE["PRODUCTS"]}, AAR, COMMIT, SOURCE_REVISION)
    root = output["metadata"]["component"]
    assert (root["bom-ref"], root["name"], root["version"]) == ("root", "VPN Shop by Corgi Lucy", SOURCE_REVISION)
    refs = {f"corgi:android:{p}:app" for p in MODULE["PRODUCTS"]}
    assert set(output["dependencies"][0]["dependsOn"]) == refs | {"web"}
    assert output["components"][0]["bom-ref"] == "web"
    assert output["components"].count(native[0]) == 1
    assert output["vulnerabilities"] == [{"id": "example"}]


def test_manifest_requires_all_apps():
    with pytest.raises(ValueError, match="all three"):
        MODULE["combine"]({}, {"vpn-shop": inputs()}, AAR, COMMIT, SOURCE_REVISION)


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


def test_native_inventory_rejects_the_unfixed_websocket_dependency():
    module = "github.com/gorilla/websocket"
    core = {"Path": "github.com/xtls/xray-core", "Version": "v1.0.0", "Sum": "h1:core"}
    wrapper = {"Path": "github.com/2dust/AndroidLibXrayLite", "Replace": {
        "Path": "../../wrapper", "Version": "(devel)"}}
    unfixed = {"Path": module, "Version": "v1.5.3", "Sum": "h1:old"}
    with pytest.raises(ValueError, match="GO-2026-6278"):
        MODULE["go_modules"]({"Deps": [wrapper, core, unfixed]}, COMMIT)
    fixed = {"Path": module, "Version": "v1.5.4-0.20240701034025-d67f41855da4",
             "Sum": "h1:PYKzliEgITjLJoJqbV90S0YRaG8LNAsICH6fp6MApC0="}
    graph = MODULE["go_modules"]({"Deps": [wrapper, core, fixed]}, COMMIT)
    record = graph[f"pkg:golang/{module}@{fixed['Version']}"]
    assert {"name": "go:module:h1", "value": fixed["Sum"]} in record["properties"]


def test_go_source_evidence_preserves_unmodified_terms_and_ancillary_notices(tmp_path):
    from zipfile import ZipFile

    source = tmp_path / "module.zip"
    files = {"LICENSE": b"Licence including a special exception.\r\n", "NOTICE": b"Attribution\r\n",
             "third_party/COPYRIGHT.txt": "Autoren ©\n".encode(), "PATENTS": b"Patent grant\n",
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
    props = {p["name"]: p["value"] for p in properties}
    notice_paths = ("NOTICE", "third_party/COPYRIGHT.txt", "PATENTS")
    expected_props = {f"go:source-file:sha256:{path}": hashlib.sha256(files[path]).hexdigest()
                      for path in ("LICENSE", "sub/COPYING", *notice_paths)}
    expected_props.update({f"go:notice:base64:{path}": base64.b64encode(files[path]).decode("ascii")
                           for path in notice_paths})
    assert props == expected_props
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


def release_inventory():
    shared = MODULE["ENGINE_REF"]
    abis = {f"{shared}/{abi}" for abi in MODULE["XRAY"]["ABIS"]}
    apps = [{"type": "application", "name": name, "bom-ref": product,
             "components": [{"type": "library", "name": dep, "purl": f"pkg:maven/example/{dep}@1",
                             "licenses": [{"license": {"id": "Apache-2.0"}}], "bom-ref": f"{product}-{dep}"}
                            for dep in ("lib", "transitive")]}
            for product, name in MODULE["PRODUCTS"].items()]
    files = [{"type": "file", "name": ref.split("/")[-1], "bom-ref": ref,
              "hashes": [{"alg": "SHA-256", "content": "1" * 64}]} for ref in [shared, *sorted(abis)]]
    modules = []
    for name in ("github.com/2dust/AndroidLibXrayLite", "github.com/xtls/xray-core", "example.org/arch"):
        purl = f"pkg:golang/{name}@v1.0.0"
        modules.append({"type": "library", "name": name, "purl": purl, "bom-ref": purl,
                        "evidence": {"licenses": [{"license": {"name": "LICENSE", "text": {
                            "contentType": "text/plain", "encoding": "base64", "content": "VGVybXM="}}}]},
                        "properties": [{"name": "go:source-file:sha256:LICENSE", "value": hashlib.sha256(b"Terms").hexdigest()},
                                       {"name": "go:source-file:sha256:NOTICE", "value": hashlib.sha256(b"Credit").hexdigest()},
                                       {"name": "go:notice:base64:NOTICE", "value": "Q3JlZGl0"}],
                        "externalReferences": [{"type": "distribution", "url": "https://example.org/module.zip",
                                                "hashes": [{"alg": "SHA-256", "content": "2" * 64}]}]})
    links = [{"ref": "root", "dependsOn": [app["bom-ref"] for app in apps]},
             {"ref": shared, "dependsOn": sorted(abis)}]
    for product in MODULE["PRODUCTS"]:
        links.append({"ref": product, "dependsOn": [product + "-lib"] + ([] if product == "lucy-admin" else [shared])})
    for product in MODULE["PRODUCTS"]:
        links.append({"ref": product + "-lib", "dependsOn": [product + "-transitive"]})
    for abi in sorted(abis):
        linked = modules if abi.endswith("/arm64-v8a") else modules[:2]
        links.append({"ref": abi, "dependsOn": [module["bom-ref"] for module in linked]})
    repository = []
    for ecosystem, manifests in {
        "npm": ["apps/user-cabinet/package-lock.json", "apps/lucy-admin/web/package-lock.json"],
        "pypi": ["services/backend/requirements.txt", "services/support-pro/requirements.txt"],
    }.items():
        # Both applications can depend on the same package and its transitive dependency.
        package = f"pkg:{ecosystem}/shared@1"
        child = f"pkg:{ecosystem}/child@1"
        for ref in (package, child):
            repository.append({"type": "library", "name": ref, "bom-ref": ref, "purl": ref})
        links.append({"ref": package, "dependsOn": [child]})
        for manifest in manifests:
            repository.append({"type": "application", "name": manifest, "bom-ref": manifest})
            links[0]["dependsOn"].append(manifest)
            links.append({"ref": manifest, "dependsOn": [package]})
    root = {"type": "application", "bom-ref": "root", "name": "VPN Shop by Corgi Lucy", "version": SOURCE_REVISION}
    return {"bomFormat": "CycloneDX", "specVersion": "1.7", "version": 1, "metadata": {"component": root},
            "components": apps + files + modules + repository, "dependencies": links}


@pytest.mark.parametrize("damage", ["repository-only", "detached", "missing-engine", "missing-abi", "no-maven",
                                    "wrong-commit", "missing-commit", "scan-path"])
def test_packaging_requires_all_android_apps_and_native_links(damage):
    validator = runpy.run_path(str(ROOT / "scripts/ci/check-sbom.py"))
    bom = release_inventory()
    root, links = bom["metadata"]["component"], bom["dependencies"]
    shared = MODULE["ENGINE_REF"]
    validator["require_release_inventory"](bom, expected_commit=SOURCE_REVISION)
    if damage == "repository-only":
        bom["components"] = [item for item in bom["components"] if item["bom-ref"] not in MODULE["PRODUCTS"]]
    elif damage == "detached":
        links[0]["dependsOn"].remove("vpn-shop")
    elif damage == "missing-engine":
        links[2]["dependsOn"].remove(shared)
    elif damage == "missing-abi":
        links[1]["dependsOn"].pop()
    elif damage == "no-maven":
        bom["components"][0]["components"] = []
    elif damage == "wrong-commit":
        root["version"] = "c" * 40
    elif damage == "missing-commit":
        del root["version"]
    else:
        root["name"] = "/src"
    with pytest.raises(ValueError):
        validator["require_release_inventory"](bom, expected_commit=SOURCE_REVISION)


@pytest.mark.parametrize("manifest", [
    "services/backend/requirements.txt", "services/support-pro/requirements.txt",
    "apps/lucy-admin/web/package-lock.json", "apps/user-cabinet/package-lock.json",
])
def test_packaging_requires_each_shipped_repository_manifest(manifest):
    bom = release_inventory()
    bom["components"] = [item for item in bom["components"] if item["name"] != manifest]
    bom["dependencies"] = [row for row in bom["dependencies"] if row["ref"] != manifest]
    bom["dependencies"][0]["dependsOn"].remove(manifest)
    with pytest.raises(ValueError, match=manifest):
        MODULE["CONTRACT"]["require_release_inventory"](bom, expected_commit=SOURCE_REVISION)


@pytest.mark.parametrize("prepend", [True, False])
def test_packaging_rejects_conflicting_dependency_records_in_either_order(prepend):
    bom = release_inventory()
    rows = bom["dependencies"]
    engine = next(row for row in rows if row["ref"] == MODULE["ENGINE_REF"])
    conflicting = {"ref": engine["ref"], "dependsOn": engine["dependsOn"][:1]}
    rows.insert(0 if prepend else len(rows), conflicting)
    with pytest.raises(ValueError, match="Duplicate dependency record.*libv2ray"):
        MODULE["CONTRACT"]["require_release_inventory"](bom, expected_commit=SOURCE_REVISION)


@pytest.mark.parametrize("damage", ["detached", "duplicate", "empty", "wrong-ecosystem", "dangling-transitive"])
def test_packaging_requires_connected_repository_graphs(damage):
    bom = release_inventory()
    manifest = "services/backend/requirements.txt"
    links = {row["ref"]: row["dependsOn"] for row in bom["dependencies"]}
    if damage == "detached":
        links["root"].remove(manifest)
    elif damage == "duplicate":
        bom["components"].append({"name": manifest, "type": "application", "bom-ref": "duplicate"})
    elif damage == "empty":
        links[manifest].clear()
    elif damage == "wrong-ecosystem":
        links[manifest][:] = ["pkg:npm/shared@1"]
    else:
        links["pkg:pypi/shared@1"].append("absent-child")
    with pytest.raises(ValueError, match="absent-child" if damage == "dangling-transitive" else manifest):
        MODULE["CONTRACT"]["require_release_inventory"](bom, expected_commit=SOURCE_REVISION)


@pytest.mark.parametrize("damage", [None, "missing", "other-service", "transitive-only", "extra",
                                    "wrong-version", "wrong-purl", "unreadable-pin"])
def test_python_runtime_pins_belong_to_each_service(tmp_path, damage):
    bom = release_inventory()
    backend = "services/backend/requirements.txt"
    support = "services/support-pro/requirements.txt"
    for path, version in ((backend, "8.1.0"), (support, "8.2.0")):
        lock = tmp_path / path
        lock.parent.mkdir(parents=True)
        lock.write_text(f"# runtime pins\nRedis == {version}\nExample_Pkg[asyncio]==2.0+local  # wheel\n")
    rows = {row["ref"]: row["dependsOn"] for row in bom["dependencies"]}
    packages = [
        {"type": "library", "bom-ref": ref, "name": name, "version": version, "purl": purl}
        for ref, name, version, purl in (
            ("old", "redis", "8.1.0", "pkg:pypi/redis@8.1.0"),
            ("new", "redis", "8.2.0", "pkg:pypi/redis@8.2.0"),
            ("common", "Example-Pkg", "2.0+local", "pkg:pypi/example-pkg@2.0%2Blocal"),
        )
    ]
    bom["components"].extend(packages)
    rows[backend][:] = ["old", "common"]
    rows[support][:] = ["new", "common"]
    if damage == "missing":
        rows[support].remove("new")
    elif damage == "other-service":
        rows[support][:] = rows[backend]
    elif damage == "transitive-only":
        rows[support].remove("new")
        bom["dependencies"].append({"ref": "common", "dependsOn": ["new"]})
    elif damage == "extra":
        rows[support].append("old")
    elif damage == "wrong-version":
        packages[1]["version"] = "8.1.0"
    elif damage == "wrong-purl":
        packages[1]["purl"] = "pkg:pypi/unrelated@8.2.0"
    elif damage == "unreadable-pin":
        (tmp_path / support).write_text("-r another-list.txt\n")

    verify = MODULE["CONTRACT"]["require_release_inventory"]
    if damage is None:
        verify(bom, expected_commit=SOURCE_REVISION, source_root=tmp_path)
    else:
        with pytest.raises(ValueError, match=support):
            verify(bom, expected_commit=SOURCE_REVISION, source_root=tmp_path)


@pytest.mark.parametrize("damage", ["unknown-direct", "missing-component", "orphan", "other-product",
                                    "missing-licence", "duplicate-component"])
def test_packaging_rejects_broken_maven_graph(damage):
    bom = release_inventory()
    shop = bom["components"][0]
    direct, transitive = shop["components"]
    links = {row["ref"]: row["dependsOn"] for row in bom["dependencies"]}
    if damage == "unknown-direct":
        links[shop["bom-ref"]].append("absent")
    elif damage == "missing-component":
        shop["components"].remove(transitive)
    elif damage == "orphan":
        links[direct["bom-ref"]].clear()
    elif damage == "other-product":
        links[direct["bom-ref"]].append(bom["components"][1]["components"][0]["bom-ref"])
    elif damage == "missing-licence":
        del transitive["licenses"]
    else:
        shop["components"].append(copy.deepcopy(transitive))
    with pytest.raises(ValueError):
        MODULE["CONTRACT"]["require_release_inventory"](bom, expected_commit=SOURCE_REVISION)


@pytest.mark.parametrize("damage", [
    "aar-hash", "jni-hash", "no-go-dependencies", "missing-wrapper", "missing-core",
    "dangling-module", "lost-license", "unhashed-source",
])
def test_packaging_rejects_incomplete_native_inventory(damage):
    bom = release_inventory()
    shared = MODULE["ENGINE_REF"]
    abi = f"{shared}/arm64-v8a"
    components = {item["bom-ref"]: item for item in bom["components"]}
    links = {row["ref"]: row["dependsOn"] for row in bom["dependencies"]}
    wrapper, core, extra = links[abi]
    if damage == "aar-hash":
        del components[shared]["hashes"]
    elif damage == "jni-hash":
        components[abi]["hashes"] = [{"alg": "SHA-1", "content": "a" * 40}]
    elif damage == "no-go-dependencies":
        links[abi].clear()
    elif damage == "missing-wrapper":
        links[abi].remove(wrapper)
    elif damage == "missing-core":
        links[abi].remove(core)
    elif damage == "dangling-module":
        links[abi].append("absent")
    elif damage == "lost-license":
        del components[extra]["evidence"]
    else:
        del components[extra]["externalReferences"][0]["hashes"]
    with pytest.raises(ValueError):
        MODULE["CONTRACT"]["require_release_inventory"](bom, expected_commit=SOURCE_REVISION)


@pytest.mark.parametrize("damage", ["notice-absent", "notice-changed", "notice-invalid-base64", "licence-changed",
                                    "licence-wrong-encoding", "hash-absent", "duplicate-hash", "duplicate-notice"])
def test_packaging_requires_the_exact_go_licence_and_notice_bytes(damage):
    bom = release_inventory()
    component = next(c for c in bom["components"] if c["name"] == "example.org/arch")
    licence = component["evidence"]["licenses"][0]["license"]
    properties = component["properties"]
    digest, notice_digest, notice = properties
    if damage == "notice-absent":
        properties.remove(notice)
    elif damage == "notice-changed":
        notice["value"] = base64.b64encode(b"Other credit").decode("ascii")
    elif damage == "notice-invalid-base64":
        notice["value"] += "***"
    elif damage == "licence-changed":
        licence["text"]["content"] = notice["value"]
    elif damage == "licence-wrong-encoding":
        del licence["text"]["encoding"]
    elif damage == "hash-absent":
        properties.remove(notice_digest)
    elif damage == "duplicate-hash":
        properties.append(digest.copy())
    else:
        properties.append(notice.copy())
    with pytest.raises(ValueError):
        MODULE["CONTRACT"]["require_release_inventory"](bom, expected_commit=SOURCE_REVISION)


def test_versioned_wrapper_checks_the_commit_query_and_linked_module_version(monkeypatch):
    import json

    name = "github.com/2dust/AndroidLibXrayLite"
    version = "v0.0.0-20261110063532-aaaaaaaaaaaa"
    component = {"name": name, "version": version, "properties": [{"name": "go:module:h1", "value": "h1:expected"}]}
    values = {"Path": name, "Version": version, "Sum": "h1:expected", "Origin": {"Hash": "c" * 40}}
    queries = []

    def output(command, **kwargs):
        queries.append(command[-1])
        return json.dumps(values)

    monkeypatch.setattr(MODULE["subprocess"], "check_output", output)
    with pytest.raises(ValueError, match="wrapper revision"):
        MODULE["add_go_license_evidence"](component, COMMIT)
    values["Origin"]["Hash"] = COMMIT
    values["Version"] = "v1.0.0"
    with pytest.raises(ValueError, match="source version"):
        MODULE["add_go_license_evidence"](component, COMMIT)
    assert queries == [f"{name}@{COMMIT}"] * 2
