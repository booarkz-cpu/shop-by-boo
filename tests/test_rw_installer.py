"""v28.66.0 (stage 10): the Remnawave installation wizard against a fake SSH server (mock tests; the real install
runs in CI in tests/live/test_install_live.py).

* a server enters the registry only with a pinned host key and a valid key or password; secrets never come back;
* the preflight reads OS, architecture, CPU, RAM, disk, Docker, ports, services and DNS and blocks on errors;
* all seven modes build a plan from the closed list of steps; a plan runs only after approval of its exact hash;
* «panel + node» runs end to end: files written with SHA-256 check, panel admin and API token created, node
  registered and connected, HTTPS verified; secrets are encrypted and masked in the logs;
* a failed step rolls back what was done; cancel stops a run; a dead worker's run becomes «failed»;
* update / diagnose / restore / reinstall / remove are plans over a successful installation;
* connecting the shop stages REMNAWAVE_URL and REMNAWAVE_TOKEN in the runtime settings (two-step apply)."""
import hashlib
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app import rw_api, rw_jobs, rw_plan, rw_steps
from app.config import settings
from app.models import AuditLog, RemnawaveDeploymentStep, RemnawaveInstallation, RemnawaveServer
from app.provisioner import DOCKER_INSTALL
from app.rw_remote import Result
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test", role="admin")
FP = "SHA256:" + "A" * 43


def facts(**over):
    base = {"os_id": "ubuntu", "os_version": "24.04", "os_name": "Ubuntu 24.04.3 LTS", "arch": "x86_64", "cpu": "2",
            "ram_mb": "4096", "disk_gb": "40", "root": "yes", "docker": "none", "compose": "none", "ufw": "active",
            "public_ip": "198.51.100.10"}
    base.update(over)
    lines = [f"{k}={v}" for k, v in base.items() if v is not None]
    return lines


class Host:
    """One fake server: files, containers, and (on the panel's server) a fake Remnawave panel."""

    def __init__(self, ip, extra_lines=(), **over):
        self.ip = ip
        self.lines = facts(public_ip=ip, **over) + list(extra_lines)
        self.files, self.up, self.calls, self.rules = {}, set(), [], []
        self.fail = set()
        self.users, self.tokens, self.nodes, self.backups = {}, [], {}, 0
        self.log_secret = ""

    def facts_text(self, domains):
        return "\n".join(self.lines + [f"dns={d} {self.ip}" for d in domains]) + "\n"

    def panel(self, method, path, token, body):
        if path == "/api/auth/register":
            if body["username"] in self.users:
                return 400, {}
            self.users[body["username"]] = body["password"]
            return 201, {"response": {"accessToken": "jwt-admin"}}
        if path == "/api/auth/login":
            return 200, {"response": {"accessToken": "jwt-admin"}}
        if path == "/api/tokens":
            assert token == "jwt-admin" and body["name"] == "corgi-shop"
            self.tokens.append("rw-api-token-0123456789")
            return 201, {"response": {"token": self.tokens[-1]}}
        assert token in self.tokens, path
        if path == "/api/system/metadata":
            return 200, {"response": {"version": "3.4.8"}}
        if path == "/api/keygen":
            return 200, {"response": {"pubKey": "node-secret-key-from-panel"}}
        if path == "/api/config-profiles":
            return 200, {"response": {"configProfiles": [{"uuid": "prof-1", "inbounds": [{"uuid": "in-1"}]}]}}
        if path == "/api/nodes" and method == "POST":
            uuid = f"node-{len(self.nodes) + 1}"
            self.nodes[uuid] = body
            return 201, {"response": {"uuid": uuid}}
        if path.startswith("/api/nodes/") and method == "GET":
            return 200, {"response": {"uuid": path.rsplit("/", 1)[1], "isConnected": True}}
        if path.startswith("/api/nodes/") and method == "DELETE":
            self.nodes.pop(path.rsplit("/", 1)[1], None)
            return 200, {"response": {}}
        return 404, {}


