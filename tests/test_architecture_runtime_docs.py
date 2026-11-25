"""Check the operator's current storage inventory against the actual Compose and Alembic inputs."""
import re
from pathlib import Path

import pytest
import yaml
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]


def documented_row(document, label):
    rows = [line for line in document.splitlines() if line.startswith(f"| {label} |")]
    assert len(rows) == 1, f"Expected one row for {label}"
    return rows[0]


@pytest.mark.parametrize(("service", "support", "image", "label"), [
    ("db", "support_db", "postgres", "PostgreSQL"),
    ("redis", "support_redis", "redis", "Redis"),
])
def test_architecture_and_external_dependency_versions(service, support, image, label):
    stack = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    standalone = yaml.safe_load((ROOT / "services/support-pro/docker-compose.yml").read_text())["services"]
    deployed = re.search(rf"{image}:([0-9.]+)-alpine@sha256:[a-f0-9]{{64}}", stack[service]["image"])
    assert deployed, stack[service]["image"]
    assert stack[support]["image"] == standalone[service]["image"] == deployed[0]
    for filename in ("PROJECT_ARCHITECTURE.md", "EXTERNAL_DEPENDENCIES.md"):
        documented_row((ROOT / "docs" / filename).read_text(), f"{label} {deployed[1]}")


@pytest.mark.parametrize(("component", "label"), [("backend", "магазине"), ("support-pro", "Support Pro")])
def test_documented_migration_heads_and_counts_match_the_revisions(component, label):
    source = ScriptDirectory(str(ROOT / "services" / component / "alembic"))
    head, = source.get_heads()
    count = len(list(source.walk_revisions()))
    doc = (ROOT / "docs/PROJECT_ARCHITECTURE.md").read_text()
    storage, = [line for line in doc.splitlines() if line.startswith("| PostgreSQL ")]
    assert f"Миграций в {label} — {count}, head `{head}`" in storage
