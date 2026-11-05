"""v28.82.0 (stage 19, part A): extra transports of a SelfSteal node — VLESS + xHTTP + REALITY (TCP 4443),
VLESS + gRPC + REALITY (TCP 8443) and Hysteria2 (UDP 443) next to VLESS + TCP + REALITY on 443.

The plan rules, the inbounds the panel profile gets (same REALITY keys and SelfSteal site; Hysteria2 with the copied
certificate), and the panel step against a fake panel: hosts, squads, the node's active inbounds, switching back."""
import copy

import pytest
from pydantic import ValidationError

from app import rw_plan, rw_steps

SERVERS = {2: {"name": "n2", "host": "93.184.216.40"}}
BASE = {"tag": "VLESS_TCP_REALITY", "port": 443, "protocol": "vless", "settings": {"clients": [], "decryption": "none"},
        "streamSettings": {"network": "raw", "security": "reality",
                           "realitySettings": {"dest": rw_plan.SELFSTEAL_SOCKET, "xver": 1, "serverNames": ["node.example.com"],
                                               "privateKey": "PRIV", "shortIds": [""]}}}


def test_plan_rules_and_steps():
    with pytest.raises(ValidationError):  # transports need the SelfSteal domain and certificate
        rw_plan.PlanIn(mode="node", node_server_ids=[2], transports=["grpc"])
    with pytest.raises(ValidationError):
        rw_plan.PlanIn(mode="node", node_server_ids=[2], selfsteal_domain="node.example.com", transports=["tuic"])
    plan = rw_plan.PlanIn(mode="node", node_server_ids=[2], selfsteal_domain="node.example.com", acme_email="a@example.com",
                          transports=["hysteria2", "xhttp", "xhttp"])
    assert plan.transports == ["hysteria2", "xhttp"]
    built = rw_plan.build_plan(plan, SERVERS, "https://panel.shop.example")
    kinds = [s["kind"] for s in built["steps"]]
    assert kinds.index("register_node") < kinds.index("node_transports") < kinds.index("verify")
    module = next(s for s in built["steps"] if s["params"].get("module") == "transports")
    assert module["params"]["transports"] == ["hysteria2", "xhttp"]
    compose = rw_plan.node_compose("key", 2222, selfsteal=True, hysteria=True)
    assert f"{rw_plan.HYSTERIA_DIR}:{rw_plan.HYSTERIA_MOUNT}:ro" in compose
    assert rw_plan.HYSTERIA_DIR not in rw_plan.node_compose("key", 2222, selfsteal=True)
    # Changing the set later is a module action of the installation.
    plan.module = rw_plan.ModuleRun(name="transports", transports=["grpc"])
    plan.transports = ["grpc"]
    steps, title = rw_plan.module_steps(plan, SERVERS, {2: ["node"]})
    assert "gRPC" in title and [s["kind"] for s in steps] == ["node_module", "write_files", "compose_up", "node_transports", "verify"]
    with pytest.raises(ValueError):
        rw_plan.module_steps(rw_plan.PlanIn(mode="node", node_server_ids=[2], module=rw_plan.ModuleRun(name="transports")),
                             SERVERS, {2: ["node"]})


def test_inbounds_share_reality_and_hysteria_reads_the_certificate():
    got = {i["tag"]: i for i in rw_steps.transport_inbounds(BASE, "node.example.com", ["xhttp", "grpc", "hysteria2"])}
    xhttp, grpc, hy = got["VLESS_XHTTP_REALITY"], got["VLESS_GRPC_REALITY"], got["HYSTERIA2"]
    assert (xhttp["port"], grpc["port"], hy["port"]) == (4443, 8443, 443)
    for inbound in (xhttp, grpc):
        stream = inbound["streamSettings"]
        assert inbound["protocol"] == "vless" and stream["security"] == "reality"
        assert stream["realitySettings"] == BASE["streamSettings"]["realitySettings"]
        assert stream["realitySettings"] is not BASE["streamSettings"]["realitySettings"]
    assert xhttp["streamSettings"]["xhttpSettings"]["path"] == "/xhttp"
    assert grpc["streamSettings"]["grpcSettings"]["serviceName"] == "grpc"
    assert hy["protocol"] == "hysteria" and hy["settings"]["version"] == 2
    tls = hy["streamSettings"]["tlsSettings"]
    assert hy["streamSettings"]["network"] == "hysteria" and tls["alpn"] == ["h3"] and tls["serverName"] == "node.example.com"
    assert tls["certificates"][0]["certificateFile"] == f"{rw_plan.HYSTERIA_MOUNT}/cert.pem" and tls["certificates"][0]["ocspStapling"]
    host = rw_steps.transport_host("hysteria2", "node.example.com", "p", "i", "x")
    assert host["port"] == 443 and host["alpn"] == "h3" and host["inbound"] == {"configProfileUuid": "p", "configProfileInboundUuid": "i"}


def test_script_checks_domain_and_keeps_tcp():
    script = rw_steps.TRANSPORTS_SH
    assert 'case "$domain" in *[!a-z0-9.-]*' in script
    assert "4443/tcp" in script and "8443/tcp" in script and "443/udp" in script and "port 443/tcp" not in script
    assert "remnawave-selfsteal" in script and "OnCalendar=daily" in script


