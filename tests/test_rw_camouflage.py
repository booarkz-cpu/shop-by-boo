"""v28.90.0 (stage 20, N5 and N6): one node with every protocol, the browser fingerprint and the TLS versions from the
admin panel, and the node's port closed to everyone but the panel.

* N5 — the uTLS fingerprint (Firefox by default) on every host of the SelfSteal profile except Hysteria2 (QUIC), also
  on hosts that existed before, with undo; all four protocols plus VLESS + TCP + TLS in one module action;
* N5 — the node's port: an nftables table of its own (always, not only with ufw), the extra addresses for a panel move,
  a module action for every node at once, and «verify» takes the rule back when the panel stops seeing a node;
* N6 — TLS 1.2 / 1.3 for VLESS + TCP + TLS (REALITY and Hysteria2 work only over TLS 1.3).

scripts/ci/node-port-guard.sh runs FIREWALL itself in network namespaces (CI «Containers»)."""
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app import rw_plan, rw_steps
from test_rw_transports import BASE, SERVERS, Panel

DOMAIN = "node.example.com"


def selfsteal(**kw) -> rw_plan.PlanIn:
    return rw_plan.PlanIn(mode="node", node_server_ids=[2], selfsteal_domain=DOMAIN, tls="internal", **kw)


def test_defaults_and_validation():
    plan = selfsteal()
    assert (plan.fingerprint, plan.tls_min, plan.tls_max) == ("firefox", "1.3", "1.3")
    with pytest.raises(ValidationError):
        selfsteal(fingerprint="netscape")
    with pytest.raises(ValidationError):
        selfsteal(tls_min="1.3", tls_max="1.2")
    with pytest.raises(ValidationError):
        selfsteal(tls_min="1.1")
    with pytest.raises(ValidationError):
        selfsteal(node_port_ips=["not-an-ip"])
    with pytest.raises(ValidationError):
        selfsteal(node_port_ips=["10.0.0.0/8"])  # too wide
    assert selfsteal(node_port_ips=["198.51.100.7", "198.51.100.7/32", "2001:db8::1"]).node_port_ips == ["198.51.100.7/32", "2001:db8::1/128"]
    every = selfsteal(transports=["tls", "hysteria2", "grpc", "xhttp"])
    assert every.transports == ["grpc", "hysteria2", "tls", "xhttp"]
    assert set(rw_plan.TRANSPORTS) == {"xhttp", "grpc", "hysteria2", "tls", "cdn"}  # v28.98.0: «cdn» — only through the module «Cloudflare CDN»


def test_tls_inbound_takes_the_chosen_versions():
    got = {i["tag"]: i for i in rw_steps.transport_inbounds(BASE, DOMAIN, ["tls", "hysteria2"], "1.2", "1.3")}
    tls = got["VLESS_TCP_TLS"]
    stream = tls["streamSettings"]
    assert tls["port"] == 2053 and tls["protocol"] == "vless" and stream["network"] == "tcp" and stream["security"] == "tls"
    settings = stream["tlsSettings"]
    assert (settings["minVersion"], settings["maxVersion"]) == ("1.2", "1.3") and settings["serverName"] == DOMAIN
    assert settings["certificates"][0]["certificateFile"] == f"{rw_plan.HYSTERIA_MOUNT}/cert.pem"
    assert "minVersion" not in got["HYSTERIA2"]["streamSettings"]["tlsSettings"], "QUIC is TLS 1.3 only"
    # The node mounts the certificate for the TLS inbound too, and the script copies it for either.
    plan = selfsteal(transports=["tls"])
    files = rw_plan.node_compose("key", 2222, selfsteal=True, hysteria=bool({"hysteria2", "tls"} & set(plan.transports)))
    assert rw_plan.HYSTERIA_MOUNT in files
    assert '[ "$hy" = on ] || [ "$tls" = on ]' in rw_steps.TRANSPORTS_SH and "port 2053/tcp" in rw_steps.TRANSPORTS_SH


def test_hosts_get_the_fingerprint_except_quic():
    assert rw_steps.transport_host("grpc", DOMAIN, "p", "i", "x", "safari")["fingerprint"] == "safari"
    assert rw_steps.transport_host("tls", DOMAIN, "p", "i", "x")["fingerprint"] == "firefox"
    assert "fingerprint" not in rw_steps.transport_host("hysteria2", DOMAIN, "p", "i", "x", "chrome")


class FingerprintPanel(Panel):
    async def __call__(self, ctx, method, path, body=None, **kw):
        if path == "/api/hosts" and method == "PATCH":
            self.calls.append((method, path))
            next(h for h in self.hosts if h["uuid"] == body["uuid"])["fingerprint"] = body["fingerprint"]
            return {}
        return await super().__call__(ctx, method, path, body, **kw)