SCRIPTS = {rw_steps.PREFLIGHT: "preflight", DOCKER_INSTALL: "docker", rw_steps.WRITE: "write", rw_steps.UNWRITE: "unwrite",
           rw_steps.COMPOSE: "compose", rw_steps.WAIT_PANEL: "wait", rw_steps.PANEL_CALL: "panel",
           rw_steps.FIREWALL: "firewall", rw_steps.GATEWAY: "gateway", rw_steps.HTTPS_CHECK: "https",
           rw_steps.BACKUP: "backup", rw_steps.RESTORE: "restore", rw_steps.FETCH_BACKUP: "fetch"}


class FakeRemote:
    def __init__(self, host):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def run(self, script, *args, stdin=None, timeout=900, root=True):
        name = SCRIPTS[script]  # anything else is not a script of the closed list
        h = self.host
        h.calls.append((name, args))
        if name in h.fail or (name, args[-1] if args else None) in h.fail:
            return Result(1, "", "boom")
        if name == "preflight":
            return Result(0, h.facts_text(args), "")
        if name == "write":
            directory, fname, digest = args
            assert hashlib.sha256(stdin).hexdigest() == digest
            prev = h.files.get((directory, fname))
            h.files[(directory, fname, "prev")] = prev
            h.files[(directory, fname)] = stdin.decode()
            return Result(0, "", "")
        if name == "unwrite":
            directory, fname = args
            prev = h.files.pop((directory, fname, "prev"), None)
            if prev is None:
                h.files.pop((directory, fname), None)
            else:
                h.files[(directory, fname)] = prev
            return Result(0, "", "")
        if name == "compose":
            directory, action = args[:2]
            if action in ("up", "start", "restart"):
                h.up.add(directory)
            elif action in ("down", "stop"):
                h.up.discard(directory)
            if action == "logs":  # v28.77.0: a container log with a secret in it
                return Result(0, f"remnawave | started\nremnawave | JWT_AUTH_SECRET=leaked-secret-value\n{h.log_secret}\n", "")
            return Result(0, f"{directory} {action}\n", "")
        if name == "panel":
            method, path, _browser = args
            token, _, body = stdin.decode().partition("\n")
            code, data = h.panel(method, path, token, json.loads(body) if body else None)
            return Result(0, json.dumps(data) + "\n" + str(code), "")
        if name == "firewall":
            h.rules.append(args)
            return Result(0, "Rule added\n", "")
        if name == "gateway":
            return Result(0, "172.18.0.1\n", "")
        if name in ("https", "selfsteal_check"):
            return Result(0, "200\n", "")
        if name == "backup":
            h.backups += 1
            return Result(0, f"/opt/remnawave/backups/panel-{h.backups}.dump 1024\n", "")
        if name == "fetch":
            import base64
            data = f"PGDMP panel copy {args[0]}".encode()
            return Result(0, hashlib.sha256(data).hexdigest() + "\n" + base64.b64encode(data).decode() + "\n", "")
        if name == "restore":
            return Result(0 if h.backups else 3, "/opt/remnawave/backups/panel-1.dump\n", "")
        return Result(0, "ok\n", "")


@pytest.fixture
def fleet(monkeypatch, tmp_path):
    hosts = {}
    monkeypatch.setenv("RW_PANEL_COPIES_DIR", str(tmp_path / "panel-copies"))

    def connect(server):
        return FakeRemote(hosts[server["host"]])
    monkeypatch.setattr(rw_jobs, "CONNECT", connect)
    monkeypatch.setattr(rw_api, "CONNECT", connect)
    # The heartbeat would open a second connection — to an empty database with sqlite :memory: — so it never fires here.
    monkeypatch.setattr(rw_jobs, "HEARTBEAT_SECONDS", 3600)
    monkeypatch.setattr(settings, "remnawave_url", "")
    monkeypatch.setattr(settings, "remnawave_token", "")

    async def no_sleep(*_):
        return None
    monkeypatch.setattr(rw_steps, "_sleep", no_sleep)
    return hosts


