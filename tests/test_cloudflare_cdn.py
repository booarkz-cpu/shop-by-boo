"""v28.98.0 (stage 20, N7): Cloudflare CDN in front of the node's XHTTP and the subscription domain, switched on and off
from «Установка». A fake Cloudflare API keeps zones, DNS records and configuration rules in memory; the plan, the
steps, «undo» and the API of the wizard are checked against it."""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import cloudflare_cdn as cf
from app import rw_api, rw_plan, rw_steps

TOKEN = "t" * 40
NODE = {2: {"name": "n2", "host": "93.184.216.40"}, 3: {"name": "p3", "host": "93.184.216.41"}}


class FakeCloudflare:
    def __init__(self):
        self.zones = {"z1": "example.com"}
        self.records = {"r0": {"zone": "z1", "name": "sub.example.com", "content": "93.184.216.41", "proxied": False}}
        self.rules = {"z1": [{"description": "owner rule", "expression": "(http.host eq \"www.example.com\")", "action": "set_config",
                              "action_parameters": {"ssl": "strict"}, "enabled": True}]}
        self.ssl = "strict"
        self.calls = []
        self.n = 0

    async def __call__(self, method, path, token, body=None, params=None):
        self.calls.append((method, path, body))
        if token != TOKEN:
            raise cf.CloudflareError("Cloudflare: Invalid API Token")
        if path == "/user/tokens/verify":
            return {"success": True, "result": {"status": "active"}}
        if path == "/zones":
            return {"success": True, "result": [{"id": z, "name": n} for z, n in self.zones.items() if n == params["name"]]}
        parts = path.strip("/").split("/")
        zone = parts[1]
        if parts[2] == "dns_records":
            if method == "GET":
                return {"success": True, "result": [{"id": i, **r} for i, r in self.records.items()
                                                     if r["zone"] == zone and r["name"] == params["name"]]}
            if method == "POST":
                self.n += 1
                self.records[f"r{self.n}"] = {"zone": zone, "name": body["name"], "content": body["content"], "proxied": body["proxied"]}
                return {"success": True, "result": {}}
            if method == "PATCH":
                self.records[parts[3]]["proxied"] = body["proxied"]
                return {"success": True, "result": {}}
            if method == "DELETE":
                self.records.pop(parts[3])
                return {"success": True, "result": {}}
        if parts[2] == "rulesets":
            if method == "GET":
                return {"success": True, "result": {"rules": self.rules.get(zone, [])}}
            self.rules[zone] = body["rules"]
            return {"success": True, "result": {}}
        if parts[2] == "settings":
            return {"success": True, "result": {"value": self.ssl}}
        raise AssertionError(path)

    def named(self, name):
        return sorted((r["content"], r["proxied"]) for r in self.records.values() if r["name"] == name)


@pytest.fixture
def cloud(monkeypatch):
    fake = FakeCloudflare()
    monkeypatch.setattr(cf, "REQUEST", fake)
    return fake


def ctx(plan, **state):
    return rw_steps.Context(plan=plan, servers=NODE, secrets={"cloudflare_token": TOKEN}, state=dict(state))


def cdn_plan(**module):
    return rw_plan.PlanIn(mode="add_node", node_server_ids=[2], selfsteal_domain="steal.example.com", cdn_domain="cdn.example.com", acme_email="owner@example.com",
                          transports=["cdn"], module=rw_plan.ModuleRun(name="cdn", **module))


def test_the_plan_switches_the_transport_and_the_dns_in_the_right_order():
    on, title = rw_plan.module_steps(cdn_plan(cdn_nodes=True), NODE, {2: ["node"]})
    assert title == "Cloudflare CDN: включить"
    assert [s["kind"] for s in on] == ["node_module", "write_files", "compose_up", "node_transports", "cdn_dns", "verify"]
    assert on[4]["params"] == {"part": "nodes", "on": True, "domain": "cdn.example.com", "addresses": ["93.184.216.40"]}
    off, _ = rw_plan.module_steps(cdn_plan(enabled=False, cdn_nodes=True), NODE, {2: ["node"]})
    assert [s["kind"] for s in off][:2] == ["cdn_dns", "node_module"], "off: the CDN stops sending traffic before the inbound goes"
    with pytest.raises(ValueError, match="Выберите"):
        rw_plan.module_steps(cdn_plan(), NODE, {2: ["node"]})
    with pytest.raises(ValidationError):
        rw_plan.PlanIn(mode="add_node", node_server_ids=[2], transports=["cdn"])  # no CDN domain, no SelfSteal
    with pytest.raises(ValidationError):
        rw_plan.PlanIn(mode="add_node", node_server_ids=[2], selfsteal_domain="steal.example.com", cdn_domain="steal.example.com", transports=["cdn"], acme_email="o@example.com")


def test_the_cdn_inbound_and_host():
    base = {"tag": "VLESS_TCP_REALITY", "streamSettings": {"security": "reality", "realitySettings": {"privateKey": "k"}}}
    [inbound] = rw_steps.transport_inbounds(base, "steal.example.com", ["cdn"])
    assert (inbound["tag"], inbound["port"]) == ("VLESS_XHTTP_CDN", 2083)
    stream = inbound["streamSettings"]
    assert stream["network"] == "xhttp" and stream["security"] == "tls" and stream["xhttpSettings"]["path"] == "/cdn"
    assert "realitySettings" not in stream, "Cloudflare cannot carry REALITY"
    host = rw_steps.transport_host("cdn", "cdn.example.com", "prof", "inb", "cdn.example.com cdn")
    assert host["address"] == host["sni"] == host["host"] == "cdn.example.com" and host["port"] == 2083
    assert host["securityLayer"] == "TLS" and host["path"] == "/cdn"
    assert 2083 in rw_plan.MTPROTO_TAKEN