@pytest.mark.asyncio
async def test_every_protocol_in_one_action_with_the_fingerprint_and_undo(monkeypatch):
    panel = FingerprintPanel()
    panel.hosts[0]["fingerprint"] = "chrome"  # the SelfSteal host made before the fingerprint setting
    monkeypatch.setattr(rw_steps, "panel_api", panel)
    plan = selfsteal(transports=["xhttp", "grpc", "hysteria2", "tls"], fingerprint="firefox", tls_min="1.2")
    ctx = rw_steps.Context(plan=plan, servers={}, secrets={}, state={"selfsteal_profile": "prof", "nodes": {"2": "node-2"}})
    await rw_steps.run_node_transports(ctx, {})
    tags = [i["tag"] for i in panel.config["inbounds"]]
    assert tags == ["VLESS_TCP_REALITY", "VLESS_GRPC_REALITY", "HYSTERIA2", "VLESS_TCP_TLS", "VLESS_XHTTP_REALITY"]
    tls = next(i for i in panel.config["inbounds"] if i["tag"] == "VLESS_TCP_TLS")["streamSettings"]["tlsSettings"]
    assert (tls["minVersion"], tls["maxVersion"]) == ("1.2", "1.3")
    by_inbound = {h["inbound"]["configProfileInboundUuid"]: h for h in panel.hosts}
    assert by_inbound["in-VLESS_TCP_REALITY"]["fingerprint"] == "firefox", "the old host is switched too"
    assert {by_inbound[f"in-{t}"].get("fingerprint") for t in ("VLESS_GRPC_REALITY", "VLESS_TCP_TLS", "VLESS_XHTTP_REALITY")} == {"firefox"}
    assert "fingerprint" not in by_inbound["in-HYSTERIA2"]
    assert panel.nodes["node-2"]["activeInbounds"] == [f"in-{t}" for t in tags]
    # Undo: the old set of transports and the old fingerprint of the host that existed before.
    await rw_steps.undo_node_transports(ctx, {})
    assert [i["tag"] for i in panel.config["inbounds"]] == ["VLESS_TCP_REALITY"]
    assert panel.hosts[0]["fingerprint"] == "chrome"


def test_module_actions():
    plan = selfsteal(transports=["tls"], fingerprint="ios", tls_min="1.2", tls_max="1.2")
    plan.module = rw_plan.ModuleRun(name="transports", transports=["tls"])
    steps, title = rw_plan.module_steps(plan, SERVERS, {2: ["node"]})
    assert "отпечаток iOS" in title and "TLS 1.2–1.2" in title
    servers = {2: {"name": "n2", "host": "93.184.216.40"}, 3: {"name": "n3", "host": "93.184.216.41"}}
    plan = rw_plan.PlanIn(mode="add_node", node_server_ids=[2, 3], node_port_ips=["203.0.113.9"],
                          module=rw_plan.ModuleRun(name="node_port", enabled=True))
    steps, title = rw_plan.module_steps(plan, servers, {2: ["node"], 3: ["node"]})
    assert [s["kind"] for s in steps] == ["node_module", "node_module", "verify"], "every node at once, then the panel check"
    assert all(s["params"]["module"] == "node_port" and s["params"]["ips"] == ["203.0.113.9/32"] for s in steps[:2])
    assert "203.0.113.9/32" in steps[0]["title"]
    with pytest.raises(ValueError):
        rw_plan.module_steps(rw_plan.PlanIn(mode="add_node", node_server_ids=[2], module=rw_plan.ModuleRun(name="node_port", server_ids=[9])),
                             servers, {2: ["node"]})
    built = rw_plan.build_plan(rw_plan.PlanIn(mode="add_node", node_server_ids=[2]), SERVERS, "https://panel.shop.example")
    assert any("nftables" in c for c in built["servers"]["2"]["changes"])


def test_firewall_script_is_closed_and_valid_shell():
    script = rw_steps.FIREWALL
    assert subprocess.run(["bash", "-n"], input=script, text=True).returncode == 0
    assert "inet corgi_node_port" in script and "priority -10" in script and "counter drop" in script
    assert 'case "$ips" in ""|*[!0-9a-fA-F.:/,]*)' in script and 'case "$port" in ""|*[!0-9]*)' in script
    assert "nft -c -f" in script, "the table is checked before it is loaded"
    assert "ufw нет" not in script, "the rule no longer depends on ufw"
    for bad in (["1.2.3.4;reboot", "2222", "add"], ["1.2.3.4", "22 22", "add"]):
        out = subprocess.run(["bash", "-c", script, "fw", *bad], capture_output=True, text=True)
        assert out.returncode == 2


@pytest.mark.asyncio
async def test_node_port_step_and_auto_removal(monkeypatch):
    calls = []

    async def run(ctx, sid, script, *args, timeout=0):
        calls.append((sid, script is rw_steps.FIREWALL, args))
        return SimpleNamespace(code=0, out="nft=on", err="")

    monkeypatch.setattr(rw_steps, "_run", run)
    servers = {2: {"name": "n2", "host": "93.184.216.40"}}
    plan = rw_plan.PlanIn(mode="add_node", node_server_ids=[2], node_port_ips=["203.0.113.9"])
    ctx = rw_steps.Context(plan=plan, servers=servers, secrets={}, state={}, shop_panel_url="https://198.51.100.1")
    await rw_steps.run_node_module(ctx, {"server_id": 2, "params": {"module": "node_port", "enabled": True}})
    assert calls[-1] == (2, True, ("198.51.100.1,203.0.113.9/32", "2222", "add"))
    assert ctx.state["firewall"]["2"] == "198.51.100.1,203.0.113.9/32"
    # Undo of the module returns the port to how it was (open: no rule before).
    await rw_steps.undo_node_module(ctx, {"server_id": 2, "params": {"module": "node_port", "enabled": True}})
    assert calls[-1][2][-1] == "delete" and "2" not in ctx.state["firewall"]

    # «verify»: the panel does not see the node — the rule is taken back and the problem is reported.
    ctx.state.update(firewall={"2": "198.51.100.1"}, nodes={"2": "node-2"})

    async def panel(ctx, method, path, body=None, **kw):
        return {"isConnected": False}

    async def no_sleep(_):
        return None

    monkeypatch.setattr(rw_steps, "panel_api", panel)
    monkeypatch.setattr(rw_steps, "_sleep", no_sleep)
    with pytest.raises(rw_steps.StepError) as err:
        await rw_steps.run_verify(ctx, {})
    assert "правило порта ноды" in str(err.value)
    assert calls[-1] == (2, True, ("198.51.100.1", "2222", "delete")) and "2" not in ctx.state["firewall"]
