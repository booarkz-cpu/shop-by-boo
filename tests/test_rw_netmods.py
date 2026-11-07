"""v28.92.0 (stage 20, N7): server modules of «Установка» — MSS clamp, node guard (nftables), swap.

The plans and the steps here (fake SSH); the scripts themselves run for real in CI (scripts/ci/netmods-check.sh: a
flood is banned, an allowed address is not, path MTU 1400 → MSS 1360, a swap file on and off)."""
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app import rw_netmods, rw_plan, rw_steps

SERVERS = {2: {"name": "n2", "host": "93.184.216.40"}, 3: {"name": "p3", "host": "93.184.216.41"}}


def plan_with(**module) -> rw_plan.PlanIn:
    return rw_plan.PlanIn(mode="add_node", node_server_ids=[2], module=rw_plan.ModuleRun(**module))


def test_plans_of_the_three_modules():
    steps, title = rw_plan.module_steps(plan_with(name="node_guard", guard_rate=80, guard_allow=["203.0.113.9"]), SERVERS, {2: ["node"]})
    assert title == "Защита ноды (nftables): включить" and len(steps) == 1
    p = steps[0]["params"]
    assert (p["module"], p["ports"], p["rate"], p["allow"], p["mode"]) == ("node_guard", [443, 2053, 4443, 8443], 80, ["203.0.113.9/32"], "enforce")
    assert "80 новых соединений/с" in steps[0]["title"]
    steps, _ = rw_plan.module_steps(plan_with(name="mss_clamp"), SERVERS, {2: ["node"]})
    assert "MTU пути" in steps[0]["title"]
    steps, _ = rw_plan.module_steps(plan_with(name="swap", swap_mb=2048, server_ids=[2, 3]), SERVERS, {2: ["node"], 3: ["panel"]})
    assert [s["server_id"] for s in steps] == [2, 3] and steps[0]["params"]["swap_mb"] == 2048, "swap — on any server of the installation"
    with pytest.raises(ValueError):
        rw_plan.module_steps(plan_with(name="node_guard", guard_ports=[0]), SERVERS, {2: ["node"]})
    with pytest.raises(ValueError):
        rw_plan.module_steps(plan_with(name="node_guard", guard_allow=["not-an-ip"]), SERVERS, {2: ["node"]})
    with pytest.raises(ValidationError):
        rw_plan.ModuleRun(name="swap", swap_mb=100)
    with pytest.raises(ValidationError):
        rw_plan.ModuleRun(name="node_guard", guard_rate=1)


def test_scripts_are_valid_and_refuse_bad_arguments():
    for script in (rw_netmods.MSS, rw_netmods.GUARD, rw_netmods.SWAP):
        assert subprocess.run(["bash", "-n"], input=script, text=True).returncode == 0
    for args in (["on", "443;id", "5", "-", "enforce"], ["on", "443", "5x", "-", "enforce"], ["on", "443", "5", "1.2.3.4;id", "enforce"],
                 ["on", "443", "5", "-", "both"], ["nope"]):
        assert subprocess.run(["bash", "-c", rw_netmods.GUARD, "g", *args], capture_output=True).returncode == 2, args
    for args in (["on", "12;id"], ["on", "100"], ["on", "99999"], ["nope"]):
        assert subprocess.run(["bash", "-c", rw_netmods.SWAP, "s", *args], capture_output=True).returncode == 2, args
    assert "100.64.0.0/10" in rw_netmods.GUARD, "CGNAT is never limited"
    assert "inet corgi_guard" in rw_netmods.GUARD and "inet corgi_mss" in rw_netmods.MSS and "ufw" not in rw_netmods.GUARD


