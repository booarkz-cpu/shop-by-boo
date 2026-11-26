"""Validate repository and release inventories before packaging."""
import argparse
import base64
import hashlib
import json
import re
import runpy
import subprocess
from collections.abc import Collection
from pathlib import Path
from urllib.parse import unquote

PRODUCTS = {"vpn-shop": "shop.remnawave.user", "vpn-client": "shop.corgi.client", "lucy-admin": "shop.remnawave.admin"}
REPOSITORY_MANIFESTS = {
    "services/backend/requirements.txt": "pypi",
    "services/support-pro/requirements.txt": "pypi",
    "apps/lucy-admin/web/package-lock.json": "npm",
    "apps/user-cabinet/package-lock.json": "npm",
}
ENGINE_REF = "corgi:android:libv2ray.aar"
ENGINE_MODULES = {"github.com/2dust/androidlibxraylite", "github.com/xtls/xray-core"}
GO_SOURCE_DIGEST = "go:source-file:sha256:"
GO_NOTICE_TEXT = "go:notice:base64:"
PROJECT_NAME = "VPN Shop by Corgi Lucy"


def validate_schema(raw: str) -> dict:
    from cyclonedx.schema import SchemaVersion
    from cyclonedx.validation.json import JsonStrictValidator

    bom = json.loads(raw)
    versions = {"1.6": SchemaVersion.V1_6, "1.7": SchemaVersion.V1_7}
    version = bom.get("specVersion")
    if version not in versions:
        raise SystemExit(f"Unsupported CycloneDX schema {version!r}")
    problem = JsonStrictValidator(versions[version]).validate_str(raw)
    if problem is not None:
        raise SystemExit(f"Invalid CycloneDX {version} SBOM: {problem}")
    return bom


def has_sha256(record: dict) -> bool:
    values = [item.get("content") for item in record.get("hashes", []) if item.get("alg") == "SHA-256"]
    if len(values) != 1 or not isinstance(values[0], str):
        return False
    return re.fullmatch(r"[0-9a-fA-F]{64}", values[0]) is not None


def go_source_file_kind(path: str) -> str | None:
    filename = path.rsplit("/", 1)[-1]
    if Path(filename).suffix.lower() in {".go", ".c", ".h", ".py", ".sh", ".js", ".java"}:
        return None
    if re.fullmatch(r"(?:notice|patents|copyright)(?:[._-].+)?", filename, re.I):
        return "notice"
    if (re.fullmatch(r"(?:licen[cs]e|copying|unlicen[cs]e)(?:[._-].+)?"
                     r"|(?:MIT|BSD|APACHE)[_-]LICEN[CS]E(?:[._-].+)?", filename, re.I)
            or "/licenses/" in f"/{path.lower()}/"):
        return "licence"
    return None


def go_file_properties(module: dict, prefix: str) -> dict:
    files = {}
    for item in module.get("properties", []):
        name = item["name"]
        if name.startswith(prefix):
            path = name.removeprefix(prefix)
            if not path or path in files:
                raise ValueError(f"Invalid or duplicate Go file property in {module['name']}: {name}")
            files[path] = item["value"]
    return files


