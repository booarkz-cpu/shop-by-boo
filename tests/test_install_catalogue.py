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
