"""Check the architecture inventory against the build, storage and migration inputs."""
import json
import re
from pathlib import Path

import pytest
import yaml
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]


def test_architecture_backend_counts_match_catalogue_and_source():
    doc = (ROOT / "docs/PROJECT_ARCHITECTURE.md").read_text()
    row = documented_row(doc, "FastAPI backend")
    catalogue = (ROOT / "docs/API_ENDPOINTS.md").read_text()
    operations = re.findall(r"^\| `(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)` \|", catalogue, re.MULTILINE)
    assert f"{len(operations)} операций OpenAPI" in row
    file_count = sum(1 for _ in (ROOT / "services/backend/app").rglob("*.py"))
    assert f"файлов Python в дереве приложения — {file_count}" in row


def test_architecture_healthcheck_count_matches_compose():
    stack = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    with_healthcheck = sum(bool(service.get("healthcheck")) and not service["healthcheck"].get("disable")
                           for service in stack.values())
    doc = (ROOT / "docs/PROJECT_ARCHITECTURE.md").read_text()
    assert f"Проверки состояния включены у {with_healthcheck} из {len(stack)} сервисов" in doc


def documented_row(document, label):
    rows = [line for line in document.splitlines() if line.startswith(f"| {label} |")]
    assert len(rows) == 1, f"Expected one row for {label}"
    return rows[0]


def row_for_source(path):
    document = (ROOT / "docs/PROJECT_ARCHITECTURE.md").read_text()
    rows = [line for line in document.splitlines() if line.startswith("| ") and f"`{path}`" in line]
    assert len(rows) == 1, f"Expected one component row for {path}"
    return rows[0]


@pytest.mark.parametrize("build", sorted(ROOT.glob("apps/*/android/app/build.gradle.kts")))
def test_android_products_have_their_own_source_and_version(build):
    version, = re.findall(r'^\s*versionName\s*=\s*"([^"]+)"', build.read_text(), re.MULTILINE)
    assert f"`{version}`" in row_for_source(build.parents[1].relative_to(ROOT))


@pytest.mark.parametrize("build", sorted(ROOT.glob("apps/*/ios/*.xcodeproj/project.pbxproj")))
def test_ios_products_have_their_own_source_and_version(build):
    version, = set(re.findall(r"MARKETING_VERSION\s*=\s*([^;]+);", build.read_text()))
    assert f"`{version}`" in row_for_source(build.parents[1].relative_to(ROOT))


def test_web_and_bot_rows_follow_the_build_inputs():
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    for target in ci["jobs"]["frontend"]["strategy"]["matrix"]["include"]:
        directory = target["dir"]
        row = row_for_source(directory)
        package = json.loads((ROOT / directory / "package.json").read_text())
        if "next" in package.get("dependencies", {}):
            lock = json.loads((ROOT / directory / "package-lock.json").read_text())
            assert f"Next.js `{lock['packages']['node_modules/next']['version']}`" in row
        else:
            task, = re.findall(r"npm run (\S+) --prefix ../user-cabinet", package["scripts"]["build"])
            assert f"`{task}`" in row
    pins = (ROOT / "services/backend/requirements.txt").read_text()
    version, = re.findall(r"^aiogram==([^\s]+)$", pins, re.MULTILINE)
    assert f"aiogram `{version}`" in row_for_source("services/backend/app/bot.py")


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
