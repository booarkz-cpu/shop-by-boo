"""The shop's own MASQUE panel: who gets access, the files of a node, the subscription and its link."""
import gzip
import io
import json
import tarfile
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app import masque, masque_panel as panel, rw_masque

NOW = datetime(2026, 11, 12, 12, 0, 0)
ON = {"enabled": True, "plan_ids": [], "port": 2087, "nodes": {}}


def sub(id=1, plan=1, days=10, life="active", user=7, devices=None, gb=None):
    return SimpleNamespace(id=id, plan_id=plan, user_id=user, name="Подписка", expires_at=NOW + timedelta(days=days), lifecycle_status=life,
                           device_limit_snapshot=devices, traffic_limit_gb_snapshot=gb, remnawave_uuid=None)


# ---------------------------------------------------------------- who has access

@pytest.mark.parametrize(("s", "state", "expected"), [
    (sub(), ON, True),
    (sub(life="grace"), ON, True),
    (sub(life="cancel_scheduled"), ON, True),
    (sub(life="frozen"), ON, False),
    (sub(life="expired"), ON, False),
    (sub(days=-1), ON, False),
    (sub(), {**ON, "enabled": False}, False),
    (sub(plan=2), {**ON, "plan_ids": [1]}, False),
    (sub(plan=1), {**ON, "plan_ids": [1]}, True),
])
def test_eligibility(s, state, expected):
    assert panel.eligible(s, state, NOW) is expected


def test_subscription_without_an_end_date_has_no_access():
    s = sub()
    s.expires_at = None
    assert panel.eligible(s, ON, NOW) is False


# ---------------------------------------------------------------- credentials and the link

def test_credentials_are_stable_distinct_and_do_not_reveal_the_password():
    a, b = rw_masque.credentials("secret", "1"), rw_masque.credentials("secret", "2")
    assert a == rw_masque.credentials("secret", "1") and a != b and a[0] != b[0]
    assert rw_masque.credentials("other", "1")[1] != a[1]              # another shop secret, another password
    assert rw_masque.credentials("other", "1")[0] == a[0]              # the login does not depend on the secret
    assert rw_masque.EMAIL.match(a[0]) and ":" not in a[0] and len(a[1]) == 32
    with pytest.raises(ValueError):
        rw_masque.credentials("", "1")


def test_link_token_round_trip_and_forgery():
    value = panel.token(42)
    assert panel.subscription_id(value) == 42
    assert panel.subscription_id("43." + value.split(".")[1]) is None      # a token of one subscription does not open another
    for bad in ("", "42", "42.", "42.zz", "x.y", value + "0", "-1." + value.split(".")[1]):
        assert panel.subscription_id(bad) is None


def test_users_hash_changes_with_the_list_and_the_address():
    one, two = panel.users_of([sub(1)]), panel.users_of([sub(1), sub(2)])
    assert panel.users_hash(one, "a.example.com", 2087) == panel.users_hash(list(reversed(one)), "a.example.com", 2087)
    assert len({panel.users_hash(one, "a.example.com", 2087), panel.users_hash(two, "a.example.com", 2087),
                panel.users_hash(one, "b.example.com", 2087), panel.users_hash(one, "a.example.com", 2088)}) == 4


# ---------------------------------------------------------------- the files of a node

def test_server_config_keeps_xray_on_loopback_and_private_networks_closed():
    prefix = rw_masque.new_prefix("secret", "server-1")
    config = rw_masque.server_config("node.example.com", [{"email": "m1", "pass": "p"}], prefix)
    inbound = config["inbounds"][0]
    assert inbound["listen"] == "127.0.0.1" and inbound["port"] == rw_masque.INNER_PORT and inbound["tag"] == rw_masque.TAG
    assert inbound["streamSettings"]["tlsSettings"]["alpn"] == ["h2"]                       # HTTP/3 cannot be hidden behind the site
    assert inbound["streamSettings"]["masqueSettings"]["path"] == f"/{prefix}/{{target}}/{{ipproto}}/"
    assert inbound["settings"]["address"] == ["10.77.0.1/16"]                              # no IPv6 inside the tunnel
    assert config["api"]["listen"] == rw_masque.API_SOCK and "HandlerService" in config["api"]["services"]
    assert config["policy"]["levels"]["0"] == {"statsUserUplink": True, "statsUserDownlink": True}
    freedom = config["outbounds"][0]
    assert freedom["protocol"] == "freedom" and "settings" not in freedom                   # Xray's default final rules stay
    with pytest.raises(ValueError):
        rw_masque.server_config("node.example.com", [{"email": "bad login", "pass": "p"}], prefix)