def require_go_source_texts(module: dict) -> None:
    digests = go_file_properties(module, GO_SOURCE_DIGEST)
    texts = go_file_properties(module, GO_NOTICE_TEXT)
    for path in texts:
        if go_source_file_kind(path) != "notice":
            raise ValueError(f"Invalid Go notice path in {module['name']}: {path}")
    licenses = module.get("evidence", {}).get("licenses", [])
    if not licenses:
        raise ValueError(f"Missing Go module licence text for {module['name']}")
    for entry in licenses:
        licence = entry.get("license", {})
        path, text = licence.get("name"), licence.get("text", {})
        if (not isinstance(path, str) or go_source_file_kind(path) != "licence"
                or path in texts or text.get("encoding") != "base64"):
            raise ValueError(f"Invalid Go licence evidence in {module['name']}: {path}")
        texts[path] = text.get("content")

    if texts.keys() != digests.keys():
        missing = sorted(texts.keys() ^ digests.keys())
        raise ValueError(f"Unpaired Go source texts and SHA-256 in {module['name']}: {missing}")
    for path, encoded in texts.items():
        try:
            data = base64.b64decode(encoded, validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid base64 in {module['name']}: {path}") from exc
        expected = digests[path]
        if not data.strip() or b"\x00" in data or not isinstance(expected, str) or hashlib.sha256(data).hexdigest() != expected.lower():
            raise ValueError(f"Invalid Go source text or SHA-256 in {module['name']}: {path}")


def require_native_inventory(components: list, links: dict) -> None:
    abi_names = runpy.run_path(str(Path(__file__).resolve().parents[1] / "mobile/xray-artifact.py"))["ABIS"]
    native = {f"{ENGINE_REF}/{abi}" for abi in abi_names}
    if links.get(ENGINE_REF) != native:
        raise ValueError("Release is missing the shared AAR or a native ABI")
    by_ref = {item["bom-ref"]: item for item in components if "bom-ref" in item}
    for ref in {ENGINE_REF} | native:
        item = by_ref.get(ref, {})
        if item.get("type") != "file" or not has_sha256(item):
            raise ValueError(f"Release requires a file with a SHA-256 digest for {ref}")

    linked_modules = set()
    for abi in native:
        modules = links.get(abi, set())
        names = {by_ref[ref]["name"].lower() for ref in modules if ref in by_ref}
        if not ENGINE_MODULES <= names:
            raise ValueError(f"Release is missing the Android wrapper or Xray-core for {abi}")
        linked_modules.update(modules)

    for ref in linked_modules:
        module = by_ref.get(ref, {})
        if module.get("type") != "library" or not module.get("purl", "").startswith("pkg:golang/"):
            raise ValueError(f"Release is missing a linked Go module: {ref}")
        require_go_source_texts(module)
        sources = module.get("externalReferences", [])
        if not any(source.get("type") == "distribution" and has_sha256(source) for source in sources):
            raise ValueError(f"Release is missing the Go source archive digest for {ref}")


def reachable_packages(name: str, direct: set, links: dict, modules: Collection[str]) -> set:
    if not direct:
        raise ValueError(f"Release is missing the dependency graph for {name}")
    reached = set()
    pending = list(direct)
    while pending:
        ref = pending.pop()
        if ref in reached:
            continue
        if ref not in modules:
            raise ValueError(f"Unresolved dependency in {name}: {ref}")
        reached.add(ref)
        pending.extend(links.get(ref, set()) - reached)
    return reached


def require_python_pins(manifest: str, source_root: Path, packages: list[dict]) -> None:
    def coordinate(name: str, version: str) -> str:
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        return f"pkg:pypi/{normalized}@{version}"

    expected = set()
    for number, line in enumerate((source_root / manifest).read_text(encoding="utf-8").splitlines(), 1):
        requirement = line.partition("#")[0].strip()
        if not requirement:
            continue
        # The distributed files pin all target platforms. An extra selects features of the same wheel.
        spec = requirement.partition(";")[0].strip()
        pin = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\s*\[[^\]]+\])?\s*==\s*"
                           r"([0-9][A-Za-z0-9.!+_-]*)", spec)
        if not pin:
            raise ValueError(f"{manifest}:{number}: cannot verify an exact runtime dependency: {requirement}")
        expected.add(coordinate(*pin.groups()))

    actual = set()
    for item in packages:
        version = item.get("version")
        if item.get("type") != "library" or not version:
            raise ValueError(f"{manifest}: expected a versioned PyPI library for {item['bom-ref']}")
        package = coordinate(item["name"], version)
        purl = item["purl"].split("#", 1)[0].split("?", 1)[0]
        if unquote(purl) != package:
            raise ValueError(f"{manifest}: {item['purl']} does not identify {package}")
        actual.add(package)
    if expected != actual:
        raise ValueError(f"{manifest}: missing PyPI pins {sorted(expected - actual)}, "
                         f"unexpected direct packages {sorted(actual - expected)}")


