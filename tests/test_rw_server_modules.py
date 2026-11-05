"""v28.84.0 (stage 19, part B, from remnawave-manager): «Защита сервера», «Самовосстановление» and node management.

The plan rules, the closed scripts' safety (own files, the shop's address always allowed), the step's handling of the
server's answers, and the admin endpoints that turn a node off/on and move it. The real server run is in
tests/live/test_node_modules_live.py."""
import pytest
from pydantic import ValidationError

from app import rw_plan, rw_steps
from app.rw_remote import Result

SERVERS = {1: {"name": "panel", "host": "93.184.216.30"}, 2: {"name": "n2", "host": "93.184.216.40"}}


def test_hardening_input_and_plan():
    h = rw_plan.Hardening(admin_ips=["203.0.113.10", "198.51.100.0/24", "203.0.113.10"])
    assert h.admin_ips == ["203.0.113.10/32", "198.51.100.0/24"]
    for bad in (["not-an-ip"], ["0.0.0.0/0"], ["10.0.0.0/8"]):
        with pytest.raises(ValidationError):
            rw_plan.Hardening(admin_ips=bad)
    plan = rw_plan.PlanIn(mode="node", node_server_ids=[2], module=rw_plan.ModuleRun(name="hardening", hardening=h, server_ids=[2]))
    steps, title = rw_plan.module_steps(plan, SERVERS, {2: ["node"]})
    assert [s["kind"] for s in steps] == ["node_module"] and title == "Защита сервера"
    assert "SSH только с 203.0.113.10/32, 198.51.100.0/24 и адреса магазина" in steps[0]["title"]
    assert steps[0]["params"]["hardening"]["admin_ips"] == ["203.0.113.10/32", "198.51.100.0/24"]
    plan.module = rw_plan.ModuleRun(name="watchdog", enabled=True)
    steps, title = rw_plan.module_steps(plan, SERVERS, {1: ["panel"], 2: ["node"]})
    assert [s["server_id"] for s in steps] == [1, 2] and title == "Самовосстановление: включить"
    plan.module = rw_plan.ModuleRun(name="watchdog", server_ids=[9])
    with pytest.raises(ValueError):
        rw_plan.module_steps(plan, SERVERS, {2: ["node"]})


def test_scripts_touch_only_their_own_files():
    script = rw_steps.HARDEN
    for own in ("/etc/fail2ban/jail.d/corgi.local", "/etc/apt/apt.conf.d/21corgi-auto-upgrades", "/etc/apt/apt.conf.d/52corgi-unattended",
                "/etc/sysctl.d/99-corgi-bbr.conf"):
        assert own in script
    assert "jail.local" not in script.replace("corgi.local", "") and "daemon.json" not in script
    assert 'exit 7' in script and '"$me"' in script, "no SSH allowlist without the shop's own address"
    assert "Automatic-Reboot \"false\"" in script
    w = rw_steps.WATCHDOG
    assert "OnUnitActiveSec=2min" in w and "127.0.0.1:3001/health" in w and '"$n" -ge 3' in w
    assert rw_steps.CLIENT_ADDRESS == 'echo "${SSH_CONNECTION%% *}"'


class Remote:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def run(self, script, *args, stdin=None, timeout=900, root=True):
        self.calls.append((script, args, root))
        return self.answers.get(script, Result(0, "", ""))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ctx_with(remote):
    plan = rw_plan.PlanIn(mode="node", node_server_ids=[2])
    return rw_steps.Context(plan=plan, servers={2: SERVERS[2]}, secrets={}, state={}, connect=lambda server: remote)