def test_haproxy_sends_only_the_secret_path_to_xray():
    prefix = rw_masque.new_prefix("secret", "server-1")
    text = rw_masque.haproxy_cfg("node.example.com", 2087, prefix)
    assert "acl tunnel req.hdr(upgrade) -i connect-ip" in text and f"acl secret path_beg /{prefix}/" in text
    assert "use_backend tunnel if tunnel secret" in text                                   # only a tunnel request to the secret path
    assert "default_backend site" in text
    assert "bind :2087 ssl crt /tls/site.pem alpn h2,http/1.1 strict-sni" in text and "#V6#\tbind :::2087 v6only" in text
    assert f"server xray 127.0.0.1:{rw_masque.INNER_PORT} ssl verify none alpn h2 sni str(node.example.com)" in text
    assert "server site unix@/dev/shm/selfsteal.sock" in text and "send-proxy" in text      # the site sees the visitor's address
    for bad in (("node.example.com", 443, prefix), ("node.example.com", rw_masque.INNER_PORT, prefix), ("bad domain", 2087, prefix),
                ("node.example.com", 2087, "short")):
        with pytest.raises(ValueError):
            rw_masque.haproxy_cfg(*bad)


def test_images_are_pinned_and_compose_keeps_both_on_the_host_network():
    for image in (rw_masque.XRAY_IMAGE, rw_masque.HAPROXY_IMAGE):
        assert "@sha256:" in image and len(image.split("@sha256:")[1]) == 64
    text = rw_masque.compose()
    assert text.count("network_mode: host") == 2 and rw_masque.XRAY_IMAGE in text and rw_masque.HAPROXY_IMAGE in text
    assert "privileged" not in text and "cap_add" not in text


def test_bundle_is_reproducible_and_complete():
    prefix = rw_masque.new_prefix("secret", "server-1")
    users = [{"email": "m2", "pass": "b"}, {"email": "m1", "pass": "a"}]
    data = rw_masque.bundle("node.example.com", 2087, prefix, users)
    assert data == rw_masque.bundle("node.example.com", 2087, prefix, users)
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(data))) as tar:
        names = tar.getnames()
        config = json.load(tar.extractfile("config.json"))
        logins = tar.extractfile("users").read().decode()
    assert names == ["config.json", "haproxy.cfg", "docker-compose.yml", "400.http", "limits.map", "users"]
    assert logins == "m2\nm1\n" and [u["email"] for u in config["inbounds"][0]["settings"]["users"]] == ["m2", "m1"]


def test_node_script_validates_its_arguments_and_knows_every_action():
    script = rw_masque.NODE
    assert "__DIR__" not in script and "__API__" not in script and "__TAG__" not in script
    for needle in ("on|sync)", "status)", "off)", "bad domain", "bad port", "bad archive", "noselfsteal", "nocert", "not installed",
                   "api rmu", "adu -s", "corgi-masque-cert.timer"):
        assert needle in script
    branch = script.split('if [ "$action" = sync ]; then')[1].split("exit 0")[0]
    assert "restart" not in branch and "compose" not in branch                             # a sync never restarts Xray


def test_result_line_is_parsed():
    assert rw_masque.parse_result("noise\nmasque=on users=3 port=2087 cert=Nov_13_2026") == {"masque": "on", "users": "3", "port": "2087", "cert": "Nov_13_2026"}
    assert rw_masque.parse_result("") == {}
    parsed = panel.parse_status("traffic m1 uplink 10\ntraffic m1 downlink 250\ntraffic bad x 1\nmasque=on users=1 port=2087 cert=x")
    assert parsed["traffic"] == {"m1": {"uplink": 10, "downlink": 250}} and parsed["summary"]["users"] == "1"


# ---------------------------------------------------------------- the subscription

def test_subscription_holds_one_config_per_working_node(monkeypatch):
    state = {**ON, "nodes": {"1": {"server_id": 1, "name": "de-1", "domain": "de.example.com", "port": 2087, "state": "on"},
                             "2": {"server_id": 2, "name": "cz-1", "domain": "cz.example.com", "port": 2090, "state": "on"},
                             "3": {"server_id": 3, "name": "nl-1", "domain": "nl.example.com", "port": 2087, "state": "failed"}}}
    configs = panel.configs_for(state, sub(5))
    assert [c["remarks"] for c in configs] == ["MASQUE · cz-1", "MASQUE · de-1"]
    login, password = rw_masque.credentials(panel.settings.app_secret, "5")
    proxy = configs[1]["outbounds"][0]
    assert proxy["protocol"] == "masque" and proxy["settings"] == {"address": "de.example.com", "port": 2087}
    assert proxy["streamSettings"]["masqueSettings"] == {"path": rw_masque.path(panel.prefix_of(1)), "user": login, "pass": password}
    assert proxy["streamSettings"]["tlsSettings"] == {"serverName": "de.example.com", "alpn": ["h2"]}
    assert configs[0]["outbounds"][0]["streamSettings"]["masqueSettings"]["path"] != proxy["streamSettings"]["masqueSettings"]["path"]
    assert configs[0]["dns"]["queryStrategy"] == "UseIPv4"