def require_repository_inventory(components: list, direct: set, links: dict,
                                 source_root: Path | None = None) -> None:
    for manifest, ecosystem in REPOSITORY_MANIFESTS.items():
        manifests = [item.get("bom-ref") for item in components
                     if item.get("type") == "application" and item.get("name") == manifest]
        if len(manifests) != 1 or manifests[0] not in direct:
            raise ValueError(f"Release requires one linked repository manifest for {manifest}")
        packages = {item["bom-ref"]: item for item in components if item.get("bom-ref")
                    and item.get("purl", "").startswith(f"pkg:{ecosystem}/")}
        declared = links.get(manifests[0], set())
        reachable_packages(manifest, declared, links, packages.keys())
        if ecosystem == "pypi" and source_root is not None:
            require_python_pins(manifest, source_root, [packages[ref] for ref in sorted(declared)])


def require_maven_inventory(app: dict, direct: set, links: dict) -> None:
    name = app["name"]
    modules = set()
    for item in app.get("components", []):
        ref = item.get("bom-ref")
        if not ref or ref in modules or not item.get("purl", "").startswith("pkg:maven/"):
            raise ValueError(f"Invalid Maven component in {name}: {ref}")
        if not any(choice.get("expression") or choice.get("license", {}).get("id") or
                   choice.get("license", {}).get("name") for choice in item.get("licenses", [])):
            raise ValueError(f"Missing Maven licence declaration in {name}: {ref}")
        modules.add(ref)

    # Only the application can depend on the shared AAR. Every Maven edge stays inside this product.
    reached = reachable_packages(name, direct - {ENGINE_REF}, links, modules)
    if reached != modules:
        raise ValueError(f"Release contains unreachable Maven components in {name}: {sorted(modules - reached)}")


def require_release_inventory(bom: dict, *, expected_commit: str | None = None, source_root: Path | None = None) -> None:
    if (bom.get("bomFormat"), bom.get("specVersion")) != ("CycloneDX", "1.7"):
        raise ValueError("Release requires CycloneDX 1.7")
    components = bom.get("components", [])
    links = {}
    for row in bom.get("dependencies", []):
        ref = row["ref"]
        if ref in links:
            raise ValueError(f"Duplicate dependency record for {ref}")
        links[ref] = set(row.get("dependsOn", []))
    product_root = bom.get("metadata", {}).get("component", {})
    if product_root.get("name") != PROJECT_NAME:
        raise ValueError("Release SBOM has the wrong product name")
    revision = product_root.get("version", "")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Release SBOM must identify the source commit")
    if expected_commit is not None and revision != expected_commit:
        raise ValueError(f"Release SBOM belongs to {revision}, expected {expected_commit}")
    root = product_root.get("bom-ref")
    require_repository_inventory(components, links.get(root, set()), links, source_root)
    for product, name in PRODUCTS.items():
        apps = [item for item in components if item.get("type") == "application" and item.get("name") == name]
        if len(apps) != 1:
            raise ValueError(f"Release requires exactly one application {name}")
        app = apps[0]
        ref = app.get("bom-ref")
        direct = links.get(ref, set())
        if ref not in links.get(root, set()):
            raise ValueError(f"Release is missing the application link for {name}")
        if (ENGINE_REF in direct) != (product != "lucy-admin"):
            raise ValueError(f"Unexpected native engine linkage for {name}")
        require_maven_inventory(app, direct, links)
    require_native_inventory(components, links)


def main(path: Path, release: bool = False, source_root: Path | None = None) -> None:
    bom = validate_schema(path.read_text(encoding="utf-8"))
    # Android applications own their resolved components in the CycloneDX hierarchy.
    pending = list(bom.get("components", []))
    count = 0
    while pending:
        component = pending.pop()
        count += 1
        pending.extend(component.get("components", []))
    if count <= 100:
        raise SystemExit(f"Repository SBOM has only {count} components")
    if release:
        revision = None
        if source_root is not None:
            revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source_root, text=True).strip()
        require_release_inventory(bom, expected_commit=revision, source_root=source_root)
    print(f"CycloneDX {bom['specVersion']}: {count} components")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--source-root", type=Path, help="Compare release PyPI dependencies with this source checkout")
    args = parser.parse_args()
    if args.source_root is not None and not args.release:
        parser.error("--source-root requires --release")
    main(args.path, args.release, args.source_root)
