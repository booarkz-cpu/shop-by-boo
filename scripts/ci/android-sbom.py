"""Join the three releaseRuntimeClasspath graphs and the shared AAR to the repository CycloneDX BOM."""
import argparse
import hashlib
import json
import re
import runpy
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile

from license_expression import AND, OR, ExpressionError, get_spdx_licensing

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = {"vpn-shop": "shop.remnawave.user", "vpn-client": "shop.corgi.client", "lucy-admin": "shop.remnawave.admin"}
LICENCE = runpy.run_path(str(ROOT / "scripts/ci/check-licenses.py"))
XRAY = runpy.run_path(str(ROOT / "scripts/mobile/xray-artifact.py"))
ENGINE_REF = "corgi:android:libv2ray.aar"
SPDX = get_spdx_licensing()


def hashed(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def go_modules(info, commit):
    modules = {}
    for dep in info["Deps"]:
        path = dep["Path"]
        source = dep.get("Replace", dep)
        if source.get("Version") == "(devel)" and path == "github.com/2dust/AndroidLibXrayLite":
            version = commit
        else:
            path, version = source["Path"], source["Version"]
            if not version.startswith("v") or not source.get("Sum", "").startswith("h1:"):
                raise ValueError(f"Unidentified Go module {path} in Android engine")
        purl = f"pkg:golang/{quote(path, safe='/')}@{quote(version, safe='')}"
        item = {"type": "library", "name": path, "version": version, "purl": purl, "bom-ref": purl}
        if source.get("Sum"):
            item["properties"] = [{"name": "go:module:h1", "value": source["Sum"]}]
        if path == "github.com/2dust/AndroidLibXrayLite":
            item["licenses"] = [{"license": {"name": "GNU Lesser General Public License v3.0"}}]
            item["externalReferences"] = [{"type": "vcs", "url": f"https://github.com/2dust/AndroidLibXrayLite/tree/{commit}"}]
        if path.lower() == "github.com/xtls/xray-core":
            item["licenses"] = [{"license": {"id": "MPL-2.0"}}]
        if purl in modules:
            raise ValueError(f"Duplicate Go module {purl}")
        modules[purl] = item
    if not {"github.com/2dust/androidlibxraylite", "github.com/xtls/xray-core"} <= {m["name"].lower() for m in modules.values()}:
        raise ValueError("Android engine is missing the pinned wrapper or Xray-core")
    return modules


def engine_inventory(aar, commit):
    abis = XRAY["payload"](aar, "jni", XRAY["revision"](commit))
    package = {"type": "file", "name": "libv2ray.aar", "version": commit, "bom-ref": ENGINE_REF,
               "hashes": [{"alg": "SHA-256", "content": hashed(aar)}]}
    native, modules, edges = [], {}, []
    with ZipFile(aar) as archive, tempfile.TemporaryDirectory() as temp:
        elf = Path(temp) / "libgojni.so"
        for abi, digest in sorted(abis.items()):
            ref = f"{ENGINE_REF}/{abi}"
            with archive.open(f"jni/{abi}/libgojni.so") as src, elf.open("wb") as dest:
                shutil.copyfileobj(src, dest)
            info = json.loads(subprocess.check_output(["go", "version", "-m", "-json", str(elf)], text=True))
            linked = go_modules(info, commit)
            for key, item in linked.items():
                if key in modules and modules[key] != item:
                    raise ValueError(f"Inconsistent Android Go module metadata for {key}")
                modules[key] = item
            native.append({"type": "file", "name": f"{abi}/libgojni.so", "bom-ref": ref,
                           "hashes": [{"alg": "SHA-256", "content": digest}],
                           "properties": [{"name": "go:compiler", "value": info["GoVersion"]}]})
            edges.append({"ref": ref, "dependsOn": sorted(linked)})
    edges.append({"ref": ENGINE_REF, "dependsOn": [item["bom-ref"] for item in native]})
    return [package, *native, *(modules[k] for k in sorted(modules))], edges


def expression_allowed(value):
    try:
        expression = SPDX.parse(value, validate=True, strict=True)
    except ExpressionError as exc:
        raise ValueError(f"Invalid SPDX licence expression {value!r}") from exc

    def allowed(node):
        if isinstance(node, AND):
            return all(allowed(child) for child in node.args)
        if isinstance(node, OR):
            return any(allowed(child) for child in node.args)
        return LICENCE["verdict"](str(node)) == "ok"

    return expression is not None and allowed(expression)


def check_licenses(component):
    allowed = []
    for choice in component.get("licenses", []):
        licence = choice.get("license", {})
        if "expression" in choice:
            allowed.append(expression_allowed(choice["expression"]))
        else:
            allowed.append(LICENCE["verdict"](licence.get("id") or licence.get("name") or "") == "ok")
    # A list of licences is not an explicit SPDX OR. Preserve every declared obligation.
    if not allowed or not all(allowed):
        raise ValueError(f"{component['name']}: review Android licence {component.get('licenses', [])!r}")


def android_graph(product, bom, model, aar):
    root = bom["metadata"]["component"]
    if (bom.get("bomFormat"), bom.get("specVersion"), root.get("name"), root.get("version")) != (
        "CycloneDX", "1.7", PRODUCTS[product], model["version"]
    ) or model["applicationId"] != PRODUCTS[product] or not model["version"]:
        raise ValueError(f"{product}: incorrect Gradle SBOM identity")
    expected_files = [] if product == "lucy-admin" else [aar.resolve()]
    if sorted(Path(p).resolve() for p in model["files"]) != expected_files:
        raise ValueError(f"{product}: unexpected release file dependencies")
    nodes = {root["bom-ref"]: "@app"}
    coordinates = {"@app"}
    for item in bom["components"]:
        ref = item["bom-ref"]
        coord = ":".join(item[k] for k in ("group", "name", "version"))
        if ref in nodes or coord in coordinates:
            raise ValueError(f"{product}: duplicated Gradle component {coord}")
        check_licenses(item)
        nodes[ref] = coord
        coordinates.add(coord)

    edges = {coord: set() for coord in nodes.values()}
    seen = set()
    for row in bom["dependencies"]:
        ref = row["ref"]
        if ref not in nodes or ref in seen or set(row) - {"ref", "dependsOn"}:
            raise ValueError(f"{product}: invalid Gradle relation {ref}")
        seen.add(ref)
        for child in row.get("dependsOn", []):
            if child not in nodes:
                raise ValueError(f"{product}: dangling Gradle reference {child}")
            edges[nodes[ref]].add(nodes[child])
    expected = {k: set(v) for k, v in model["edges"].items()}
    if edges != expected or not edges.get("@app") or not any(edges[k] for k in edges if k != "@app"):
        difference = sorted(k for k in set(edges) | set(expected) if edges.get(k) != expected.get(k))
        raise ValueError(f"{product}: incomplete Gradle release graph {difference}")

    def scoped(ref):
        return f"corgi:android:{product}:{ref}"

    # The same Maven module can resolve differently for different products. Keep both graphs.
    def scope_component(value):
        if isinstance(value, list):
            return [scope_component(v) for v in value]
        if isinstance(value, dict):
            return {k: scoped(v) if k == "bom-ref" else scope_component(v) for k, v in value.items()}
        return value

    app = scope_component(root)
    app["components"] = [scope_component(item) for item in bom["components"]]
    graph = {scoped(row["ref"]): [scoped(child) for child in row.get("dependsOn", [])]
             for row in bom["dependencies"]}
    if expected_files:
        graph[app["bom-ref"]].append(ENGINE_REF)
    return app, [{"ref": ref, "dependsOn": sorted(children)} for ref, children in sorted(graph.items())]


def combine(repo, inputs, aar, commit):
    if set(inputs) != set(PRODUCTS):
        raise ValueError("Expected release SBOMs for all three Android products")
    root = repo["metadata"]["component"]["bom-ref"]
    root_edges = [row for row in repo["dependencies"] if row["ref"] == root]
    if len(root_edges) != 1:
        raise ValueError("Repository SBOM must identify its root dependency graph")
    native, native_edges = engine_inventory(aar, commit)
    for product, (bom, model) in sorted(inputs.items()):
        app, graph = android_graph(product, bom, model, aar)
        repo["components"].append(app)
        repo["dependencies"].extend(graph)
        root_edges[0].setdefault("dependsOn", []).append(app["bom-ref"])
    repo["components"].extend(native)
    repo["dependencies"].extend(native_edges)
    return repo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    aar = ROOT / "apps/vpn-shop/android/app/libs/libv2ray.aar"
    pin = (ROOT / "scripts/mobile/build-xray-aar.sh").read_text()
    commit, = re.findall(r"XRAY_AAR_COMMIT:-([0-9a-f]{40})", pin)
    inputs = {}
    validate_schema = runpy.run_path(str(ROOT / "scripts/ci/check-sbom.py"))["validate_schema"]
    for product in PRODUCTS:
        folder = ROOT / "apps" / product / "android/app/build/reports/cyclonedx-direct"
        inputs[product] = (validate_schema((folder / "bom.json").read_text()), json.loads((folder / "resolution.json").read_text()))
    result = combine(json.loads(args.repository.read_text()), inputs, aar, commit)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    for product, (bom, _) in inputs.items():
        print(f"{product}: {len(bom['components'])} Maven components, release dependency graph verified")


if __name__ == "__main__":
    main()