def test_client_and_server_agree_on_the_path():
    prefix = rw_masque.new_prefix("secret", "server-9")
    server = rw_masque.server_config("node.example.com", [{"email": "m1", "pass": "p"}], prefix)["inbounds"][0]
    client = rw_masque.client_config("node.example.com", 2087, prefix, "m1", "p", "x")["outbounds"][0]
    assert client["streamSettings"]["masqueSettings"]["path"] == server["streamSettings"]["masqueSettings"]["path"]
    assert masque.port_conflicts([server], 2087, ["h2"]) == []          # Xray's loopback port is another one


# ---------------------------------------------------------------- keeping nodes in step

def test_due_only_when_the_list_changed_or_the_node_was_not_checked_for_long():
    node = {"state": "on", "hash": "abc", "checked_at": "2026-11-12T11:50:00Z"}
    assert panel.due(node, "abc", NOW) is False
    assert panel.due(node, "other", NOW) is True
    assert panel.due({**node, "checked_at": "2026-11-12T11:29:00Z"}, "abc", NOW) is True
    assert panel.due({**node, "checked_at": None}, "abc", NOW) is True
    assert panel.due({**node, "state": "failed"}, "other", NOW) is False


class Db:
    def __init__(self, subs):
        self.subs, self.commits = subs, 0

    async def execute(self, _):
        subs = self.subs
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: subs))

    async def commit(self):
        self.commits += 1


@pytest.fixture
def stored(monkeypatch):
    from app import node_health
    box = {}

    async def load(db, key, default):
        return {**default, **json.loads(json.dumps(box.get(key, {})))}

    async def save(db, key, value):
        box[key] = json.loads(json.dumps(value))

    monkeypatch.setattr(node_health, "_load", load)
    monkeypatch.setattr(node_health, "_save", save)
    return box


@pytest.mark.asyncio
async def test_tick_contacts_a_node_only_when_its_list_changed(stored, monkeypatch):
    calls = []

    async def ssh(db, server_id, action, *args, stdin=None):
        if action == "traffic":
            return SimpleNamespace(code=0, out="masque=traffic", err="")
        calls.append((server_id, action, args[0], args[1], len(stdin)))
        return SimpleNamespace(code=0, out="masque=sync users=1 added=1 removed=0", err="")

    monkeypatch.setattr(panel, "_ssh", ssh)
    stored[panel.STATE_KEY] = {**ON, "nodes": {"1": {"server_id": 1, "name": "de-1", "domain": "de.example.com", "port": 2087, "state": "on", "stack": panel.STACK}}}
    db = Db([sub(1, days=5), sub(2, life="frozen")])
    now = datetime.now(panel.UTC)
    db.subs = [sub(1), sub(2, life="frozen")]
    for s in db.subs:
        s.expires_at = panel._naive(now) + timedelta(days=5)

    assert await panel.tick(db, now) == 1 and calls[0][:4] == (1, "sync", "de.example.com", "2087")
    node = stored[panel.STATE_KEY]["nodes"]["1"]
    assert node["users"] == 1 and node["error"] is None and node["hash"]
    assert await panel.tick(db, now) == 0 and len(calls) == 1                      # nothing changed: no SSH

    db.subs[1].lifecycle_status = "active"                                          # a second subscription became live
    assert await panel.tick(db, now) == 1 and stored[panel.STATE_KEY]["nodes"]["1"]["users"] == 2

    stored[panel.STATE_KEY]["enabled"] = False                                      # switched off: everyone is removed
    assert await panel.tick(db, now) == 1 and stored[panel.STATE_KEY]["nodes"]["1"]["users"] == 0


