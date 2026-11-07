"""v28.90.0 (stage 20, N3): every dependency manifest of the repository is covered by Dependabot.

Dependabot opens a PR for each update; patch updates merge themselves only after the whole CI is green
(scripts/dependabot-automerge.cjs), minor and major ones wait for a person. A new app or Dockerfile without an entry
in .github/dependabot.yml would silently stay on old versions — this test fails instead."""
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
KINDS = {"package.json": "npm", "requirements.txt": "pip", "settings.gradle.kts": "gradle", "Dockerfile": "docker",
         "docker-compose.yml": "docker-compose"}


def covered() -> set[tuple[str, str]]:
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    out = set()
    for update in config["updates"]:
        for directory in update.get("directories") or [update["directory"]]:
            out.add((update["package-ecosystem"], directory.rstrip("/") or "/"))
    return out


def manifests() -> set[tuple[str, str]]:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    out = set()
    for f in files:
        path = Path(f)
        kind = KINDS.get(path.name)
        if kind and "node_modules" not in path.parts and not f.startswith(("tests/", "docs/")):
            out.add((kind, "/" + str(path.parent) if str(path.parent) != "." else "/"))
    return out


def test_every_manifest_has_dependabot_updates():
    missing = manifests() - covered()
    assert not missing, f"no Dependabot entry for: {sorted(missing)}"


def test_github_actions_and_weekly_schedule():
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    assert ("github-actions", "/") in covered()
    assert all(u["schedule"]["interval"] == "weekly" for u in config["updates"])
