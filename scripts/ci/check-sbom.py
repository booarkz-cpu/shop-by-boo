"""Validate repository and release inventories before packaging."""
import argparse
import json
import runpy
from pathlib import Path

PRODUCTS = {"vpn-shop": "shop.remnawave.user", "vpn-client": "shop.corgi.client", "lucy-admin": "shop.remnawave.admin"}
ENGINE_REF = "corgi:android:libv2ray.aar"


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


def require_release_inventory(bom: dict) -> None:
    if (bom.get("bomFormat"), bom.get("specVersion")) != ("CycloneDX", "1.7"):
        raise ValueError("Release requires CycloneDX 1.7")
    components = bom.get("components", [])
    links = {row["ref"]: set(row.get("dependsOn", [])) for row in bom.get("dependencies", [])}
    root = bom.get("metadata", {}).get("component", {}).get("bom-ref")
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
    abi_names = runpy.run_path(str(Path(__file__).resolve().parents[1] / "mobile/xray-artifact.py"))["ABIS"]
    native = {f"{ENGINE_REF}/{abi}" for abi in abi_names}
    files = {item["bom-ref"] for item in components if item.get("type") == "file" and item.get("bom-ref")}
    if links.get(ENGINE_REF) != native or not ({ENGINE_REF} | native) <= files:
        raise ValueError("Release is missing the shared AAR or a native ABI")


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
