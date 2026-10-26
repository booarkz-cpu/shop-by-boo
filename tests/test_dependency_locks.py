"""Dependency pins that must not drift apart.

The Support Pro image installs ``support-pro/app/requirements.txt`` (Dependabot updates that
file); ``support-pro/requirements.txt`` only includes it, so the tests run on the same pins.
"""
import re
from pathlib import Path

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
    lines = [x.strip() for x in (ROOT / "support-pro/requirements.txt").read_text().splitlines() if x.strip() and not x.startswith("#")]
    assert lines == ["-r app/requirements.txt"]
    dev = (ROOT / "support-pro/requirements-dev.txt").read_text()
    assert "-r requirements.txt" in dev
    assert pins("support-pro/app/requirements.txt")["fastapi"]


def test_sqlalchemy_asyncio_extra_brings_greenlet():
    # SQLAlchemy 2.1 no longer installs greenlet by itself; without it the async engine fails to import.
    backend = (ROOT / "backend/requirements.txt").read_text().lower()
    assert "sqlalchemy[asyncio]==" in backend or "greenlet==" in backend
    assert "greenlet" in pins("support-pro/app/requirements.txt")

