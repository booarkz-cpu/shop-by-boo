"""«Сверка с панелью»: what the shop set on the Remnawave panel against what the panel has now (REQ-RW-0007)."""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app import rw_drift

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
DE, CZ = "00000001-0000-4000-8000-000000000000", "00000002-0000-4000-8000-000000000000"


def pool(**over):
    base = {"enabled": True, "name": "Автовыбор", "tile": {"exists": True, "visible": True, "name": "Автовыбор"},
            "stats": {"missing": []}, "hosts": [{"uuid": "h1", "name": "de-1", "in_pool": True, "disabled": False},
                                               {"uuid": "h2", "name": "cz-1", "in_pool": False, "disabled": True}]}
    return {**base, **over}


def ban(*rows):
    return {"nodes": [{"uuid": u, "name": n, "ban": b, "minutes": m} for u, n, b, m in rows]}


WANTED = {"nodes": {DE: {"name": "de-1", "minutes": 60}, CZ: {"name": "cz-1", "minutes": 60}}}


def test_nothing_to_compare_and_everything_in_place():
    assert rw_drift.compare(None, {"nodes": {}}, None) == []
    assert rw_drift.compare(pool(enabled=False, tile={"exists": False}), {"nodes": {}}, None) == []   # the pool is switched off
    assert rw_drift.compare(pool(), WANTED, ban((DE, "de-1", True, 60), (CZ, "cz-1", True, 60))) == []


def test_pool_differences():
    items = rw_drift.pool_drift(pool(tile={"exists": False}, stats={"missing": ["h9"]},
                                     hosts=[{"uuid": "h1", "name": "de-1", "in_pool": True, "disabled": True}]))
    assert [(i["object"], i["actual"]) for i in items] == [
        ("Плитка «Автовыбор»", "удалена на панели"), ("Сервер пула h9", "удалён на панели"), ("Сервер пула «de-1»", "выключен на панели")]
    assert {i["tab"] for i in items} == {"autoselect"}
    hidden = rw_drift.pool_drift(pool(tile={"exists": True, "visible": False, "name": "Авто"}))
    assert hidden[0]["actual"] == "скрыта или выключена на панели"
    # A host that is not in the pool may be disabled: not the shop's business.
    assert rw_drift.pool_drift(pool()) == []


def test_ban_differences():
    items = rw_drift.ban_drift(WANTED, ban((DE, "de-1", True, 30)))
    assert [(i["object"], i["expected"], i["actual"]) for i in items] == [
        ("Нода «cz-1»", "бан на 60 мин.", "ноды нет на панели"), ("Нода «de-1»", "бан на 60 мин.", "бан на 30 мин.")]
    off = rw_drift.ban_drift({"nodes": {DE: {"name": "de-1", "minutes": 60}}}, ban((DE, "de-1", False, None)))
    assert off[0]["actual"] == "бан выключен на панели" and off[0]["tab"] == "torrents"
    # A node the shop never touched is not compared, whatever it has.
    assert rw_drift.ban_drift({"nodes": {}}, ban((DE, "de-1", False, None))) == []


def test_state_remembers_the_last_clean_check_and_survives_a_failure():
    clean = rw_drift.remember(rw_drift.DEFAULT, [], None, NOW)
    assert clean == {"checked_at": "2026-11-12T09:00:00+00:00", "ok_at": "2026-11-12T09:00:00+00:00", "items": [], "error": None, "failed_at": None}
    later = NOW.replace(hour=10)
    drifted = rw_drift.remember(clean, [{"object": "x"}], None, later)
    assert drifted["checked_at"] == "2026-11-12T10:00:00+00:00" and drifted["ok_at"] == "2026-11-12T09:00:00+00:00" and drifted["items"]
    # The panel did not answer: the last known differences stay, the failure is said, «checked» does not move.
    failed = rw_drift.remember(drifted, None, "Remnawave: нет ответа", NOW.replace(hour=11))
    assert failed["items"] == drifted["items"] and failed["checked_at"] == drifted["checked_at"]
    assert failed["error"] == "Remnawave: нет ответа" and failed["failed_at"] == "2026-11-12T11:00:00+00:00"


class Db:
    def __init__(self):
        self.store, self.commits = {}, 0

    async def commit(self):
        self.commits += 1


@pytest.fixture
def wired(monkeypatch):
    from app import node_health, rw_autoselect

    db = Db()

    async def load(_db, key, default):
        return {**default, **db.store.get(key, {})}

    async def save(_db, key, value):
        db.store[key] = value

    async def config(_db):
        return {"enabled": True}

    monkeypatch.setattr(node_health, "_load", load)
    monkeypatch.setattr(node_health, "_save", save)
    monkeypatch.setattr(rw_autoselect, "_config", config)
    return db


@pytest.mark.asyncio
async def test_check_stores_the_answer_and_meta_reads_it_without_the_panel(wired, monkeypatch):
    answers = [(pool(tile={"exists": False}), {"nodes": {}}, None)]

    async def read_panel(_db):
        if not answers:
            raise HTTPException(502, "Remnawave: нет ответа")
        return answers.pop(0)

    monkeypatch.setattr(rw_drift, "read_panel", read_panel)
    before = await rw_drift.meta(db=wired, admin=None)
    assert before["checked_at"] is None and before["in_sync"] is False and before["watched"] == {"autoselect": True, "torrent_ban_nodes": 0, "masque_nodes": 0}

    first = await rw_drift.check(db=wired, admin=None)
    assert len(first["items"]) == 1 and first["in_sync"] is False and wired.commits == 1
    assert (await rw_drift.meta(db=wired, admin=None))["items"] == first["items"]

    second = await rw_drift.check(db=wired, admin=None)   # the panel is down now
    assert second["error"] == "Remnawave: нет ответа" and second["items"] == first["items"] and second["in_sync"] is False