@pytest.mark.asyncio
async def test_nodes_behind_the_cdn_and_back(cloud):
    plan = cdn_plan(cdn_nodes=True)
    c = ctx(plan)
    st = {"server_id": None, "params": {"part": "nodes", "on": True, "domain": "cdn.example.com", "addresses": ["93.184.216.40"]}}
    await rw_steps.run_cdn_dns(c, st)
    assert cloud.named("cdn.example.com") == [("93.184.216.40", True)]
    rules = cloud.rules["z1"]
    assert rules[0]["description"] == "owner rule", "the owner's rules stay"
    assert rules[-1] == {"description": "corgi-cdn cdn.example.com", "expression": '(http.host eq "cdn.example.com")',
                         "action": "set_config", "action_parameters": {"ssl": "full"}, "enabled": True}
    assert c.state["cdn"]["nodes"] == {"domain": "cdn.example.com", "on": True}
    await rw_steps.undo_cdn_dns(c, st)  # a later step failed
    assert cloud.named("cdn.example.com") == [] and [r["description"] for r in cloud.rules["z1"]] == ["owner rule"]

    await rw_steps.run_cdn_dns(c, st)
    off = {"server_id": None, "params": {**st["params"], "on": False}}
    await rw_steps.run_cdn_dns(ctx(plan), off)
    assert cloud.named("cdn.example.com") == [] and [r["description"] for r in cloud.rules["z1"]] == ["owner rule"]


@pytest.mark.asyncio
async def test_subscription_domain_orange_and_grey_cloud(cloud):
    plan = rw_plan.PlanIn(mode="add_node", node_server_ids=[2], module=rw_plan.ModuleRun(name="cdn", cdn_subscription=True))
    c = ctx(plan)
    st = {"server_id": None, "params": {"part": "subscription", "on": True, "domain": "sub.example.com", "addresses": ["93.184.216.41"]}}
    await rw_steps.run_cdn_dns(c, st)
    assert cloud.named("sub.example.com") == [("93.184.216.41", True)]
    assert list(cloud.records) == ["r0"], "the existing record is switched, not replaced"
    cloud.ssl = "flexible"
    await rw_steps.run_cdn_dns(c, st)
    assert any("Full (strict)" in line for line in c.log)
    await rw_steps.run_cdn_dns(c, {"server_id": None, "params": {**st["params"], "on": False}})
    assert cloud.named("sub.example.com") == [("93.184.216.41", False)]


@pytest.mark.asyncio
async def test_errors_of_cloudflare_reach_the_step(cloud):
    c = ctx(cdn_plan(cdn_nodes=True))
    c.secrets["cloudflare_token"] = "w" * 40
    with pytest.raises(rw_steps.StepError, match="Invalid API Token"):
        await rw_steps.run_cdn_dns(c, {"server_id": None, "params": {"part": "nodes", "on": True, "domain": "cdn.example.com",
                                                                      "addresses": ["93.184.216.40"]}})
    c.secrets.clear()
    with pytest.raises(rw_steps.StepError, match="токена"):
        await rw_steps.run_cdn_dns(c, {"server_id": None, "params": {"part": "nodes", "on": True, "domain": "cdn.example.com",
                                                                      "addresses": ["93.184.216.40"]}})
    with pytest.raises(cf.CloudflareError, match="Зона"):
        await cf.zone_of(TOKEN, "cdn.other.org")
    with pytest.raises(cf.CloudflareError, match="IPv4"):
        await cf.apply_records(TOKEN, "cdn.example.com", ["2001:db8::1"], True)


@pytest.mark.asyncio
async def test_the_wizard_keeps_the_token_and_switches_parts(cloud):
    params = {"transports": ["xhttp"], "selfsteal_domain": "steal.example.com"}
    secrets: dict = {}
    run: dict = {}
    with pytest.raises(HTTPException, match="Токен"):
        await rw_api._cdn_params(rw_api.ModuleIn(name="cdn", cdn_nodes=True, cdn_domain="cdn.example.com", cloudflare_token="short"),
                                 params, secrets, run)
    with pytest.raises(HTTPException, match="Зона"):
        await rw_api._cdn_params(rw_api.ModuleIn(name="cdn", cdn_nodes=True, cdn_domain="cdn.other.org", cloudflare_token=TOKEN), params, secrets, run)
    await rw_api._cdn_params(rw_api.ModuleIn(name="cdn", cdn_nodes=True, cdn_subscription=True, cdn_domain="CDN.example.com", cloudflare_token=TOKEN),
                             params, secrets, run)
    assert secrets["cloudflare_token"] == TOKEN and params["cdn_domain"] == "cdn.example.com"
    assert params["transports"] == ["cdn", "xhttp"] and params["cdn_subscription"] is True
    # The transports module never drops «cdn» (only the CDN module switches it).
    await rw_api._module_params(rw_api.ModuleIn(name="transports", transports=["grpc"]), params, secrets)
    assert "cdn" in params["transports"] and "grpc" in params["transports"]
    off_run: dict = {}
    await rw_api._cdn_params(rw_api.ModuleIn(name="cdn", enabled=False), params, secrets, off_run)  # the saved token
    assert off_run == {"cdn_nodes": True, "cdn_subscription": True} and params["transports"] == ["grpc"]
    with pytest.raises(HTTPException):
        await rw_api._cdn_params(rw_api.ModuleIn(name="cdn", enabled=False), params, secrets, {})


def test_transports_script_opens_the_cdn_port():
    import subprocess
    script = rw_steps.TRANSPORTS_SH
    assert subprocess.run(["bash", "-n"], input=script, text=True).returncode == 0
    assert 'port 2083/tcp "$cdn"' in script and '[ "$cdn" = on ]' in script
