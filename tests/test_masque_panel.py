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


def sub(id=1, plan=1, days=10, life="active", user=7):
    return SimpleNamespace(id=id, plan_id=plan, user_id=user, name="Подписка", expires_at=NOW + timedelta(days=days), lifecycle_status=life)


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
    assert config["api"]["listen"] == f"127.0.0.1:{rw_masque.API_PORT}" and "HandlerService" in config["api"]["services"]
    assert config["policy"]["levels"]["0"] == {"statsUserUplink": True, "statsUserDownlink": True}
    freedom = config["outbounds"][0]
    assert freedom["protocol"] == "freedom" and "settings" not in freedom                   # Xray's default final rules stay
    with pytest.raises(ValueError):
        rw_masque.server_config("node.example.com", [{"email": "bad login", "pass": "p"}], prefix)


def test_haproxy_sends_only_the_secret_path_to_xray():
    prefix = rw_masque.new_prefix("secret", "server-1")
    text = rw_masque.haproxy_cfg("node.example.com", 2087, prefix)
    assert f"use_backend tunnel if {{ req.hdr(upgrade) -i connect-ip }} {{ path_beg /{prefix}/ }}" in text    # only a tunnel request
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
    assert names == ["config.json", "haproxy.cfg", "docker-compose.yml", "400.http", "users"]
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
        calls.append((server_id, action, args[0], args[1], len(stdin)))
        return SimpleNamespace(code=0, out="masque=sync users=1 added=1 removed=0", err="")

    monkeypatch.setattr(panel, "_ssh", ssh)
    stored[panel.STATE_KEY] = {**ON, "nodes": {"1": {"server_id": 1, "name": "de-1", "domain": "de.example.com", "port": 2087, "state": "on"}}}
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
    stored[panel.STATE_KEY] = {**ON, "nodes": {"1": {"server_id": 1, "name": "de-1", "domain": "de.example.com", "port": 2087, "state": "on"}}}
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
    assert "strict-sni" not in off and "ssl-default-bind" not in off and "stick-table" not in off and "gpc1" not in off
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
        assert "stick-table" not in tar.extractfile("haproxy.cfg").read().decode()
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
