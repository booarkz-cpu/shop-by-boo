"""Validate repository and release inventories before packaging."""
import argparse
import json
import re
import runpy
from pathlib import Path

PRODUCTS = {"vpn-shop": "shop.remnawave.user", "vpn-client": "shop.corgi.client", "lucy-admin": "shop.remnawave.admin"}
ENGINE_REF = "corgi:android:libv2ray.aar"
ENGINE_MODULES = {"github.com/2dust/androidlibxraylite", "github.com/xtls/xray-core"}
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
        licenses = module.get("evidence", {}).get("licenses", [])
        if not any(entry.get("license", {}).get("text", {}).get("content") for entry in licenses):
            raise ValueError(f"Release is missing the Go module licence text for {ref}")
        sources = module.get("externalReferences", [])
        if not any(source.get("type") == "distribution" and has_sha256(source) for source in sources):
            raise ValueError(f"Release is missing the Go source archive digest for {ref}")


def require_release_inventory(bom: dict, *, expected_commit: str | None = None) -> None:
    if (bom.get("bomFormat"), bom.get("specVersion")) != ("CycloneDX", "1.7"):
        raise ValueError("Release requires CycloneDX 1.7")
    components = bom.get("components", [])
    links = {row["ref"]: set(row.get("dependsOn", [])) for row in bom.get("dependencies", [])}
    product_root = bom.get("metadata", {}).get("component", {})
    if product_root.get("name") != PROJECT_NAME:
        raise ValueError("Release SBOM has the wrong product name")
    revision = product_root.get("version", "")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Release SBOM must identify the source commit")
    if expected_commit is not None and revision != expected_commit:
        raise ValueError(f"Release SBOM belongs to {revision}, expected {expected_commit}")
    root = product_root.get("bom-ref")
    for product, name in PRODUCTS.items():
        apps = [item for item in components if item.get("type") == "application" and item.get("name") == name]
        if len(apps) != 1:
            raise ValueError(f"Release requires exactly one application {name}")
        app = apps[0]
        ref = app.get("bom-ref")
        direct = links.get(ref, set())
        maven = {child["bom-ref"] for child in app.get("components", []) if child.get("purl", "").startswith("pkg:maven/")}
        if ref not in links.get(root, set()) or not maven.intersection(direct):
            raise ValueError(f"Release is missing the Maven graph for {name}")
        if (ENGINE_REF in direct) != (product != "lucy-admin"):
            raise ValueError(f"Unexpected native engine linkage for {name}")
    require_native_inventory(components, links)


def main(path: Path, release: bool = False) -> None:
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
        require_release_inventory(bom)
    print(f"CycloneDX {bom['specVersion']}: {count} components")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    main(args.path, args.release)
