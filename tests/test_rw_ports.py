"""Ports of the shop's servers (owner's task of 2026-11-13): what is needed, what the scan says, the install step."""
from types import SimpleNamespace

import pytest

from app import rw_plan, rw_ports


def test_required_follows_the_roles():
    node = rw_ports.required(["node", "selfsteal"], transports=["xhttp", "hysteria2", "cdn"], mtproto=8888, masque=2087, node_port=2222)
    assert [(p["proto"], p["port"], p["scope"]) for p in node] == [
        ("tcp", 80, "all"), ("tcp", 443, "all"), ("udp", 443, "all"), ("tcp", 2083, "all"), ("tcp", 2087, "all"),
        ("tcp", 2222, "panel"), ("tcp", 4443, "all"), ("tcp", 8888, "all")]
    panel = rw_ports.required(["panel", "subscription_page"])
    assert [(p["proto"], p["port"]) for p in panel] == [("tcp", 80), ("tcp", 443)] and "панель" in panel[1]["why"]
    both = rw_ports.required(["panel", "node"])
    assert "Caddy" in both[1]["why"] and "REALITY" in both[1]["why"]                      # one row, two reasons
    assert rw_ports.required(["node"]) == [{"proto": "tcp", "port": 443, "why": "нода: VLESS + REALITY", "scope": "all"}]
    assert rw_ports.required([]) == []


def test_spec_is_sorted_unique_and_safe():
    assert rw_ports.spec([{"proto": "udp", "port": 443}, {"proto": "tcp", "port": 443}, {"proto": "tcp", "port": 80},
                          {"proto": "tcp", "port": 443}, {"proto": "icmp", "port": 1}, {"proto": "tcp", "port": 70000}]) == "tcp/80,tcp/443,udp/443"
    assert rw_ports.spec([]) == ""


SCAN = """firewall ufw
allowed tcp 22
allowed any 443
allowed udp 443
listen tcp 22 sshd
listen tcp 443 xray
listen tcp 8080 python3
listen udp 443 xray
ssh 22
opened tcp/2087
ports=scan"""


def test_scan_is_parsed():
    out = rw_ports.parse_scan(SCAN)
    assert out["firewalls"] == ["ufw"] and out["ssh"] == [22] and out["opened"] == {("tcp", 2087)}
    assert out["allowed"] == {("tcp", 22), ("tcp", 443), ("udp", 443)}
    assert out["listening"][("tcp", 8080)] == "python3"
    assert rw_ports.parse_scan("listen tcp 1 x")["firewalls"] == ["none"]


def test_status_rows():
    scan = rw_ports.parse_scan(SCAN)
    need = rw_ports.required(["node", "selfsteal"], masque=2087, node_port=2222)
    rows = rw_ports.status(scan, need, {("tcp", 80): False, ("tcp", 443): True})
    by = {(r["proto"], r["port"]): r for r in rows}
    assert by[("tcp", 80)]["firewall"] == "closed" and by[("tcp", 80)]["required"] and by[("tcp", 80)]["reachable"] is False
    assert by[("tcp", 443)]["firewall"] == "open" and by[("tcp", 443)]["listening"] and by[("tcp", 443)]["process"] == "xray"
    assert by[("tcp", 2222)]["firewall"] == "panel_only"
    assert by[("tcp", 2087)]["opened_by_shop"] is True
    assert by[("tcp", 22)]["ssh"] is True and by[("tcp", 22)]["required"] is False
    assert by[("tcp", 8080)]["required"] is False and by[("tcp", 8080)]["firewall"] == "closed"
    open_all = rw_ports.status(rw_ports.parse_scan("firewall none"), need)
    assert all(r["firewall"] in ("open", "panel_only") for r in open_all)       # no firewall on the server: nothing it closes


def test_node_script_core_rules():
    core = rw_ports.CORE
    for needle in ("ufw allow", "--add-port", "-m comment --comment \"$tag\" -j ACCEPT", "meta l4proto", "ssh_ports", "exit 3", "reapply",
                   "netfilter-persistent"):
        assert needle in core, needle
    assert "ufw enable" not in core and "--set-default" not in core and "-P INPUT" not in core.split("ipt_closing")[2]   # never turns a firewall on
    assert "corgi-ports.service" in rw_ports.NODE and "CORGI_PORTS_CORE" in rw_ports.NODE


def test_install_plan_opens_the_ports():
    plan = rw_plan.PlanIn(mode="distributed", panel_server_id=1, subpage_server_id=1, node_server_ids=[2], panel_domain="panel.example.com",
                          sub_domain="sub.example.com", acme_email="a@example.com", selfsteal_domain="node.example.com",
                          transports=["xhttp", "hysteria2"])
    servers = {1: {"name": "panel", "host": "198.51.100.1"}, 2: {"name": "de-1", "host": "198.51.100.2"}}
    built = rw_plan.build_plan(plan, servers, None)
    ports = [s for s in built["steps"] if s["params"].get("module") == "ports"]
    assert [(s["server_id"], rw_ports.spec(s["params"]["ports"])) for s in ports] == [(1, "tcp/80,tcp/443"), (2, "tcp/80,tcp/443,udp/443,tcp/4443")]
    assert built["steps"].index(ports[-1]) < len(built["steps"]) - 1 and built["steps"][-1]["kind"] == "verify"
    assert any("брандмауэрах сервера" in c for c in built["servers"]["2"]["changes"])


class Ctx:
    def __init__(self):
        self.state, self.notes = {}, []


@pytest.mark.asyncio
async def test_install_step_opens_and_undo_closes_only_what_it_opened(monkeypatch):
    from app import rw_steps
    calls = []

    async def run(ctx, sid, script, *args, **kw):
        calls.append(args)
        if args[0] == "scan":
            return SimpleNamespace(code=0, out="firewall iptables\nopened tcp/80\nports=scan", err="")
        return SimpleNamespace(code=0, out="ports=" + args[0], err="")

    monkeypatch.setattr(rw_steps, "_run", run)
    monkeypatch.setattr(rw_steps, "_note", lambda ctx, text: ctx.notes.append(text))
    monkeypatch.setattr(rw_steps, "_modules", lambda ctx, sid: {})
    ctx = Ctx()
    st = {"server_id": 2, "params": {"module": "ports", "ports": rw_ports.required(["node", "selfsteal"])}}
    await rw_steps.run_node_module(ctx, st)
    assert calls[:2] == [("scan",), ("open", "tcp/80,tcp/443")]
    assert ctx.state["ports_opened"] == {"2": ["tcp/443"]} and any("iptables" in n for n in ctx.notes)
    await rw_steps.undo_node_module(ctx, st)
    assert calls[-1] == ("close", "tcp/443")                                            # 80 was opened before: it stays


@pytest.mark.asyncio
async def test_install_step_fails_on_a_refused_rule(monkeypatch):
    from app import rw_steps

    async def run(ctx, sid, script, *args, **kw):
        return SimpleNamespace(code=0 if args[0] == "scan" else 4, out="firewall none", err="")

    monkeypatch.setattr(rw_steps, "_run", run)
    monkeypatch.setattr(rw_steps, "_note", lambda ctx, text: None)
    monkeypatch.setattr(rw_steps, "_modules", lambda ctx, sid: {})
    with pytest.raises(rw_steps.StepError, match="Брандмауэр сервера не принял правило"):
        await rw_steps.run_node_module(Ctx(), {"server_id": 2, "params": {"module": "ports", "ports": [{"proto": "tcp", "port": 443}]}})
