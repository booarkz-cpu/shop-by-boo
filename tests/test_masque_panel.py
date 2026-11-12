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
    assert f"use_backend tunnel if {{ path_beg /{prefix}/ }}" in text and "default_backend site" in text
    assert "bind :2087 ssl crt /tls/site.pem alpn h2,http/1.1" in text and "#V6#\tbind :::2087 v6only" in text
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
    assert names == ["config.json", "haproxy.cfg", "docker-compose.yml", "users"]
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