@pytest.mark.asyncio
async def test_steps_pass_the_shop_and_panel_addresses_and_undo(monkeypatch):
    calls = []
    answers = {}

    async def run(ctx, sid, script, *args, timeout=0):
        calls.append((script, args))
        return answers.get(script, SimpleNamespace(code=0, out="guard=enforce ports=443 rate=80\n", err=""))

    async def client(ctx, sid):
        return "198.51.100.1"

    monkeypatch.setattr(rw_steps, "_run", run)
    monkeypatch.setattr(rw_steps, "_client_address", client)
    plan = rw_plan.PlanIn(mode="add_node", node_server_ids=[2])
    ctx = rw_steps.Context(plan=plan, servers=SERVERS, secrets={}, state={}, shop_panel_url="https://198.51.100.7")
    st = {"server_id": 2, "params": {"module": "node_guard", "enabled": True, "ports": [443, 8443], "rate": 80,
                                     "allow": ["203.0.113.9/32"], "mode": "enforce"}}
    await rw_steps.run_node_module(ctx, st)
    script, args = calls[-1]
    assert script is rw_netmods.GUARD and args == ("on", "443,8443", "80", "203.0.113.9/32,198.51.100.1,198.51.100.7", "enforce")
    assert ctx.state["modules"]["2"]["node_guard"].startswith("guard=enforce")
    await rw_steps.undo_node_module(ctx, st)
    assert calls[-1] == (rw_netmods.GUARD, ("off",)), "undo switches the guard off"

    answers[rw_netmods.SWAP] = SimpleNamespace(code=5, out="nospace free=900M\n", err="")
    with pytest.raises(rw_steps.StepError, match="Мало места"):
        await rw_steps.run_node_module(ctx, {"server_id": 2, "params": {"module": "swap", "enabled": True, "swap_mb": 2048}})
    assert calls[-1] == (rw_netmods.SWAP, ("on", "2048"))
    answers[rw_netmods.MSS] = SimpleNamespace(code=6, out="", err="")
    with pytest.raises(rw_steps.StepError, match="MTU пути"):
        await rw_steps.run_node_module(ctx, {"server_id": 2, "params": {"module": "mss_clamp", "enabled": True}})


@pytest.mark.asyncio
async def test_sni_scan_is_read_only_and_ranks_the_candidates(monkeypatch):
    steps, title = rw_plan.module_steps(plan_with(name="sni_scan"), SERVERS, {2: ["node"]})
    assert title == "Подбор сайта для REALITY" and "ничего не меняется" in steps[0]["title"]
    assert subprocess.run(["bash", "-n"], input=rw_netmods.SNI_SCAN, text=True).returncode == 0
    out = "ok 120 www.apple.com X25519MLKEM768\nno 30 www.bad.example\nok 45 dl.google.com X25519\nweird line\n"
    assert [r["host"] for r in rw_netmods.parse_sni(out)] == ["dl.google.com", "www.apple.com"]
    calls = []

    async def run(ctx, sid, script, *args, timeout=0):
        calls.append(args)
        return SimpleNamespace(code=0, out=out, err="")

    monkeypatch.setattr(rw_steps, "_run", run)
    ctx = rw_steps.Context(plan=rw_plan.PlanIn(mode="add_node", node_server_ids=[2]), servers=SERVERS, secrets={}, state={})
    await rw_steps.run_node_module(ctx, {"server_id": 2, "params": {"module": "sni_scan", "enabled": True}})
    assert calls[0] == rw_netmods.SNI_CANDIDATES and len(calls[0]) >= 25
    assert ctx.state["modules"]["2"]["sni_scan"] == "dl.google.com, www.apple.com"
    assert ctx.state["sni_scan"]["2"][0] == {"host": "dl.google.com", "ms": 45, "group": "X25519"}


# ---- v28.94.0 (N7): MTProto proxy for Telegram


def test_mtproto_plan_refuses_the_node_ports():
    steps, title = rw_plan.module_steps(plan_with(name="mtproto", mtproto_port=9443, mtproto_domain="www.cloudflare.com"), SERVERS, {2: ["node"]})
    assert title == "MTProto-прокси для Telegram: включить" and len(steps) == 1
    assert steps[0]["params"] == {"module": "mtproto", "enabled": True, "mtproto_port": 9443, "mtproto_domain": "www.cloudflare.com"}
    assert "TCP 9443" in steps[0]["title"] and "www.cloudflare.com" in steps[0]["title"]
    for taken in (443, 2053, 4443, 8443, 2222):  # REALITY, the extra transports, the node's port for the panel
        if taken >= 1024:
            with pytest.raises(ValueError, match="занят нодой"):
                rw_plan.module_steps(plan_with(name="mtproto", mtproto_port=taken), SERVERS, {2: ["node"]})
    with pytest.raises(ValidationError):
        rw_plan.ModuleRun(name="mtproto", mtproto_port=443)  # below 1024: the container has no capabilities
    with pytest.raises(ValidationError):
        rw_plan.ModuleRun(name="mtproto", mtproto_domain="evil.com;id")
    with pytest.raises(ValueError, match="ноды"):
        rw_plan.module_steps(plan_with(name="mtproto", server_ids=[3]), SERVERS, {2: ["node"], 3: ["panel"]})
    off, _ = rw_plan.module_steps(plan_with(name="mtproto", enabled=False, mtproto_port=443 + 10000), SERVERS, {2: ["node"]})
    assert "убрать MTProto" in off[0]["title"]


