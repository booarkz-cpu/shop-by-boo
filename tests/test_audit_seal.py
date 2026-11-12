"""«Целостность журнала»: a changed or deleted audit record breaks the seal of its range (REQ-ADMIN-0012)."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import audit_seal as seal

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


def record(i, action="payment.refund", actor="admin@example.test", details='{"sum": 100}'):
    return SimpleNamespace(id=i, action=action, actor=actor, target=f"order:{i}", details=details, request_id=f"req-{i}",
                           created_at=datetime(2026, 11, 12, 9, 0, i))


class Db:
    """The audit table and app_settings, enough for the module."""

    def __init__(self, rows):
        self.rows, self.settings, self.commits = list(rows), {}, 0

    async def commit(self):
        self.commits += 1

    async def scalar(self, _query):
        return len([r for r in self.rows if r.id > self.edge])


@pytest.fixture
def wired(monkeypatch):
    from app import node_health

    db = Db([record(i) for i in range(1, 8)])
    db.edge = 0

    async def load(_db, key, default):
        return {**default, **db.settings.get(key, {})}

    async def save(_db, key, value):
        db.settings[key] = value

    async def rows(_db, after, upto, limit=None):
        found = [r for r in sorted(db.rows, key=lambda r: r.id) if r.id > after and (upto is None or r.id <= upto)]
        db.edge = max(db.edge, upto or 0)
        return found[:limit] if limit else found

    monkeypatch.setattr(node_health, "_load", load)
    monkeypatch.setattr(node_health, "_save", save)
    monkeypatch.setattr(seal, "_rows", rows)
    monkeypatch.setattr(seal, "_last_tick", None)
    return db


def test_the_seal_depends_on_every_field_and_on_the_previous_seal():
    rows = [record(1), record(2)]
    base = seal.digest("", rows)
    assert base == seal.digest("", [record(1), record(2)]) and len(base) == 64
    for changed in (record(2, action="payment.view"), record(2, actor="other@example.test"), record(2, details='{"sum": 1}')):
        assert seal.digest("", [record(1), changed]) != base
    assert seal.digest("", [record(2), record(1)]) != base            # the order
    assert seal.digest("earlier", rows) != base                        # the chain
    assert seal.digest("", rows, b"another secret") != base            # the server's secret
    assert seal.canonical(record(1)) == '[1,"payment.refund","admin@example.test","order:1","{\\"sum\\": 100}","req-1","2026-11-12T09:00:01.000000"]'


@pytest.mark.asyncio
async def test_sealing_and_an_intact_journal(wired):
    assert await seal.seal_new(wired, NOW) == 7
    assert await seal.seal_new(wired, NOW) == 0                         # nothing new: no empty seal
    wired.rows += [record(8), record(9)]
    assert await seal.seal_new(wired, NOW) == 2
    seals = wired.settings[seal.STATE_KEY]["seals"]
    assert [(s["from"], s["to"], s["count"]) for s in seals] == [(1, 7, 7), (8, 9, 2)] and seals[1]["prev"] == seals[0]["digest"]
    wired.rows.append(record(10))                                        # written after the last seal
    result = await seal.verify(wired, NOW)
    assert result["intact"] is True and result["broken"] == [] and result["sealed_records"] == 9 and result["unsealed_records"] == 1
    assert result["verified_at"] == "2026-11-12T10:00:00+00:00"


@pytest.mark.asyncio
async def test_a_changed_and_a_deleted_record_are_found_by_range(wired):
    await seal.seal_new(wired, NOW)
    wired.rows += [record(8), record(9)]
    await seal.seal_new(wired, NOW)
    wired.rows[2].details = '{"sum": 1}'                                 # record 3 was edited in the database
    result = await seal.verify(wired, NOW)
    assert result["intact"] is False
    assert result["broken"] == [{"from": 1, "to": 7, "sealed": 7, "found": 7, "sealed_at": "2026-11-12T10:00:00+00:00"}]
    wired.rows[2].details = '{"sum": 100}'
    wired.rows = [r for r in wired.rows if r.id != 9]                    # record 9 was deleted
    result = await seal.verify(wired, NOW)
    assert [(b["from"], b["to"], b["sealed"], b["found"]) for b in result["broken"]] == [(8, 9, 2, 1)]
    assert wired.settings[seal.STATE_KEY]["broken"] == result["broken"]  # the answer is remembered


@pytest.mark.asyncio
async def test_a_removed_seal_and_a_foreign_secret_are_found(wired, monkeypatch):
    await seal.seal_new(wired, NOW)
    wired.rows += [record(8)]
    await seal.seal_new(wired, NOW)
    state = wired.settings[seal.STATE_KEY]
    kept = dict(state["seals"][1])
    state["seals"] = [kept]                                              # the first seal was removed from app_settings
    assert (await seal.verify(wired, NOW))["intact"] is False
    # Re-sealed by someone without the server's secret.
    forged = seal.seal_rows([], [record(i) for i in range(1, 9)], NOW)
    forged["digest"] = seal.digest("", [record(i) for i in range(1, 9)], b"not the server secret")
    state["seals"] = [forged]
    assert (await seal.verify(wired, NOW))["intact"] is False


@pytest.mark.asyncio
async def test_old_seals_are_joined_only_while_they_hold(wired):
    await seal.seal_new(wired, NOW)
    for i in (8, 9, 10):
        wired.rows.append(record(i))
        await seal.seal_new(wired, NOW)
    seals = wired.settings[seal.STATE_KEY]["seals"]
    joined = await seal.join_oldest(wired, seals, 3)
    assert [(s["from"], s["to"], s["count"]) for s in joined] == [(1, 9, 9), (10, 10, 1)] and joined[0]["joined"] == 3
    wired.settings[seal.STATE_KEY]["seals"] = joined
    assert (await seal.verify(wired, NOW))["intact"] is True               # the chain goes on through the joined seal
    wired.rows[0].actor = "someone@example.test"
    assert await seal.join_oldest(wired, joined, 2) == joined              # a broken range is never folded away


@pytest.mark.asyncio
async def test_the_worker_seals_every_ten_minutes(wired):
    assert await seal.tick(wired, NOW) == 7
    wired.rows.append(record(8))
    assert await seal.tick(wired, NOW.replace(minute=9)) is None
    assert await seal.tick(wired, NOW.replace(minute=10)) == 1