@pytest.mark.asyncio
async def test_failed_sync_is_remembered_and_retried(stored, monkeypatch):
    async def ssh(db, server_id, action, *args, stdin=None):
        return SimpleNamespace(code=8, out="not installed", err="")

    monkeypatch.setattr(panel, "_ssh", ssh)
    stored[panel.STATE_KEY] = {**ON, "nodes": {"1": {"server_id": 1, "name": "de-1", "domain": "de.example.com", "port": 2087, "state": "on",
                                                     "stack": panel.STACK}}}
    db = Db([])
    assert await panel.tick(db) == 1
    node = stored[panel.STATE_KEY]["nodes"]["1"]
    assert node["error"] == "MASQUE на этой ноде не установлен" and "hash" not in node
    assert await panel.tick(db) == 1                                                # no hash yet: the next pass tries again


@pytest.mark.asyncio
async def test_tick_does_nothing_without_nodes(stored):
    assert await panel.tick(Db([sub()])) == 0


# ---------------------------------------------------------------- reissuing a link

def test_reissue_changes_the_link_the_login_and_the_password():
    before, after = {"epochs": {}}, {"epochs": {"42": 1}}
    old, new = panel.token(42, before), panel.token(42, after)
    assert old != new and old == panel.token(42)                      # a link issued before this release keeps working
    assert panel.subscription_id(old, before) == 42 and panel.subscription_id(new, after) == 42
    assert panel.subscription_id(old, after) is None                  # the old link is dead after a reissue
    assert panel.creds(before, 42) != panel.creds(after, 42) and panel.creds(before, 42)[0] != panel.creds(after, 42)[0]
    assert panel.creds(after, 43) == panel.creds(before, 43)          # other subscriptions are untouched
    assert panel.users_of([sub(42)], after) != panel.users_of([sub(42)], before)


@pytest.mark.asyncio
async def test_reissue_pushes_the_new_login_to_every_node(stored, monkeypatch):
    sent = []

    async def ssh(db, server_id, action, *args, stdin=None):
        sent.append((server_id, action))
        return SimpleNamespace(code=0, out="masque=sync users=1 added=1 removed=1", err="")

    monkeypatch.setattr(panel, "_ssh", ssh)
    state = {**ON, "epochs": {}, "nodes": {"1": {"server_id": 1, "name": "de-1", "domain": "de.example.com", "port": 2087, "state": "on"},
                                           "2": {"server_id": 2, "name": "cz-1", "domain": "cz.example.com", "port": 2087, "state": "on"}}}
    live = sub(42)
    live.expires_at = panel._naive() + timedelta(days=3)
    old_hash = panel.users_hash(panel.users_of([live], state), "de.example.com", 2087)
    await panel._reissue(Db([live]), state, live)
    assert state["epochs"] == {"42": 1} and sent == [(1, "sync"), (2, "sync")]
    assert state["nodes"]["1"]["hash"] != old_hash and stored[panel.STATE_KEY]["epochs"] == {"42": 1}


# ---------------------------------------------------------------- protections against detection

def test_shield_defaults_and_validation():
    assert rw_masque.shield() == rw_masque.SHIELD_DEFAULT == rw_masque.shield({})
    assert rw_masque.shield({"strict_sni": 0, "ban_after": "40"}) == {**rw_masque.SHIELD_DEFAULT, "strict_sni": False, "ban_after": 40}
    for bad in ({"ban_after": 4}, {"ban_after": 501}, {"ban_minutes": 0}, {"ban_minutes": 1441}, {"ban_after": "many"}):
        with pytest.raises(ValueError):
            rw_masque.shield(bad)


def test_always_on_protections_do_not_depend_on_the_choice():
    prefix = rw_masque.new_prefix("secret", "server-1")
    off = rw_masque.haproxy_cfg("node.example.com", 2087, prefix, {"strict_sni": False, "tls_like_site": False, "probe_ban": False})
    for text in (off, rw_masque.haproxy_cfg("node.example.com", 2087, prefix)):
        assert "req.hdr(upgrade) -i connect-ip" in text                                   # a plain GET of the secret path goes to the site
        assert "errorfile 400 /errors/400.http" in text and text.count("/dev/null") == 5    # no HAProxy pages
        assert "http-request deny deny_status 400 if !{ req.hdr(host) -m found }" in text
    assert "strict-sni" not in off and "ssl-default-bind" not in off and "type ipv6" not in off and "gpc1" not in off
    assert rw_masque.ERROR_400.startswith("HTTP/1.1 400 Bad Request\r\n") and rw_masque.ERROR_400.endswith("\r\n\r\n400 Bad Request")
    assert "html" not in rw_masque.ERROR_400.lower()