async def add_server(db, hosts, name, ip, purpose=("panel", "node"), **host_kw):
    hosts[ip] = Host(ip, **host_kw)
    out = await rw_api.create_server(rw_api.ServerIn(name=name, host=ip, auth_method="password", password="s3cret-pass",
                                                     host_key_fingerprint=FP, purpose=list(purpose)), db, ADMIN)
    return out


async def run_all(db):
    while await rw_jobs.run_next(db.bind, "test-worker"):
        pass
    await db.commit()
    db.expire_all()  # the runner wrote through its own sessions


def test_server_input_is_typed():
    with pytest.raises(ValidationError):
        rw_api.ServerIn(name="a", host="1.2.3.4; rm -rf /", auth_method="password", password="x", host_key_fingerprint=FP)
    with pytest.raises(ValidationError):  # no trust on first use: the fingerprint is required
        rw_api.ServerIn(name="node-1", host="198.51.100.4", auth_method="password", password="x")
    with pytest.raises(ValidationError):
        rw_api.ServerIn(name="node-1", host="127.0.0.1", auth_method="password", password="x", host_key_fingerprint=FP)
    with pytest.raises(ValidationError):  # a key that is not a key
        rw_api.ServerIn(name="node-1", host="198.51.100.4", auth_method="key", private_key="hello", host_key_fingerprint=FP)
    with pytest.raises(ValidationError):
        rw_api.ServerIn(name="node-1", host="198.51.100.4", auth_method="password", password="x", host_key_fingerprint=FP,
                        command="id")


@pytest.mark.asyncio
async def test_registry_check_and_secret_never_returned(database, fleet):
    db = database
    out = await add_server(db, fleet, "panel-1", "198.51.100.10")
    assert out["has_secret"] and '"password":' not in json.dumps(out) and "s3cret" not in json.dumps(out)
    row = await db.get(RemnawaveServer, out["id"])
    assert row.ssh_secret != "s3cret-pass" and "s3cret" not in row.ssh_secret
    checked = await rw_api.check_server(out["id"], db, ADMIN)
    assert checked["status"] == "ready" and checked["os"].startswith("Ubuntu 24.04") and checked["ram_mb"] == 4096
    keys = {c["key"]: c["status"] for c in checked["checks"]}
    assert keys["ssh"] == "ok" and keys["os"] == "ok" and keys["docker"] == "warn" and keys["port_443"] == "ok"
    assert (await rw_api.list_servers(db, ADMIN))["servers"][0]["id"] == out["id"]
    actions = (await db.execute(select(AuditLog.action).where(AuditLog.action.like("rw.%")))).scalars().all()
    assert "rw.server.created" in actions


def test_preflight_evaluation_blocks_on_conflicts():
    text = "\n".join(facts(ram_mb="900", disk_gb="3", root="no", arch="armv7l") +
                     ["listen=443 nginx", "listen=80 nginx", "service=nginx", "dns=panel.example.com 203.0.113.99"])
    checks = {c["key"]: c for c in rw_steps.evaluate(rw_steps.parse_facts(text), ["panel"], ["panel.example.com"], None,
                                                    "198.51.100.10", "acme")}
    for key in ("arch", "ram", "disk", "root", "port_443", "port_80", "service_nginx", "dns_panel.example.com"):
        assert checks[key]["status"] == "error", key
    again = "\n".join(facts() + ["listen=443 docker-proxy", "container=remnawave-caddy running"])
    checks = {c["key"]: c for c in rw_steps.evaluate(rw_steps.parse_facts(again), ["panel"], [], None, "198.51.100.10", "acme")}
    assert checks["port_443"]["status"] == "warn"  # our own Caddy from an earlier run is updated, never doubled
    foreign = "\n".join(facts() + ["listen=443 docker-proxy"])  # e.g. the shop's own Caddy: never replaced
    checks = {c["key"]: c for c in rw_steps.evaluate(rw_steps.parse_facts(foreign), ["panel"], [], None, "198.51.100.10", "acme")}
    assert checks["port_443"]["status"] == "error"


