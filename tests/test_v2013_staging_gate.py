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


def test_enabled_gate_is_rechecked_on_each_request(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
    from app import main, e2e_v2

    now = datetime.now(timezone.utc)
    state = {main.PRODUCTION_PAYMENTS_GATE_KEY: "1",
             e2e_v2.ADMISSION_STATUS_KEY: json.dumps(evidence(now - timedelta(hours=25))),
             e2e_v2.ADMISSION_CONFIG_KEY: json.dumps({"revision": "staging-a", "public_key": "k", "providers": ["yookassa"]})}

    async def setting(db, key, default=""):
        return state.get(key, default)

    monkeypatch.setattr(main, "setting_value", setting)
    assert asyncio.run(main.production_payments_allowed(None)) is False
    state[e2e_v2.ADMISSION_STATUS_KEY] = json.dumps(evidence(now))
    assert asyncio.run(main.production_payments_allowed(None)) is True
    state[main.PRODUCTION_PAYMENTS_GATE_KEY] = "0"
    assert asyncio.run(main.production_payments_allowed(None)) is False
    # The v1 smoke runner's status key is not evidence any more.
    state[main.PRODUCTION_PAYMENTS_GATE_KEY] = "1"
    state[e2e_v2.ADMISSION_STATUS_KEY] = "{}"
    state[main.STAGING_E2E_STATUS_KEY] = json.dumps(evidence(now))
    assert asyncio.run(main.production_payments_allowed(None)) is False
