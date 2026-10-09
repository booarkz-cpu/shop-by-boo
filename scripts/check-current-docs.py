#!/usr/bin/env python3
"""Fail when current release identity or documentation pointers diverge."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "21.5.1"
TAG = f"v{VERSION}"
DISTRIBUTION_TAG = "v27"
SHOP_HEAD = "0062_support_delivery_identity"
SUPPORT_HEAD = "0006"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def require(relative: str, *needles: str) -> None:
    value = read(relative)
    missing = [needle for needle in needles if needle not in value]
    if missing:
        raise SystemExit(f"{relative}: missing {missing!r}")


def main() -> None:
    require("backend/app/main.py", f'APP_VERSION = "{VERSION}"')
    require("deploy/install-vps.sh", f'INSTALLER_VERSION="{VERSION}"')
    require("scripts/build-release.sh", f'VERSION="{VERSION}"')
    require("README.md", DISTRIBUTION_TAG, VERSION, SHOP_HEAD, "MATRIX_COMPLETION_21_5_1.md")
    require("DOCUMENTATION.md", DISTRIBUTION_TAG, VERSION, SHOP_HEAD, SUPPORT_HEAD)
    require("INSTALL_STEPS.md", DISTRIBUTION_TAG, VERSION)
    require("install.sh", 'BRANCH="${BRANCH:-v27}"')
    require("docs/ru/DEPLOYMENT_CURRENT.md", DISTRIBUTION_TAG, VERSION, SHOP_HEAD, SUPPORT_HEAD)
    require("docs/ru/PRODUCTION_CURRENT.md", TAG, SHOP_HEAD, SUPPORT_HEAD)
    require("docs/ru/WORKSPACE_COVERAGE.md", TAG, SHOP_HEAD, SUPPORT_HEAD)
    require(".github/workflows/publish-release.yml", TAG, "v21_5_1")

    manifest = json.loads(read("release-manifest.template.json"))
    expected = {
        "version": VERSION,
        "artifact": "remnawave_vpn_shop_v21_5_1_full_release.zip",
        "detached_manifest": "remnawave_vpn_shop_v21_5_1_full_release_manifest.json",
        "migration_head": SHOP_HEAD,
        "support_migration_head": SUPPORT_HEAD,
        "upgrade_from": "21.5.0",
    }
    mismatches = {key: (manifest.get(key), value) for key, value in expected.items() if manifest.get(key) != value}
    if mismatches:
        raise SystemExit(f"release-manifest.template.json: {mismatches}")
    for flag in ("production_ready", "full_function_transfer", "production_e2e_verified", "signed"):
        if manifest.get(flag) is not False:
            raise SystemExit(f"release-manifest.template.json: {flag} must remain false")

    matrix = read("docs/ru/WORKSPACE_COVERAGE.md")
    table_rows = [line for line in matrix.splitlines() if re.match(r"^\| [^|-].*\|$", line)]
    if len(table_rows) < 45:
        raise SystemExit(f"coverage matrix unexpectedly short: {len(table_rows)} rows")

    print(f"current documentation contract OK: distribution {DISTRIBUTION_TAG}, runtime {TAG}, shop {SHOP_HEAD}, support {SUPPORT_HEAD}")


if __name__ == "__main__":
    main()
