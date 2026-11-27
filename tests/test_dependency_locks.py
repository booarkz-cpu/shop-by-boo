"""Dependency pins that must not drift apart.

Support Pro has exactly one lock, ``services/support-pro/requirements.txt``: the tests install it
(through ``requirements-dev.txt``), Dependabot updates it, and the Docker image installs it,
because docker-compose builds Support Pro with the ``support-pro`` directory as the context.
"""
import json
import re
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


def pins(path: str) -> dict[str, str]:
    out = {}
    for line in (ROOT / path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" in line:
            name, version = line.split("==", 1)
            out[re.sub(r"\[.*\]", "", name).strip().lower().replace("_", "-")] = version.strip()
    return out


def test_support_pro_image_installs_the_tested_lock():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    for service in ("support_pro", "support_worker"):
        build = compose["services"][service]["build"]
        context = (ROOT / build["context"]).resolve()
        dockerfile = (context / build["dockerfile"]).read_text()
        copied = re.findall(r"^COPY\s+(\S*requirements\S*\.txt)\s", dockerfile, re.M)
        assert copied, service
        assert all((context / name).resolve() == (ROOT / "services/support-pro/requirements.txt").resolve() for name in copied), (service, copied)
    assert "-r requirements.txt" in (ROOT / "services/support-pro/requirements-dev.txt").read_text()
    # A second copy of the lock is what let versions drift before: there must be only one.
    assert not (ROOT / "services/support-pro/app/requirements.txt").exists()
    assert pins("services/support-pro/requirements.txt")["fastapi"]


def test_sqlalchemy_asyncio_extra_brings_greenlet():
    # SQLAlchemy 2.1 no longer installs greenlet by itself; without it the async engine fails to import.
    backend = (ROOT / "services/backend/requirements.txt").read_text().lower()
    assert "sqlalchemy[asyncio]==" in backend or "greenlet==" in backend
    assert "greenlet" in pins("services/support-pro/requirements.txt")


def test_dependabot_watches_the_files_that_are_installed():
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    pip_dirs = {u["directory"] for u in config["updates"] if u["package-ecosystem"] == "pip"}
    assert pip_dirs == {"/services/backend", "/services/support-pro"}


@pytest.mark.parametrize("name", ["pydantic", "pydantic-core", "redis"])
def test_dependabot_can_offer_support_updates(name):
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    support, = (
        entry for entry in config["updates"]
        if entry.get("directory") == "/services/support-pro" and entry["package-ecosystem"] == "pip"
    )
    installed = Version(pins("services/support-pro/requirements.txt")[name])
    for rule in support.get("ignore", []):
        if not fnmatchcase(name, rule["dependency-name"].lower().replace("_", "-")):
            continue
        versions = rule.get("versions", [])
        update_types = rule.get("update-types", [])
        assert versions or update_types, f"{name}: all updates are ignored"
        assert "version-update:semver-patch" not in update_types, f"{name}: patch updates are ignored"
        for expression in versions:
            excluded = SpecifierSet(expression)
            if name == "redis":
                assert installed not in excluded, f"{name}: {expression} excludes the tested release {installed}"
            # A bounded exclusion can skip a bad release. A lower bound at or below
            # the installed version, with no upper bound, suppresses every upgrade.
            hides_every_upgrade = all(
                bound.operator in {">", ">="} and Version(bound.version) <= installed
                for bound in excluded
            )
            assert not hides_every_upgrade, f"{name} {expression} masks every newer version"


@pytest.mark.parametrize("name", ["aiogram", "redis"])
def test_bot_and_redis_clients_match_the_documented_backend_versions(name):
    runtime = pins("services/backend/requirements.txt")
    stack = (ROOT / "docs/TECH_STACK.md").read_text().splitlines()
    assert [row.split("|")[2].strip() for row in stack if row.startswith(f"| {name} |")] == [runtime[name]]


def test_support_pro_python_315_runtime_dependency_contract():
    locked = pins("services/support-pro/requirements.txt")
    assert locked["fastapi"] == "0.165.0"
    assert locked["sqlalchemy"] == "2.1.9"
    assert Version(locked["aiogram"]) >= Version("3.34.0")
    assert Version(locked["certifi"]) >= Version("2026.11.20")
    assert Version(locked["redis"]) >= Version("8.2.0")
    inventory = (ROOT / "docs/EXTERNAL_DEPENDENCIES.md").read_text().splitlines()
    support_row, = (line for line in inventory if line.startswith("| Support Pro runtime |"))
    for name, label in (("aiogram", "aiogram"), ("redis", "redis-py")):
        assert f"{label} {locked[name]}" in support_row
    # Earlier fakeredis cannot construct an async client with redis-py 8.2.
    dev = pins("services/support-pro/requirements-dev.txt")
    assert Version(dev["fakeredis"]) >= Version("2.41.0")
    assert locked["pydantic"] == "2.14.4"
    assert locked["pydantic-core"] == "2.50.5"
    assert Version(locked["opentelemetry-api"]) >= Version("1.44.0")

    dockerfile = (ROOT / "services/support-pro/app/Dockerfile").read_text()
    assert "python:3.15-slim@" in dockerfile


def test_web_dependency_contracts_are_synchronized():
    admin_manifest = json.loads((ROOT / "apps/lucy-admin/web/package.json").read_text())
    admin_lock = json.loads((ROOT / "apps/lucy-admin/web/package-lock.json").read_text())
    cabinet_manifest = json.loads((ROOT / "apps/user-cabinet/package.json").read_text())
    cabinet_lock = json.loads((ROOT / "apps/user-cabinet/package-lock.json").read_text())

    assert admin_manifest["devDependencies"]["@playwright/test"] == "1.65.1"
    assert admin_lock["packages"][""]["devDependencies"]["@playwright/test"] == "1.65.1"
    assert admin_lock["packages"]["node_modules/@playwright/test"]["version"] == "1.65.1"
    assert admin_lock["packages"]["node_modules/playwright"]["version"] == "1.65.1"
    assert admin_lock["packages"]["node_modules/playwright-core"]["version"] == "1.65.1"

    inventory = (ROOT / "docs/EXTERNAL_DEPENDENCIES.md").read_text()
    for label, manifest, lock in (
        ("lucide-react в Lucy Admin Web", admin_manifest, admin_lock),
        ("lucide-react в кабинете и Telegram Mini App", cabinet_manifest, cabinet_lock),
    ):
        resolved = lock["packages"]["node_modules/lucide-react"]["version"]
        assert re.fullmatch(r"\d+\.\d+\.\d+", resolved)
        assert manifest["dependencies"]["lucide-react"] == f"^{resolved}"
        assert lock["packages"][""]["dependencies"]["lucide-react"] == f"^{resolved}"
        rows = [row.split("|")[2].strip() for row in inventory.splitlines() if row.startswith(f"| {label} |")]
        assert rows == [resolved], label

    assert cabinet_manifest["devDependencies"]["jsdom"] == "31.0.1"
    assert cabinet_lock["packages"][""]["devDependencies"]["jsdom"] == "31.0.1"
    assert cabinet_lock["packages"]["node_modules/jsdom"]["version"] == "31.0.1"
