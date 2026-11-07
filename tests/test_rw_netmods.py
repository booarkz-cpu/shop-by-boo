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