def test_schedule_and_what_is_worth_a_message():
    assert rw_drift.due(rw_drift.DEFAULT, NOW)
    checked = {"checked_at": "2026-11-12T09:00:00+00:00", "failed_at": None}
    assert not rw_drift.due(checked, NOW.replace(hour=14, minute=59)) and rw_drift.due(checked, NOW.replace(hour=15))
    # A failed attempt counts too: an unreachable panel is not asked every minute.
    assert not rw_drift.due({"checked_at": "2026-11-12T01:00:00+00:00", "failed_at": "2026-11-12T08:30:00+00:00"}, NOW)
    old = {"items": [{"area": "A", "object": "x", "actual": "нет"}]}
    same = [{"area": "A", "object": "x", "actual": "нет"}]
    assert rw_drift.news(old, same) == []
    assert rw_drift.news(old, same + [{"area": "A", "object": "y", "actual": "нет"}]) == [{"area": "A", "object": "y", "actual": "нет"}]


@pytest.mark.asyncio
async def test_tick_checks_when_due_and_notifies_once(wired, monkeypatch):
    from app import rw_autoupdate

    sent = []

    async def notify(text):
        sent.append(text)

    async def read_panel(_db):
        return pool(tile={"exists": False}), {"nodes": {}}, None

    monkeypatch.setattr(rw_autoupdate, "_notify", notify)
    monkeypatch.setattr(rw_drift, "read_panel", read_panel)
    first = await rw_drift.tick(wired, NOW)
    assert len(first["items"]) == 1 and len(sent) == 1 and "Плитка «Автовыбор» — удалена на панели" in sent[0]
    assert await rw_drift.tick(wired, NOW.replace(minute=30)) is None          # not due yet
    again = await rw_drift.tick(wired, NOW.replace(hour=15))
    assert again["checked_at"] == "2026-11-12T15:00:00+00:00" and len(sent) == 1  # the same difference: no second message


MASQUE_NODES = {
    "7": {"server_id": 7, "domain": "de.example.org", "port": 2087, "state": "on", "users": 3},
    "8": {"server_id": 8, "domain": "cz.example.org", "port": 2087, "state": "on", "users": 3},
    "9": {"server_id": 9, "domain": "nl.example.org", "port": 2087, "state": "off"},
}


def test_masque_nodes_drift_when_the_stack_is_stopped_or_changed_on_the_node():
    same = {"7": {"masque": "on", "users": "3", "port": "2087"}, "8": {"masque": "on", "users": "3", "port": "2087"}}
    assert rw_drift.masque_drift(MASQUE_NODES, same) == []
    assert rw_drift.masque_drift(MASQUE_NODES, {}) == []                     # nothing asked: nothing claimed
    items = rw_drift.masque_drift(MASQUE_NODES, {"7": "8", "8": {"users": "1", "port": "8443"}, "9": "8"})
    assert [(i["object"], i["expected"], i["actual"]) for i in items] == [
        ("Нода cz.example.org", "порт 2087", "порт 8443"),
        ("Нода cz.example.org", "пользователей: 3", "пользователей: 1"),
        ("Нода de.example.org", "стек MASQUE работает", "стек MASQUE не запущен"),
    ]
    assert {i["area"] for i in items} == {"MASQUE"} and {i["tab"] for i in items} == {"protocolSwitch"}
    down = rw_drift.masque_drift(MASQUE_NODES, {"7": "SSH: нет соединения"})
    assert down[0]["actual"] == "SSH: нет соединения"


@pytest.mark.asyncio
async def test_check_asks_masque_nodes_even_without_panel_settings(wired, monkeypatch):
    from app import masque_panel, rw_autoselect

    wired.store[masque_panel.STATE_KEY] = {"nodes": MASQUE_NODES}

    async def off(_db):
        return {"enabled": False}

    async def read_panel(_db):
        raise AssertionError("the panel is not asked when nothing is set on it")

    async def read_masque(_db):
        return MASQUE_NODES, {"7": "8"}

    monkeypatch.setattr(rw_autoselect, "_config", off)
    monkeypatch.setattr(rw_drift, "read_panel", read_panel)
    monkeypatch.setattr(rw_drift, "read_masque", read_masque)
    view = await rw_drift.check(db=wired, admin=None)
    assert view["watched"] == {"autoselect": False, "torrent_ban_nodes": 0, "masque_nodes": 2}
    assert [i["actual"] for i in view["items"]] == ["стек MASQUE не запущен"]


@pytest.mark.asyncio
async def test_read_masque_asks_only_installed_nodes(wired, monkeypatch):
    from types import SimpleNamespace

    from app import masque_panel

    wired.store[masque_panel.STATE_KEY] = {"nodes": MASQUE_NODES}
    asked = []

    async def ssh(_db, server_id, action, *args, **kwargs):
        asked.append((server_id, action))
        if server_id == 8:
            return SimpleNamespace(code=8, out="not installed", err="")
        return SimpleNamespace(code=0, out="masque=on users=3 port=2087 cert=Feb_1_2027", err="")

    monkeypatch.setattr(masque_panel, "_ssh", ssh)
    nodes, reports = await rw_drift.read_masque(wired)
    assert asked == [(7, "status"), (8, "status")]
    assert reports == {"7": {"masque": "on", "users": "3", "port": "2087", "cert": "Feb_1_2027"}, "8": "8"}
    assert rw_drift.masque_drift(nodes, reports)[0]["actual"] == "стек MASQUE не запущен"