def test_all_seven_modes_build_plans_of_the_closed_list():
    servers = {i: {"name": f"s{i}", "host": f"198.51.100.{i}"} for i in range(1, 5)}
    payloads = {
        "panel_node": dict(panel_server_id=1, panel_domain="panel.example.com", acme_email="a@example.com"),
        "panel": dict(panel_server_id=1, panel_domain="panel.example.com", acme_email="a@example.com"),
        "node": dict(node_server_ids=[2]),
        "panel_subpage": dict(panel_server_id=1, panel_domain="panel.example.com", sub_domain="sub.example.com", acme_email="a@example.com"),
        "subpage": dict(subpage_server_id=3, sub_domain="sub.example.com", acme_email="a@example.com"),
        "distributed": dict(panel_server_id=1, panel_domain="panel.example.com", node_server_ids=[2, 4], subpage_server_id=3,
                            sub_domain="sub.example.com", acme_email="a@example.com"),
        "add_node": dict(node_server_ids=[2, 4]),
    }
    assert set(payloads) == set(rw_plan.MODES)
    for mode, extra in payloads.items():
        plan = rw_plan.build_plan(rw_plan.PlanIn(mode=mode, **extra), servers, "https://panel.shop.example")
        kinds = [s["kind"] for s in plan["steps"]]
        assert set(kinds) <= set(rw_steps.STEP_KINDS) and kinds[0] == "preflight" and kinds[-1] == "verify", mode
        assert ("panel_bootstrap" in kinds) == (mode in ("panel_node", "panel", "panel_subpage", "distributed")), mode
        assert kinds.count("register_node") == len(rw_plan.PlanIn(mode=mode, **extra).node_server_ids), mode
        assert all(s["changes"] for s in plan["servers"].values())
    with pytest.raises(ValidationError):
        rw_plan.PlanIn(mode="panel", panel_server_id=1, panel_domain="panel.example.com")  # ACME needs an email
    with pytest.raises(ValidationError):
        rw_plan.PlanIn(mode="distributed", panel_server_id=1, panel_domain="p.example.com", node_server_ids=[1], tls="internal")
    with pytest.raises(ValidationError):
        rw_plan.PlanIn(mode="panel", panel_server_id=1, panel_domain="evil.com\n{", tls="internal")
    with pytest.raises(ValueError):  # node only without a panel connected to the shop
        rw_plan.build_plan(rw_plan.PlanIn(mode="node", node_server_ids=[2]), servers, None)


def test_generated_files():
    plan = rw_plan.PlanIn(mode="panel_subpage", panel_server_id=1, panel_domain="panel.example.com", sub_domain="sub.example.com",
                          acme_email="a@example.com")
    secrets = rw_steps.new_secrets()
    env = rw_plan.panel_env(plan, secrets)
    assert f'POSTGRES_PASSWORD="{secrets["db_password"]}"' in env and 'SUB_PUBLIC_DOMAIN="sub.example.com"' in env
    compose = rw_plan.panel_compose()
    assert "127.0.0.1:3000:3000" in compose and "0.0.0.0" not in compose and "@sha256:" in compose
    caddy = rw_plan.caddyfile({"panel.example.com": 3000, "sub.example.com": 3010}, "acme", "a@example.com")
    assert "reverse_proxy 127.0.0.1:3000" in caddy and "tls internal" not in caddy and "email a@example.com" in caddy
    assert "tls internal" in rw_plan.caddyfile({"panel.example.com": 3000}, "internal", None)
    sub = rw_plan.subpage_env("https://panel.example.com", "tok", secrets, True)
    assert 'REMNAWAVE_PANEL_URL="http://remnawave:3000"' in sub
    node = rw_plan.node_compose("node-secret", 2222)
    assert rw_plan.IMAGES["node"] in node and "node-secret" in node
    password = secrets["panel_admin_password"]
    assert len(password) >= 24 and any(c.isupper() for c in password) and any(c.islower() for c in password) and any(c.isdigit() for c in password)
    with pytest.raises(ValueError):
        rw_plan._q("a\nb")