@pytest.mark.asyncio
async def test_hardening_step_passes_the_shop_address_and_reports_errors():
    remote = Remote({rw_steps.CLIENT_ADDRESS: Result(0, "198.51.100.7\n", ""), rw_steps.HARDEN: Result(0, "fail2ban=on upgrades=on bbr=bbr", "")})
    ctx = ctx_with(remote)
    st = {"server_id": 2, "params": {"module": "hardening", "hardening": {"fail2ban": True, "upgrades": False, "bbr": True, "admin_ips": ["203.0.113.10/32"]}}}
    await rw_steps.run_node_module(ctx, st)
    address, harden = remote.calls
    assert address[2] is False, "the address is read without sudo (sudo drops SSH_CONNECTION)"
    assert harden[1] == ("apply", "on", "off", "on", "203.0.113.10/32", "198.51.100.7")
    assert ctx.state["modules"]["2"]["hardening"]["admin_ips"] == ["203.0.113.10/32"]
    # Without an allowlist the address is not asked for.
    remote2 = Remote({})
    st2 = {"server_id": 2, "params": {"module": "hardening", "hardening": {"fail2ban": True, "upgrades": True, "bbr": False, "admin_ips": []}}}
    await rw_steps.run_node_module(ctx_with(remote2), st2)
    assert [c[1][-2:] for c in remote2.calls] == [("-", "-")]
    for code, text in ((6, "ufw выключен"), (5, "BBR"), (4, "apt"), (7, "адрес магазина")):
        failing = Remote({rw_steps.CLIENT_ADDRESS: Result(0, "198.51.100.7", ""), rw_steps.HARDEN: Result(code, "", "")})
        with pytest.raises(rw_steps.StepError, match=text):
            await rw_steps.run_node_module(ctx_with(failing), st)


@pytest.mark.asyncio
async def test_watchdog_step_needs_an_active_timer_and_undo_runs_the_script():
    ok = Remote({rw_steps.WATCHDOG: Result(0, "watchdog=active", "")})
    ctx = ctx_with(ok)
    st = {"server_id": 2, "params": {"module": "watchdog", "enabled": True}}
    await rw_steps.run_node_module(ctx, st)
    assert ctx.state["modules"]["2"]["watchdog"] is True
    await rw_steps.undo_node_module(ctx, st)
    assert ok.calls[-1][1] == ("undo",)
    with pytest.raises(rw_steps.StepError):
        await rw_steps.run_node_module(ctx_with(Remote({rw_steps.WATCHDOG: Result(0, "watchdog=failed", "")})), st)


@pytest.mark.asyncio
async def test_node_switch_and_patch(monkeypatch):
    from fastapi import HTTPException

    from app import main, node_health
    import app.remnawave as remnawave
    calls, audits = [], []

    class Client:
        async def enable_node(self, uuid): calls.append(("enable", uuid))
        async def disable_node(self, uuid): calls.append(("disable", uuid))
        async def update_node(self, uuid, patch): calls.append(("patch", uuid, patch))

    class Db:
        async def commit(self): pass

    async def audit(db, action, actor, target=None, details=None):
        audits.append((action, target, details))

    monkeypatch.setattr(remnawave, "RemnawaveClient", Client)
    monkeypatch.setattr(main, "audit", audit)
    admin = type("A", (), {"email": "boss@example.com"})()
    assert await node_health.node_switch("n-1", "disable", Db(), admin) == {"ok": True}
    assert await node_health.node_switch("n-1", "enable", Db(), admin) == {"ok": True}
    await node_health.node_patch("n-1", node_health.NodePatchIn(address="de2.example.com", port=2222), Db(), admin)
    assert calls == [("disable", "n-1"), ("enable", "n-1"), ("patch", "n-1", {"address": "de2.example.com", "port": 2222})]
    assert [a[0] for a in audits] == ["nodes.disable", "nodes.enable", "nodes.update"]
    with pytest.raises(HTTPException):
        await node_health.node_switch("../x", "disable", Db(), admin)
    with pytest.raises(HTTPException):
        await node_health.node_patch("n-1", node_health.NodePatchIn(), Db(), admin)
    with pytest.raises(ValidationError):
        node_health.NodePatchIn(address="evil.com; rm -rf /")