def test_chosen_protections_appear_in_the_config():
    prefix = rw_masque.new_prefix("secret", "server-1")
    text = rw_masque.haproxy_cfg("node.example.com", 2087, prefix, {"ban_after": 40, "ban_minutes": 15})
    assert text.count("strict-sni") == 2                                                   # IPv4 and IPv6
    assert "ssl-default-bind-options ssl-min-ver TLSv1.2" in text and f"ssl-default-bind-curves {rw_masque.SITE_CURVES}" in text
    assert "stick-table type ipv6 size 100k expire 15m store gpc1" in text
    assert "http-response sc-inc-gpc1(0) if { status 401 }" in text                        # a wrong password
    assert f"http-request sc-inc-gpc1(0) if {{ req.hdr(upgrade) -i connect-ip }} !{{ path_beg /{prefix}/ }}" in text   # a tunnel to a wrong path
    assert "!{ sc0_get_gpc1 ge 40 }" in text
    assert "deny" not in text.split("frontend public")[1].split("use_backend")[0].replace("deny deny_status 400 if !{ req.hdr(host)", "")   # a blocked address is not refused: it gets the site


def test_bundle_carries_the_chosen_protections():
    prefix = rw_masque.new_prefix("secret", "server-1")
    a = rw_masque.bundle("node.example.com", 2087, prefix, [], None)
    b = rw_masque.bundle("node.example.com", 2087, prefix, [], {"probe_ban": False})
    assert a != b
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(b))) as tar:
        assert "type ipv6" not in tar.extractfile("haproxy.cfg").read().decode()
        assert tar.extractfile("400.http").read().decode() == rw_masque.ERROR_400


def test_outside_comparison_names_every_difference():
    site = {"status": 200, "body": "aa", "headers": {"content-type": "text/html", "strict-transport-security": "max-age=1", "date": "x", "alt-svc": "h3"}}
    assert panel.compare(site, {**site, "headers": {**site["headers"], "date": "y"}}) == []            # the time differs by nature
    assert panel.compare(site, {"status": 200, "body": "aa", "headers": {"content-type": "text/html", "strict-transport-security": "max-age=1"}}) == []
    other = {"status": 503, "body": "bb", "headers": {"content-type": "text/plain", "server": "haproxy"}}
    assert panel.compare(site, other) == ["код ответа 503 вместо 200", "другое содержимое страницы", "заголовок content-type: другое значение",
                                          "заголовок server: лишний", "заголовок strict-transport-security: отсутствует"]


@pytest.mark.asyncio
async def test_probe_compares_three_requests_and_reports_an_unreachable_port(stored, monkeypatch):
    import httpx
    stored[panel.STATE_KEY] = {**ON, "nodes": {"1": {"server_id": 1, "name": "de-1", "domain": "de.example.com", "port": 2087, "state": "on"}}}
    seen = []

    async def fetch(url):
        seen.append(url)
        if ":2087" in url and url.endswith("/"):
            return {"status": 200 if url.endswith(":2087/") else 404, "body": "home" if url.endswith(":2087/") else "nf", "headers": {}}
        if ":2087" in url:
            raise httpx.ConnectError("closed")
        return {"status": 200 if url.endswith(".com/") else 404, "body": "home" if url.endswith(".com/") else "nf", "headers": {}}

    monkeypatch.setattr(panel, "_fetch", fetch)
    out = await panel.probe(1, db=Db([]), admin=None)
    assert [c["same"] for c in out["checks"]] == [True, False, True] and out["same"] is False
    assert out["checks"][1]["differences"] == ["нет ответа: ConnectError"]
    assert seen[4].startswith("https://de.example.com/") and seen[5] == f"https://de.example.com:2087/{panel.prefix_of(1)}/1/2/"
    assert len(out["limits"]) == 3
    with pytest.raises(panel.HTTPException):
        await panel.probe(9, db=Db([]), admin=None)


# ---------------------------------------------------------------- tunnels as in the plan (owner's decision 2)

def test_tunnel_limit_follows_the_plans_device_limit():
    users = panel.users_of([sub(1, devices=3), sub(2)], ON)
    assert [u["limit"] for u in users] == [3, 0]
    assert rw_masque.limits_map(users) == f"{users[0]['email']} 3\n"                 # no line: no limit
    assert panel.users_hash(users, "a.example.com", 2087) != panel.users_hash(panel.users_of([sub(1, devices=2), sub(2)], ON), "a.example.com", 2087)
    text = rw_masque.haproxy_cfg("node.example.com", 2087, rw_masque.new_prefix("s", "server-1"))
    assert "http-request track-sc1 http_auth_user table tunnels if tunnel secret" in text
    assert f"map_str_int({rw_masque.LIMITS_MAP},0)" in text and "use_backend site if tunnel secret limited too_many" in text
    assert text.index("use_backend site if tunnel secret limited too_many") < text.index("use_backend tunnel if tunnel secret")
    assert f"stats socket {rw_masque.HAPROXY_SOCK} mode 600 level admin" in text


