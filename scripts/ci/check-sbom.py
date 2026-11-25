"""Validate the repository SBOM against the bundled CycloneDX JSON schema."""
import json
import sys
from pathlib import Path

from cyclonedx.schema import SchemaVersion
from cyclonedx.validation.json import JsonStrictValidator


def main(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    bom = json.loads(raw)
    versions = {"1.6": SchemaVersion.V1_6, "1.7": SchemaVersion.V1_7}
    version = bom.get("specVersion")
    if version not in versions:
        raise SystemExit(f"Unsupported CycloneDX schema {version!r}")
    problem = JsonStrictValidator(versions[version]).validate_str(raw)
    if problem is not None:
        raise SystemExit(f"Invalid CycloneDX {version} SBOM: {problem}")
    count = len(bom.get("components", []))
    if count <= 100:
        raise SystemExit(f"Repository SBOM has only {count} components")
    print(f"CycloneDX {version}: {count} components")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
