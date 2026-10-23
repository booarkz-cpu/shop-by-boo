"""A saved gate flag cannot outlive or bypass its staging evidence."""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.staging_gate import staging_evidence_valid


def evidence(now):
    return {"status": "passed", "full_e2e": True, "contract_version": 2,
            "config_revision": "staging-a", "finished_at": now.isoformat()}


def test_valid_current_evidence_accepts_at_boundary():
    now = datetime.now(timezone.utc)
    assert staging_evidence_valid(evidence(now - timedelta(hours=24)), {"revision": "staging-a"}, now)
    assert staging_evidence_valid(evidence(now), {"revision": "staging-a"}, now)


@pytest.mark.parametrize("change", [
    {"status": "running"}, {"full_e2e": False}, {"contract_version": 1},
    {"config_revision": "old"}, {"finished_at": "garbage"},
])
def test_wrong_or_incomplete_evidence_fails_closed(change):
    now = datetime.now(timezone.utc)
    assert not staging_evidence_valid({**evidence(now), **change}, {"revision": "staging-a"}, now)


def test_stale_future_or_unbound_evidence_fails_closed():
    now = datetime.now(timezone.utc)
    for finished in (now - timedelta(hours=24, seconds=1), now + timedelta(seconds=1)):
        assert not staging_evidence_valid(evidence(finished), {"revision": "staging-a"}, now)
    assert not staging_evidence_valid(evidence(now), {"revision": "another-config"}, now)
    assert not staging_evidence_valid(evidence(now), {}, now)


def test_legacy_naive_timestamp_is_interpreted_as_utc():
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    status = evidence(now - timedelta(hours=2))
    status["finished_at"] = "2026-09-24T22:00:00"
    assert staging_evidence_valid(status, {"revision": "staging-a"}, now)


def test_real_payments_are_open_unless_an_administrator_closed_them(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
    from app import main

    state = {}

    async def setting(db, key, default=""):
        return state.get(key, default)

    monkeypatch.setattr(main, "setting_value", setting)
    # A fresh installation accepts real payments without any staging evidence.
    assert asyncio.run(main.production_payments_allowed(None)) is True
    state[main.PRODUCTION_PAYMENTS_CLOSED_KEY] = "1"
    assert asyncio.run(main.production_payments_allowed(None)) is False
    state[main.PRODUCTION_PAYMENTS_CLOSED_KEY] = "0"
    assert asyncio.run(main.production_payments_allowed(None)) is True