def test_xray_api_is_a_unix_socket_not_a_port():
    config = rw_masque.server_config("node.example.com", [], rw_masque.new_prefix("s", "server-1"))
    assert config["api"]["listen"] == rw_masque.API_SOCK and config["api"]["listen"].startswith("/")
    assert str(rw_masque.API_PORT) not in rw_masque.NODE and "unix://" + rw_masque.API_SOCK in rw_masque.NODE
    assert "traffic)" in rw_masque.NODE and "-reset" in rw_masque.NODE and "limits_apply" in rw_masque.NODE


# ---------------------------------------------------------------- traffic and the plan's limit (owner's decision 1)

def test_counter_adds_up_and_starts_anew_each_month_without_the_panel():
    a = panel.add_traffic(None, 100, datetime(2026, 11, 12))
    b = panel.add_traffic(a, 50, datetime(2026, 11, 30))
    assert b["bytes"] == 150 and b["since"] == a["since"]
    c = panel.add_traffic(b, 7, datetime(2026, 12, 1))
    assert c["bytes"] == 7 and c["since"].startswith("2026-12-01")
    assert panel.add_traffic(c, -5, datetime(2026, 12, 2))["bytes"] == 7             # a negative delta is ignored


def test_limit_counts_masque_together_with_the_panel():
    entry = {"bytes": 3 * panel.GB, "since": "2026-11-01T00:00:00Z"}
    ok = panel.judge(entry, 10 * panel.GB, {"userTraffic": {"usedTrafficBytes": 6 * panel.GB}}, NOW)
    assert ok["over"] is False and ok["panel_used"] == 6 * panel.GB and ok["limit"] == 10 * panel.GB
    assert panel.judge(entry, 10 * panel.GB, {"userTraffic": {"usedTrafficBytes": 7 * panel.GB}}, NOW)["over"] is True
    assert panel.judge(entry, 10 * panel.GB, {"usedTrafficBytes": 1, "trafficLimitBytes": 3 * panel.GB}, NOW)["over"] is True   # the panel's own limit wins
    assert panel.judge(entry, 2 * panel.GB, None, NOW)["over"] is True                 # the panel is silent: MASQUE alone
    assert panel.judge(entry, None, {"usedTrafficBytes": 10 ** 15}, NOW)["over"] is False   # no limit: never over


def test_a_new_period_in_the_panel_starts_the_masque_counter_anew():
    entry = {"bytes": 9 * panel.GB, "since": "2026-11-01T00:00:00Z", "over": True}
    out = panel.judge(entry, 10 * panel.GB, {"usedTrafficBytes": 0, "lastTrafficResetAt": "2026-11-10T00:00:00.000Z"}, NOW)
    assert out["bytes"] == 0 and out["over"] is False and out["since"].startswith("2026-11-10") and out["panel_reset"] is True
    again = panel.judge({**out, "bytes": 5}, 10 * panel.GB, {"usedTrafficBytes": 0, "lastTrafficResetAt": "2026-11-10T00:00:00.000Z"}, NOW)
    assert again["bytes"] == 5                                                           # the same reset is not applied twice
    assert panel.add_traffic(again, 1, datetime(2026, 12, 3))["bytes"] == 6               # the month rule yields to the panel's period


def test_used_up_limit_takes_masque_away_only_while_the_switch_is_on():
    s = sub(5, gb=10)
    assert panel.eligible(s, ON, NOW, {5}) is False
    assert panel.eligible(s, {**ON, "count_in_limit": False}, NOW, {5}) is True
    assert panel.eligible(s, ON, NOW, {6}) is True


