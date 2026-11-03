"""v28.65.0 (stage 9): the Remnawave Manager architecture documents describe the code as it is.

* every file named in the four documents exists, and every shop route named as existing is a real route;
* the fourteen components and the seven modes are all in REMNAWAVE_ARCHITECTURE.md;
* each panel route listed as used has a client method and a live test against the latest panel;
* the agent delivers only the action kinds of the closed list and rejects any other."""
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import AgentAction, NodeAgent
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
DOCS = {name: (ROOT / "docs/ru/new" / f"{name}.md").read_text() for name in
        ("REMNAWAVE_ARCHITECTURE", "REMNAWAVE_DATA_MODEL", "REMNAWAVE_API_DESIGN", "DEPLOYMENT_AGENT_ARCHITECTURE")}
COMPONENTS = ["Remnawave Manager", "Deployment Manager", "Server Registry", "Node Manager", "Domain Manager",
              "Certificate Manager", "Proxy Manager", "Subscription Manager", "Module Manager", "Backup Manager",
              "Update Manager", "Health Manager", "Job Manager", "Audit Manager"]
MODES = ["Panel + Node", "Panel Only", "Node Only", "Panel + Subscription Page", "Subscription Page Only",
         "Distributed Deployment", "Add Node to Existing Panel"]


def test_named_files_exist():
    for name, text in DOCS.items():
        for path in set(re.findall(r"`((?:backend|scripts|tests|deploy|admin|cabinet|docs)/[\w./-]+\.\w+)`", text)):
            assert (ROOT / path.split("::")[0]).exists(), f"{name}: {path}"


def test_components_and_modes_are_all_described():
    text = DOCS["REMNAWAVE_ARCHITECTURE"]
    for number, component in enumerate(COMPONENTS, 1):
        assert re.search(rf"^\| {number} \| {re.escape(component)} \|", text, re.M), component
    for mode in MODES:
        assert f"| {mode} |" in text, mode


def test_existing_shop_routes_in_the_api_design_are_real():
    from app.admin_center import _walk
    from app.main import app
    paths = {p for _, p in _walk(app.routes)}
    existing = DOCS["REMNAWAVE_API_DESIGN"].split("## 3.")[0]
    for path in set(re.findall(r"`(?:GET|POST|PUT|PATCH|DELETE)?[ /]*(/api/(?:admin|agent)/[\w/{}.-]+)", existing)):
        path = path.rstrip(".")
        assert any(p == path or p.startswith(path.rstrip("/") + "/") for p in paths) or path.endswith("…"), path
    # The wizard's (stage 10), the Domain Manager's (stage 11) and the extension manager's (stage 12) routes exist.
    assert {"/api/admin/rw/servers", "/api/admin/rw/installations/plan", "/api/admin/rw/installations/{installation_id}/approve",
            "/api/admin/rw/domains", "/api/admin/rw/certificates", "/api/admin/rw/proxy-routes",
            "/api/admin/rw/extensions", "/api/admin/rw/extensions/profiles/reality"} <= paths  # v28.69.0, stage 12


def test_used_panel_routes_have_a_client_method_and_a_live_test():
    client = (ROOT / "backend/app/remnawave.py").read_text()
    live = (ROOT / "tests/live/test_remnawave_live.py").read_text()
    table = DOCS["REMNAWAVE_API_DESIGN"].split("## 1.")[1].split("Ошибки:")[0]
    for row in [r for r in table.splitlines() if r.startswith("| `")]:
        cells = [c.strip() for c in row.strip("|").split("|")]
        for method in re.findall(r"`(\w+)`", cells[1]):
            assert method == "sub_proxy" or f"def {method}(" in client, method
        for test in re.findall(r"`(test_\w+)`", cells[3]):
            assert f"def {test}(" in live, test


def test_node_compose_matches_the_official_service_shape():
    import yaml

    from app import provisioner
    service = yaml.safe_load(provisioner.node_compose("k"))["services"]["remnanode"]
    assert service["network_mode"] == "host" and service["environment"]["NODE_PORT"] == "2222"
    assert "/api/admin/provision-node" in DOCS["REMNAWAVE_API_DESIGN"] and "NodeProvisionIn" in DOCS["REMNAWAVE_API_DESIGN"]


@pytest.mark.asyncio
async def test_agent_gets_only_actions_of_the_closed_list(database):
    from app import platform_api
    db = database
    agent = NodeAgent(name="ci-node", token_hash=platform_api._hash("agent-token"))
    db.add(agent)
    await db.flush()
    db.add_all([AgentAction(agent_id=agent.id, kind="restart_node", payload={}, status="queued"),
                AgentAction(agent_id=agent.id, kind="run_shell", payload={"cmd": "id"}, status="queued")])
    await db.commit()
    out = await platform_api.agent_heartbeat(platform_api.HeartbeatIn(), db, "agent-token")
    assert [a["kind"] for a in out["actions"]] == ["restart_node"]
    states = {a.kind: a.status for a in (await db.execute(select(AgentAction))).scalars()}
    assert states == {"restart_node": "delivered", "run_shell": "rejected"}