class Panel:
    """Enough of Remnawave's API for the step: profiles get inbound uuids by tag, hosts, squads, nodes."""

    def __init__(self):
        self.config = {"inbounds": [copy.deepcopy(BASE)]}
        self.hosts = [{"uuid": "h-main", "inbound": {"configProfileUuid": "prof", "configProfileInboundUuid": "in-VLESS_TCP_REALITY"}}]
        self.squads = [{"uuid": "sq", "inbounds": [{"uuid": "in-VLESS_TCP_REALITY"}, {"uuid": "other"}]},
                       {"uuid": "sq-free", "inbounds": [{"uuid": "other"}]}]
        self.nodes, self.calls = {}, []

    def profile(self):
        return {"uuid": "prof", "config": copy.deepcopy(self.config),
                "inbounds": [{"uuid": f"in-{i['tag']}", "tag": i["tag"]} for i in self.config["inbounds"]]}

    async def __call__(self, ctx, method, path, body=None, **kw):
        self.calls.append((method, path))
        if path == "/api/config-profiles/prof":
            return self.profile()
        if path == "/api/config-profiles" and method == "PATCH":
            self.config = body["config"]
            return self.profile()
        if path == "/api/hosts" and method == "GET":
            return self.hosts
        if path == "/api/hosts" and method == "POST":
            self.hosts.append({"uuid": f"h-{body['inbound']['configProfileInboundUuid']}", **body})
            return self.hosts[-1]
        if path.startswith("/api/hosts/") and method == "DELETE":
            self.hosts = [h for h in self.hosts if h["uuid"] != path.rsplit("/", 1)[1]]
            return {}
        if path == "/api/internal-squads" and method == "GET":
            return {"internalSquads": self.squads}
        if path == "/api/internal-squads" and method == "PATCH":
            next(s for s in self.squads if s["uuid"] == body["uuid"])["inbounds"] = [{"uuid": u} for u in body["inbounds"]]
            return {}
        if path == "/api/nodes" and method == "PATCH":
            self.nodes[body["uuid"]] = body["configProfile"]
            return {}
        return {}


@pytest.mark.asyncio
async def test_panel_step_adds_and_removes_transports(monkeypatch):
    panel = Panel()
    monkeypatch.setattr(rw_steps, "panel_api", panel)
    plan = rw_plan.PlanIn(mode="node", node_server_ids=[2], selfsteal_domain="node.example.com", tls="internal",
                          transports=["grpc", "hysteria2"])
    ctx = rw_steps.Context(plan=plan, servers={}, secrets={}, state={"selfsteal_profile": "prof", "nodes": {"2": "node-2"}})
    await rw_steps.run_node_transports(ctx, {})
    tags = [i["tag"] for i in panel.config["inbounds"]]
    assert tags == ["VLESS_TCP_REALITY", "VLESS_GRPC_REALITY", "HYSTERIA2"]
    assert {h["uuid"] for h in panel.hosts} == {"h-main", "h-in-VLESS_GRPC_REALITY", "h-in-HYSTERIA2"}
    assert [i["uuid"] for i in panel.squads[0]["inbounds"]] == ["in-VLESS_TCP_REALITY", "other", "in-VLESS_GRPC_REALITY", "in-HYSTERIA2"]
    assert panel.squads[1]["inbounds"] == [{"uuid": "other"}], "squads without the REALITY inbound are not touched"
    assert panel.nodes["node-2"]["activeInbounds"] == ["in-VLESS_TCP_REALITY", "in-VLESS_GRPC_REALITY", "in-HYSTERIA2"]
    assert ("POST", "/api/nodes/node-2/actions/restart") in panel.calls
    assert ctx.state["transports"] == ["grpc", "hysteria2"]

    # Switch to xHTTP only: gRPC and Hysteria2 go away from the profile, hosts and squads; the rest stays.
    ctx.plan = rw_plan.PlanIn(mode="node", node_server_ids=[2], selfsteal_domain="node.example.com", tls="internal", transports=["xhttp"])
    await rw_steps.run_node_transports(ctx, {})
    assert [i["tag"] for i in panel.config["inbounds"]] == ["VLESS_TCP_REALITY", "VLESS_XHTTP_REALITY"]
    assert {h["uuid"] for h in panel.hosts} == {"h-main", "h-in-VLESS_XHTTP_REALITY"}
    assert [i["uuid"] for i in panel.squads[0]["inbounds"]] == ["in-VLESS_TCP_REALITY", "other", "in-VLESS_XHTTP_REALITY"]

    # Undo returns the previous set.
    await rw_steps.undo_node_transports(ctx, {})
    assert [i["tag"] for i in panel.config["inbounds"]] == ["VLESS_TCP_REALITY", "VLESS_GRPC_REALITY", "HYSTERIA2"]


@pytest.mark.asyncio
async def test_panel_step_needs_the_selfsteal_profile(monkeypatch):
    monkeypatch.setattr(rw_steps, "panel_api", Panel())
    plan = rw_plan.PlanIn(mode="node", node_server_ids=[2], selfsteal_domain="node.example.com", tls="internal", transports=["xhttp"])
    with pytest.raises(rw_steps.StepError):
        await rw_steps.run_node_transports(rw_steps.Context(plan=plan, servers={}, secrets={}, state={}), {})