@pytest.mark.asyncio
async def test_collect_adds_node_traffic_and_blocks_the_one_over_the_limit(stored, monkeypatch):
    now = panel._naive()
    live, free = sub(1, gb=1), sub(2)
    for s in (live, free):
        s.expires_at = now + timedelta(days=5)
    state = {**ON, "nodes": {"1": {"server_id": 1, "name": "de-1", "domain": "de.example.com", "port": 2087, "state": "on", "stack": panel.STACK},
                             "2": {"server_id": 2, "name": "old", "domain": "old.example.com", "port": 2087, "state": "on"}}}
    l1, l2 = panel.creds(state, 1)[0], panel.creds(state, 2)[0]
    asked = []

    async def ssh(db, server_id, action, *args, stdin=None):
        asked.append((server_id, action))
        return SimpleNamespace(code=0, err="", out=f"traffic {l1} uplink {panel.GB}\ntraffic {l1} downlink 5\ntraffic {l2} downlink 9\ntraffic ghost downlink 1\nmasque=traffic")

    monkeypatch.setattr(panel, "_ssh", ssh)
    db = Db([live, free])
    assert await panel.collect(db, state, now) is True
    assert asked == [(1, "traffic")]                                                    # a node of the old layout is not asked
    data = stored[panel.TRAFFIC_KEY]
    assert data["subs"]["1"]["bytes"] == panel.GB + 5 and data["subs"]["2"]["bytes"] == 9 and "ghost" not in str(data)
    assert data["over"] == [1] and data["subs"]["2"]["over"] is False                   # 1 GB plan, 1 GB moved; the other has no limit
    assert [s.id for s in await panel._live_subs(db, state, now)] == [2]
    assert [s.id for s in await panel._live_subs(db, {**state, "count_in_limit": False}, now)] == [1, 2]
    assert await panel.collect(db, state, now) is False and asked == [(1, "traffic")]   # not again within five minutes


@pytest.mark.asyncio
async def test_node_of_an_older_release_is_reinstalled_once(stored, monkeypatch):
    actions = []

    async def ssh(db, server_id, action, *args, stdin=None):
        actions.append(action)
        return SimpleNamespace(code=0, out="masque=on users=0 port=2087 cert=x", err="")

    monkeypatch.setattr(panel, "_ssh", ssh)
    stored[panel.STATE_KEY] = {**ON, "nodes": {"1": {"server_id": 1, "name": "de-1", "domain": "de.example.com", "port": 2087, "state": "on"}}}
    assert await panel.tick(Db([])) == 1 and actions == ["on"]
    assert stored[panel.STATE_KEY]["nodes"]["1"]["stack"] == panel.STACK
    await panel.tick(Db([]))
    assert "on" not in actions[1:]                                                       # afterwards only traffic and syncs


@pytest.mark.asyncio
async def test_customer_links_only_for_subscriptions_with_masque_on_a_working_node(stored):
    now = panel._naive()
    a, b, c = sub(1, user=7), sub(2, user=7, life="frozen"), sub(3, user=7, gb=1)
    for s in (a, b, c):
        s.expires_at = now + timedelta(days=5)
    stored[panel.STATE_KEY] = {**ON, "nodes": {"1": {"server_id": 1, "domain": "de.example.com", "port": 2087, "state": "on"}}}
    stored[panel.TRAFFIC_KEY] = {"subs": {"3": {"bytes": 5}}, "over": [3]}
    items, _ = await panel.customer_items(Db([a, b, c]), 7)
    # frozen: no link; a used-up limit: listed with the flag, so the cabinet can say why (the bot skips it)
    assert [(i["subscription_id"], i["over_limit"]) for i in items] == [(1, False), (3, True)]
    stored[panel.STATE_KEY]["count_in_limit"] = False
    items, _ = await panel.customer_items(Db([a, b, c]), 7)
    assert [(i["subscription_id"], i["over_limit"]) for i in items] == [(1, False), (3, False)] and items[1]["traffic_bytes"] == 5
    stored[panel.STATE_KEY]["nodes"]["1"]["state"] = "failed"
    assert (await panel.customer_items(Db([a, b, c]), 7))[0] == []                    # no working node: no link


def test_bot_has_the_masque_line_in_three_languages():
    from app.bot_texts import t
    for lang in ("ru", "en", "uk"):
        text = t(lang, "keys_masque", name="Lucy Max", url="https://x/api/masque/sub/1.a")
        assert "MASQUE · Lucy Max" in text and "<code>https://x/api/masque/sub/1.a</code>" in text


@pytest.mark.asyncio
async def test_subscription_link_is_rate_limited(monkeypatch):
    from app import main, runtime_security
    monkeypatch.setattr(main, "redis_client", None)                                     # the in-process fallback counter
    runtime_security._LOCAL.clear()
    calls = 0

    async def no_state(db):
        nonlocal calls
        calls += 1
        return {**ON}

    monkeypatch.setattr(panel, "_state", no_state)
    monkeypatch.setattr(panel, "SUB_LIMIT", 3)
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="198.51.100.7"), scope={})
    monkeypatch.setattr(main, "_client_ip", lambda req: req.client.host)
    for _ in range(3):
        with pytest.raises(panel.HTTPException) as err:
            await panel.subscription("999.0000", db=Db([]), request=request)
        assert err.value.status_code == 404                                              # a forged link: not found
    with pytest.raises(panel.HTTPException) as err:
        await panel.subscription("999.0000", db=Db([]), request=request)
    assert err.value.status_code == 429 and calls == 3                                   # the fourth never reaches the database