async def plan_and_approve(db, payload):
    planned = await rw_api.plan_installation(payload, db, ADMIN)
    with pytest.raises(HTTPException) as err:
        await rw_api.approve(planned["id"], rw_api.ApproveIn(plan_sha256="0" * 64), db, ADMIN)
    assert err.value.status_code == 409
    return await rw_api.approve(planned["id"], rw_api.ApproveIn(plan_sha256=planned["plan_sha256"]), db, ADMIN)


@pytest.mark.asyncio
async def test_panel_and_node_install_end_to_end(database, fleet, monkeypatch, tmp_path):
    db = database
    server = await add_server(db, fleet, "panel-1", "198.51.100.10")
    payload = rw_plan.PlanIn(mode="panel_node", panel_server_id=server["id"], panel_domain="panel.example.com", acme_email="a@example.com")
    with pytest.raises(HTTPException) as err:  # not checked yet
        await rw_api.plan_installation(payload, db, ADMIN)
    assert err.value.status_code == 422
    await rw_api.check_server(server["id"], db, ADMIN)

    class Shop:  # the shop-side HTTPS check of an ACME panel
        status_code = 200
    import httpx

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get(self, url, headers=None):
            assert url == "https://panel.example.com/api/auth/status"
            return Shop()
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    approved = await plan_and_approve(db, payload)
    assert approved["status"] == "queued" and approved["progress"] == 0
    await run_all(db)
    got = await rw_api.get_installation(approved["id"], db, ADMIN)
    assert got["status"] == "succeeded", got
    assert got["progress"] == 100 and all(s["status"] == "done" for s in got["steps"])
    host = fleet["198.51.100.10"]
    assert {"/opt/remnawave", "/opt/remnanode", "/opt/remnawave-caddy"} <= host.up
    assert "corgi-admin" in host.users and host.nodes["node-1"]["address"] == "172.18.0.1"
    assert host.nodes["node-1"]["configProfile"] == {"activeConfigProfileUuid": "prof-1", "activeInbounds": ["in-1"]}
    assert "node-secret-key-from-panel" in host.files[("/opt/remnanode", "docker-compose.yml")]
    assert not host.rules  # the node on the panel's server needs no firewall rule
    row = await db.get(RemnawaveInstallation, approved["id"])
    assert "rw-api-token" not in row.secrets and "rw-api-token" not in json.dumps(got)
    secrets = rw_jobs.load_secrets(row)
    logs = "\n".join(s.log_tail or "" for s in (await db.execute(select(RemnawaveDeploymentStep))).scalars())
    assert secrets["panel_admin_password"] not in logs and secrets["db_password"] not in logs
    assert got["result"]["panel_url"] == "https://panel.example.com"
    srv = await db.get(RemnawaveServer, server["id"])
    assert srv.status == "installed" and srv.roles == ["node", "panel"]
    creds = await rw_api.credentials(approved["id"], db, ADMIN)
    assert creds["username"] == "corgi-admin" and creds["password"] == secrets["panel_admin_password"]
    with pytest.raises(HTTPException):  # a server with installed components is not deleted silently
        await rw_api.delete_server(server["id"], db, ADMIN)

    staged = await rw_api.connect_shop(approved["id"], db, ADMIN, ADMIN)
    assert staged["change"]["status"] == "staged" and set(staged["change"]["keys"]) == {"remnawave_url", "remnawave_token"}

    # maintenance actions are plans over this installation
    host.log_secret = "db " + rw_jobs.load_secrets(row)["db_password"]
    for action in ("diagnose", "logs", "stop", "start", "restart", "update", "restore", "reinstall", "remove"):
        planned = await rw_api.action(approved["id"], rw_api.ActionIn(action=action), db, ADMIN)
        kinds = [s["kind"] for s in planned["plan"]["steps"]]
        assert set(kinds) <= set(rw_steps.STEP_KINDS), action
        await rw_api.approve(planned["id"], rw_api.ApproveIn(plan_sha256=planned["plan_sha256"]), db, ADMIN)
        await run_all(db)
        done = await rw_api.get_installation(planned["id"], db, ADMIN)
        assert done["status"] == "succeeded", (action, done)
        if action == "update":
            assert kinds[:2] == ["backup_panel", "fetch_panel_backup"] and host.backups == 1
            copies = list((tmp_path / "panel-copies").glob("panel-*.dump.enc"))
            assert len(copies) == 1 and b"PGDMP" not in copies[0].read_bytes()  # encrypted at rest
            assert rw_steps.unseal(copies[0].read_bytes()).startswith(b"PGDMP")
        if action in ("logs", "stop", "start", "restart"):  # v28.77.0: service control never writes files
            assert "compose_ctl" in kinds and "write_files" not in kinds and "compose_down" not in kinds
            ops = {s["params"]["op"] for s in planned["plan"]["steps"] if s["kind"] == "compose_ctl"}
            assert ops == {action}
            assert (action == "stop") == (not host.up)
        if action == "logs":
            text = "\n".join(s["log"] or "" for s in done["steps"])
            assert "remnawave | started" in text and "JWT_AUTH_SECRET=***" in text and "leaked-secret-value" not in text
            assert rw_jobs.load_secrets(row)["db_password"] not in text
        if action == "remove":
            assert "compose_down" in kinds and "write_files" not in kinds
    assert not host.up
    srv = await db.get(RemnawaveServer, server["id"])
    await db.refresh(srv)
    assert srv.status == "removed" and srv.roles == []
    assert await rw_api.delete_server(server["id"], db, ADMIN) == {"deleted": True}


