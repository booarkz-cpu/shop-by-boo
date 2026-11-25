#!/usr/bin/env python3
"""Build deterministic source, checksum and a commit-bound detached manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import runpy
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ci-run", default="")
    parser.add_argument("--sbom", type=Path, help="CycloneDX JSON from the successful CI run for this commit")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "release-manifest.template.json").read_text())
    tag = manifest["distribution_tag"]
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise SystemExit("Distribution tag must be a stable semantic version")
    artifact = f"remnawave_vpn_shop_{tag.replace('.', '_')}_full_release.zip"
    detached = artifact.removesuffix(".zip") + "_manifest.json"
    if manifest["artifact"] != artifact or manifest["detached_manifest"] != detached:
        raise SystemExit("Distribution filenames do not match its tag")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    if args.sbom:
        raw = args.sbom.read_bytes()
        bom = json.loads(raw)
        validate_release = runpy.run_path(str(root / "scripts/ci/check-sbom.py"))["require_release_inventory"]
        validate_release(bom, expected_commit=commit)
        sbom_name = artifact.removesuffix(".zip") + ".cdx.json"
        (root / sbom_name).write_bytes(raw)
        manifest["sbom"] = {"name": sbom_name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    subprocess.run([sys.executable, str(root / "scripts/package-source.py"), artifact], cwd=root, check=True)
    digest = hashlib.sha256((root / artifact).read_bytes()).hexdigest()
    (root / (artifact + ".sha256")).write_text(f"{digest}  {artifact}\n")
    manifest.update(sha256=digest, commit=commit, ci_run=args.ci_run, signed=False,
                    tests="Green CI and Docker required on the exact release commit; external provider E2E is not certified")
    (root / detached).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"{tag}: {artifact}, {artifact}.sha256, {detached}")


if __name__ == "__main__":
    main()