# ---------------------------------------------------------------- alerts

def test_certificate_date_of_the_node_script_is_read():
    assert panel.cert_until("Nov_13_17:28:00_2026_GMT") == datetime(2026, 11, 13, 17, 28)
    assert panel.cert_until("Feb__1_00:00:00_2027_GMT") == datetime(2027, 2, 1)          # openssl pads the day with a space
    assert panel.cert_until("") is None and panel.cert_until("garbage") is None
    assert panel.parse_status("traffic m1 uplink 5\ncert Feb_10_12:00:00_2027_GMT\nmasque=traffic")["cert"] == "Feb_10_12:00:00_2027_GMT"


def test_alerts_once_per_problem():
    now = datetime(2026, 11, 13, 12, 0)
    state = {"nodes": {
        "1": {"name": "de-1", "domain": "de.example.com", "state": "on", "error": "Нода не ответила", "failing_since": "2026-11-13T11:45:00Z"},
        "2": {"name": "cz-1", "domain": "cz.example.com", "state": "on", "error": "x", "failing_since": "2026-11-13T11:55:00Z"},
        "3": {"name": "nl-1", "domain": "nl.example.com", "state": "on", "cert_until": "Nov_20_00:00:00_2026_GMT"},
        "4": {"name": "fi-1", "domain": "fi.example.com", "state": "on", "cert_until": "Feb_10_00:00:00_2027_GMT"},
    }}
    first = panel.alerts(state, now)
    assert len(first) == 2
    assert "«de-1» не сверяется с 11:45 UTC: Нода не ответила" in first[0]                # 15 minutes: reported; cz-1 after 5: not yet
    assert "«nl-1» истекает через 6 дн. (20.11.2026)" in first[1]                         # fi-1 has three months left
    assert panel.alerts(state, now) == []                                                  # nothing is repeated
    state["nodes"]["3"]["cert_until"] = "Nov_21_00:00:00_2026_GMT"                         # a renewed but still short one: reported again
    assert len(panel.alerts(state, now)) == 1


@pytest.mark.asyncio
async def test_a_recovered_node_can_alert_again(stored, monkeypatch):
    replies = iter([SimpleNamespace(code=8, out="not installed", err=""), SimpleNamespace(code=0, out="masque=sync users=0", err="")])

    async def ssh(db, server_id, action, *args, stdin=None):
        return next(replies)

    monkeypatch.setattr(panel, "_ssh", ssh)
    node = {"server_id": 1, "name": "de-1", "domain": "de.example.com", "port": 2087, "state": "on", "failing_since": "2026-11-13T11:00:00Z",
            "alerted_failure": True}
    failed = await panel.sync_node(Db([]), node, [])
    assert failed["failing_since"] == "2026-11-13T11:00:00Z" and failed["alerted_failure"] is True   # the first failure time is kept
    ok = await panel.sync_node(Db([]), failed, [])
    assert "failing_since" not in ok and "alerted_failure" not in ok and ok["error"] is None


@pytest.mark.asyncio
async def test_tick_sends_the_alert(stored, monkeypatch):
    from app import rw_autoupdate
    sent = []

    async def notify(text):
        sent.append(text)

    async def ssh(db, server_id, action, *args, stdin=None):
        return SimpleNamespace(code=0, out="masque=traffic", err="")

    monkeypatch.setattr(rw_autoupdate, "_notify", notify)
    monkeypatch.setattr(panel, "_ssh", ssh)
    stored[panel.STATE_KEY] = {**ON, "nodes": {"1": {"server_id": 1, "name": "de-1", "domain": "de.example.com", "port": 2087, "state": "on",
                                                     "stack": panel.STACK, "error": "x", "failing_since": "2000-01-01T00:00:00Z",
                                                     "hash": panel.users_hash([], "de.example.com", 2087), "checked_at": "2999-01-01T00:00:00Z"}}}
    await panel.tick(Db([]))
    assert len(sent) == 1 and "«de-1» не сверяется" in sent[0] and stored[panel.STATE_KEY]["nodes"]["1"]["alerted_failure"] is True
    await panel.tick(Db([]))
    assert len(sent) == 1