def test_mtproto_script_refuses_bad_arguments_and_unpinned_images():
    assert subprocess.run(["bash", "-n"], input=rw_netmods.MTPROTO, text=True).returncode == 0
    image = rw_netmods.MTPROTO_IMAGE
    assert image.startswith("nineseconds/mtg:2@sha256:") and len(image.split("@sha256:")[1]) == 64
    for args in (["on", "9443;id", "a.b", image], ["on", "0", "a.b", image], ["on", "70000", "a.b", image], ["on", "9443", "A B", image],
                 ["on", "9443", "a.b", "nineseconds/mtg:latest"], ["on", "9443", "a.b", "evil/mtg@sha256:" + "0" * 64], ["nope"]):
        assert subprocess.run(["bash", "-c", rw_netmods.MTPROTO, "m", *args], capture_output=True).returncode == 2, args
    assert "--cap-drop ALL" in rw_netmods.MTPROTO and "--read-only" in rw_netmods.MTPROTO


def test_mtproto_link():
    link = rw_netmods.mtproto_link("93.184.216.40", "mtproto=on port=9443 domain=www.cloudflare.com secret=ee0011")
    assert link == {"port": 9443, "domain": "www.cloudflare.com", "tg": "tg://proxy?server=93.184.216.40&port=9443&secret=ee0011",
                    "https": "https://t.me/proxy?server=93.184.216.40&port=9443&secret=ee0011"}
    assert rw_netmods.mtproto_link("h", "mtproto=off") == {} and rw_netmods.mtproto_link("h", "") == {}


@pytest.mark.asyncio
async def test_mtproto_step_keeps_the_secret_out_of_the_log_and_undoes(monkeypatch):
    calls = []
    answer = SimpleNamespace(code=0, out="pulled\nmtproto=on port=9443 domain=www.cloudflare.com secret=eeabcdef0123456789\n", err="")

    async def run(ctx, sid, script, *args, timeout=0):
        calls.append((script, args))
        return answer
    monkeypatch.setattr(rw_steps, "_run", run)
    ctx = rw_steps.Context(plan=rw_plan.PlanIn(mode="add_node", node_server_ids=[2]), servers=SERVERS, secrets={}, state={})
    st = {"server_id": 2, "params": {"module": "mtproto", "enabled": True, "mtproto_port": 9443, "mtproto_domain": "www.cloudflare.com"}}
    await rw_steps.run_node_module(ctx, st)
    assert calls[-1] == (rw_netmods.MTPROTO, ("on", "9443", "www.cloudflare.com", rw_netmods.MTPROTO_IMAGE))
    assert ctx.state["mtproto"]["2"]["tg"] == "tg://proxy?server=93.184.216.40&port=9443&secret=eeabcdef0123456789"
    assert ctx.state["modules"]["2"]["mtproto"] == "TCP 9443, www.cloudflare.com"
    assert "eeabcdef" not in "\n".join(ctx.log) and "secret=[скрыто]" in "\n".join(ctx.log)
    await rw_steps.undo_node_module(ctx, st)
    assert calls[-1] == (rw_netmods.MTPROTO, ("off",))
    answer = SimpleNamespace(code=5, out="busy\n", err="")
    with pytest.raises(rw_steps.StepError, match="занят"):
        await rw_steps.run_node_module(ctx, st)
    answer = SimpleNamespace(code=0, out="mtproto=off\n", err="")
    await rw_steps.run_node_module(ctx, {"server_id": 2, "params": {"module": "mtproto", "enabled": False}})
    assert "2" not in ctx.state["mtproto"] and ctx.state["modules"]["2"]["mtproto"] == "off"