@pytest.mark.asyncio
async def test_failed_step_rolls_back(database, fleet, monkeypatch):
    db = database
    monkeypatch.setattr(settings, "remnawave_url", "https://panel.shop.example")
    monkeypatch.setattr(settings, "remnawave_token", "shop-token")
    panel_calls = []

    class Client:
        async def _request(self, method, path, **kw):
            panel_calls.append((method, path))
            if path == "/api/keygen":
                return {"pubKey": "k"}
            if path == "/api/config-profiles":
                return {"configProfiles": [{"uuid": "p", "inbounds": [{"uuid": "i"}]}]}
            if path == "/api/nodes" and method == "POST":
                return {"uuid": "n-1"}
            if path == "/api/nodes/n-1" and method == "GET":
                return {"isConnected": False}
            return {}
    import app.remnawave as remnawave
    monkeypatch.setattr(remnawave, "RemnawaveClient", Client)
    monkeypatch.setattr(rw_steps.socket, "gethostbyname", lambda host: "203.0.113.1")
    server = await add_server(db, fleet, "node-1", "198.51.100.20", purpose=["node"])
    await rw_api.check_server(server["id"], db, ADMIN)
    approved = await plan_and_approve(db, rw_plan.PlanIn(mode="node", node_server_ids=[server["id"]]))
    await run_all(db)
    got = await rw_api.get_installation(approved["id"], db, ADMIN)
    assert got["status"] == "failed" and "не подключилась" in got["error"]
    statuses = {s["kind"]: s["status"] for s in got["steps"]}
    assert statuses["verify"] == "failed" and statuses["register_node"] == "rolled_back"
    assert statuses["compose_up"] == "rolled_back" and statuses["write_files"] == "rolled_back"
    host = fleet["198.51.100.20"]
    assert ("DELETE", "/api/nodes/n-1") in panel_calls and not host.up and ("/opt/remnanode", "docker-compose.yml") not in host.files
    assert host.rules == [("203.0.113.1", "2222", "add"), ("203.0.113.1", "2222", "delete")]


