"""Dependency pins that must not drift apart.

Support Pro has exactly one lock, ``support-pro/requirements.txt``: the tests install it
(through ``requirements-dev.txt``), Dependabot updates it, and the Docker image installs it,
because docker-compose builds Support Pro with the ``support-pro`` directory as the context.
"""
import re
from pathlib import Path

import yaml

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
        assert all((context / name).resolve() == (ROOT / "support-pro/requirements.txt").resolve() for name in copied), (service, copied)
    assert "-r requirements.txt" in (ROOT / "support-pro/requirements-dev.txt").read_text()
    # A second copy of the lock is what let versions drift before: there must be only one.
    assert not (ROOT / "support-pro/app/requirements.txt").exists()
    assert pins("support-pro/requirements.txt")["fastapi"]


def test_sqlalchemy_asyncio_extra_brings_greenlet():
    # SQLAlchemy 2.1 no longer installs greenlet by itself; without it the async engine fails to import.
    backend = (ROOT / "backend/requirements.txt").read_text().lower()
    assert "sqlalchemy[asyncio]==" in backend or "greenlet==" in backend
    assert "greenlet" in pins("support-pro/requirements.txt")


def test_dependabot_watches_the_files_that_are_installed():
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    pip_dirs = {u["directory"] for u in config["updates"] if u["package-ecosystem"] == "pip"}
    assert pip_dirs == {"/backend", "/support-pro"}
