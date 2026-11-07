"""v28.92.0 (stage 20, N7): «Установка» — the catalogue of operations on the servers.

Every card leads to something that works: an admin tab that exists, the installer, or a module of the installer.
For a server the catalogue knows the steps done and which installation a module would go to."""
import re
from pathlib import Path

import pytest

from app import install_catalogue, rw_plan
from test_rw_installer import ADMIN, add_server, fleet, plan_and_approve, run_all  # noqa: F401
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def admin_tabs() -> set[str]:
    source = (ROOT / "admin/src/main.tsx").read_text()
    return set(re.findall(r'"([A-Za-z0-9]+)"', re.search(r"type Tab=([^;]+);", source).group(1)))


def test_every_card_leads_to_a_working_place():
    ops = install_catalogue.catalogue()
    assert len(ops) >= 30 and len({o["id"] for o in ops}) == len(ops)
    tabs = admin_tabs()
    for op in ops:
        kind = op["action"]["kind"]
        assert op["group"] in install_catalogue.GROUPS and op["title"] and op["text"]
        if kind == "tab":
            assert op["action"]["tab"] in tabs, op["id"]
        elif kind == "module":
            assert op["action"]["module"] in rw_plan.MODULES and op["action"]["needs"] in ("node", "any"), op["id"]
        else:
            assert kind == "install"
    assert {o["id"] for o in ops if o["simple"]} >= {"install_panel", "add_node", "hardening", "node_port"}, "the basics in «Простой»"
    assert sum(1 for o in ops if o["ssh"]) and sum(1 for o in ops if not o["ssh"])


@pytest.mark.asyncio
async def test_server_state_and_ready_modules(database, fleet):
    db = database
    server = await add_server(db, fleet, "n1", "198.51.100.40")
    from app import rw_api
    await rw_api.check_server(server["id"], db, ADMIN)
    before = await install_catalogue.get_catalogue(server["id"], db, ADMIN)
    assert before["state"]["installation_id"] is None and before["state"]["steps"]["prepared"]
    assert not next(o for o in before["operations"] if o["id"] == "node_guard")["ready"]
    assert next(o for o in before["operations"] if o["id"] == "bot")["ready"], "tabs are always open"
    approved = await plan_and_approve(db, rw_plan.PlanIn(mode="panel_node", panel_server_id=server["id"], panel_domain="panel.example.com",
                                                         tls="internal"))
    await run_all(db)
    after = await install_catalogue.get_catalogue(server["id"], db, ADMIN)
    assert after["state"]["installation_id"] == approved["id"] and "node" in after["state"]["roles"]
    assert after["state"]["steps"]["panel"] and after["state"]["steps"]["domain"] and "panel" in after["state"]["roles"]
    assert next(o for o in after["operations"] if o["id"] == "node_guard")["ready"]
    with pytest.raises(Exception):
        await install_catalogue.get_catalogue(999, db, ADMIN)


@pytest.mark.asyncio
async def test_snapshot_and_danger_zone(database, fleet, monkeypatch, tmp_path):
    from fastapi import HTTPException

    from app import rw_api
    db = database
    monkeypatch.setenv("RW_PANEL_COPIES_DIR", str(tmp_path / "copies"))
    server = await add_server(db, fleet, "p1", "198.51.100.41")
    await rw_api.check_server(server["id"], db, ADMIN)
    installed = await plan_and_approve(db, rw_plan.PlanIn(mode="panel_node", panel_server_id=server["id"], panel_domain="panel.example.com",
                                                          tls="internal"))
    await run_all(db)

    async def act(**kw):
        planned = await rw_api.action(installed["id"], rw_api.ActionIn(**kw), db, ADMIN)
        await rw_api.approve(planned["id"], rw_api.ApproveIn(plan_sha256=planned["plan_sha256"]), db, ADMIN)
        await run_all(db)
        return planned, await rw_api.get_installation(planned["id"], db, ADMIN)

    planned, done = await act(action="snapshot")
    assert [s["kind"] for s in planned["plan"]["steps"]] == ["backup_panel", "fetch_panel_backup", "fetch_configs"]
    assert done["status"] == "succeeded", done["error"]
    listed = (await install_catalogue.snapshots(ADMIN))["snapshots"]
    assert {s["kind"] for s in listed} == {"files", "database"}
    files = next(s for s in listed if s["kind"] == "files")
    got = await install_catalogue.download_snapshot(files["name"], db, ADMIN)
    import io
    import tarfile
    assert tarfile.open(fileobj=io.BytesIO(got.body), mode="r:gz").getnames() == ["opt/remnawave/docker-compose.yml"]
    assert (tmp_path / "copies" / files["name"]).read_bytes()[:20] != got.body[:20], "stored encrypted"
    with pytest.raises(HTTPException):
        await install_catalogue.download_snapshot("../etc/passwd", db, ADMIN)

    with pytest.raises(HTTPException):
        await rw_api.action(installed["id"], rw_api.ActionIn(action="remove_component"), db, ADMIN)
    with pytest.raises(HTTPException):
        await rw_api.action(installed["id"], rw_api.ActionIn(action="update", component="node"), db, ADMIN)
    with pytest.raises(HTTPException):
        await rw_api.action(installed["id"], rw_api.ActionIn(action="remove_component", component="selfsteal"), db, ADMIN)
    host = fleet["198.51.100.41"]
    assert "/opt/remnanode" in host.up
    planned, done = await act(action="remove_component", component="node")
    assert [s["kind"] for s in planned["plan"]["steps"]] == ["compose_down"] and done["status"] == "succeeded"
    assert "/opt/remnanode" not in host.up and "/opt/remnawave" in host.up, "only the node is taken off"
    planned, _ = await act(action="remove_component", component="panel")
    assert [s["kind"] for s in planned["plan"]["steps"]] == ["backup_panel", "fetch_panel_backup", "compose_down"]