@pytest.mark.asyncio
async def test_preflight_failure_stops_before_any_change(database, fleet):
    db = database
    server = await add_server(db, fleet, "panel-1", "198.51.100.10", extra_lines=["listen=443 nginx", "service=nginx"])
    checked = await rw_api.check_server(server["id"], db, ADMIN)
    assert checked["status"] == "check_failed"
    approved = await plan_and_approve(db, rw_plan.PlanIn(mode="panel", panel_server_id=server["id"], panel_domain="panel.example.com",
                                                         tls="internal"))
    await run_all(db)
    got = await rw_api.get_installation(approved["id"], db, ADMIN)
    assert got["status"] == "failed" and "443" in got["error"]
    assert [c[0] for c in fleet["198.51.100.10"].calls if c[0] != "preflight"] == []
    assert {s["status"] for s in got["steps"][1:]} == {"skipped"}


@pytest.mark.asyncio
async def test_cancel_and_stale_runs(database, fleet):
    db = database
    server = await add_server(db, fleet, "node-1", "198.51.100.10")
    await rw_api.check_server(server["id"], db, ADMIN)
    payload = rw_plan.PlanIn(mode="panel", panel_server_id=server["id"], panel_domain="panel.example.com", tls="internal")
    planned = await rw_api.plan_installation(payload, db, ADMIN)
    assert (await rw_api.cancel(planned["id"], db, ADMIN))["status"] == "cancelled"
    with pytest.raises(HTTPException):
        await rw_api.approve(planned["id"], rw_api.ApproveIn(plan_sha256=planned["plan_sha256"]), db, ADMIN)
    first = await plan_and_approve(db, payload)
    second = await rw_api.plan_installation(payload, db, ADMIN)
    with pytest.raises(HTTPException) as err:  # one server, one installation at a time
        await rw_api.approve(second["id"], rw_api.ApproveIn(plan_sha256=second["plan_sha256"]), db, ADMIN)
    assert err.value.status_code == 409
    row = await db.get(RemnawaveInstallation, first["id"])
    row.status = "running"; row.heartbeat_at = datetime.utcnow() - timedelta(minutes=6)
    await db.commit()
    assert await rw_jobs.recover_stale(db.bind) == 1
    await db.refresh(row)
    assert row.status == "failed" and "Прервано" in row.error
    third = await plan_and_approve(db, payload)
    row = await db.get(RemnawaveInstallation, third["id"])
    row.cancel_requested = True
    await db.commit()
    await run_all(db)
    got = await rw_api.get_installation(third["id"], db, ADMIN)
    assert got["status"] == "cancelled" and {s["status"] for s in got["steps"]} == {"skipped"}


def test_remote_masks_secrets_and_quotes_arguments(monkeypatch):
    from app import rw_remote
    assert rw_remote.tail("token=abcdef123 ok", ["abcdef123"]) == "token=*** ok"
    sent = {}

    class Chan:
        def __init__(self):
            self.channel = self

        def write(self, data):
            sent["stdin"] = data

        def shutdown_write(self):
            pass

        def read(self):
            return b""

        def recv_exit_status(self):
            return 0

    class Client:
        def exec_command(self, command, timeout):
            sent["command"] = command
            return Chan(), Chan(), Chan()
    remote = rw_remote.Remote.__new__(rw_remote.Remote)
    remote.user, remote.client = "deploy", Client()
    remote.run("echo \"$1\"", "x'; reboot #")
    assert sent["command"].startswith("sudo -n bash -c ") and "'x'\"'\"'; reboot #'" in sent["command"]
