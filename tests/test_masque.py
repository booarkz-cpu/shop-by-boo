"""MASQUE: the version a node needs, the inbound of the official schema, port conflicts, and no pretended switch."""
import pytest

from app import masque, rw_plan, rw_steps

CERT, KEY = "/var/lib/corgi-hysteria/cert.pem", "/var/lib/corgi-hysteria/key.pem"
USERS = [{"email": "u1@shop", "pass": "p1"}, {"email": "u2@shop", "pass": "p2", "level": 1}]


def test_version_is_read_from_what_a_node_reports():
    assert masque.parse_version("Xray 26.11.9 (Xray, Penetrates Everything.) 676eaf6 (go1.27.0 linux/amd64)") == (26, 11, 9)
    assert masque.parse_version("v26.10.21") == (26, 10, 21)
    assert masque.parse_version("") is None and masque.parse_version(None) is None and masque.parse_version("rw-core dev") is None
    assert masque.parse_version("1.8") is None                           # two parts are not a core version


@pytest.mark.parametrize(("version", "state"), [("26.10.21", "ready"), ("26.11.9", "ready"), ("27.1.1", "ready"), ("26.10.20", "old"),
                                               ("26.9.30", "old"), ("1.8.24", "old"), (None, "unknown"), ("unknown", "unknown")])
def test_core_state(version, state):
    assert masque.core_state(version) == state


def test_required_version_is_not_older_than_the_first_tag_with_masque():
    assert masque.FIRST_TAG <= masque.REQUIRED and masque.REQUIRED >= (26, 10, 10)


def test_inbound_follows_the_official_schema():
    item = masque.inbound("node.example.com", CERT, KEY, USERS)
    assert item["protocol"] == "masque" and item["port"] == masque.DEFAULT_PORT
    assert item["settings"] == {"users": [{"email": "u1@shop", "pass": "p1", "level": 0}, {"email": "u2@shop", "pass": "p2", "level": 1}],
                                "address": ["10.77.0.1/24", "fd77::1/64"], "mtu": 1280}
    stream = item["streamSettings"]
    assert stream["method"] == "masque" and stream["security"] == "tls" and "realitySettings" not in stream
    assert stream["masqueSettings"] == {"path": "/.well-known/masque/ip/{target}/{ipproto}/"}   # the inbound uses only the path
    assert stream["tlsSettings"] == {"serverName": "node.example.com", "alpn": ["h3", "h2"],
                                     "certificates": [{"certificateFile": CERT, "keyFile": KEY}]}


@pytest.mark.parametrize(("kw", "text"), [
    ({"address": ["10.0.0.1/31"]}, "/30"), ({"address": ["fd00::1/127"]}, "/126"), ({"address": ["10.0.0.1/24", "10.1.0.1/24"]}, "одного"),
    ({"address": []}, "хотя бы один"), ({"address": ["nope"]}, "Неверный диапазон"), ({"mtu": 1279}, "MTU"), ({"mtu": 70000}, "MTU"),
    ({"port": 0}, "Порт"), ({"http": ["h1"]}, "HTTP"), ({"http": []}, "HTTP"), ({"path": "masque"}, "Путь"),
    ({"path": "/ip/{host}/"}, "Путь"), ({"users": [{"email": "a:b", "pass": "x"}]}, "двоеточие"),
    ({"users": [{"email": "a", "pass": ""}]}, "пароля"), ({"users": [{"email": "A", "pass": "x"}, {"email": "a", "pass": "y"}]}, "повторяется"),
])
def test_inbound_refuses_what_xray_would_refuse(kw, text):
    with pytest.raises(ValueError, match=text):
        masque.inbound("node.example.com", CERT, KEY, **kw)


def test_inbound_needs_a_domain_because_reality_is_not_supported():
    for bad in ("203.0.113.5", "localhost", ""):
        with pytest.raises(ValueError, match="домен"):
            masque.inbound(bad, CERT, KEY)


def test_query_form_of_the_path_is_accepted():
    assert masque.inbound("node.example.com", CERT, KEY, path="/masque{?target,ipproto}")["streamSettings"]["masqueSettings"]["path"] == "/masque{?target,ipproto}"


def test_outbound_matches_the_inbound():
    server = masque.inbound("node.example.com", CERT, KEY, USERS)
    client = masque.outbound("node.example.com", "u1@shop", "p1", http="h2")
    assert client["settings"] == {"address": "node.example.com", "port": server["port"]}
    assert client["streamSettings"]["masqueSettings"]["path"] == server["streamSettings"]["masqueSettings"]["path"]
    assert client["streamSettings"]["tlsSettings"]["alpn"] == ["h2"] and "mux" not in client
    for bad in ({"http": "h1"}, {"user": "a:b"}, {"password": ""}):
        with pytest.raises(ValueError):
            masque.outbound(**{"domain": "node.example.com", "user": "u", "password": "p", **bad})


def _profile():
    base = {"tag": "VLESS_TCP_REALITY", "port": 443, "protocol": "vless", "streamSettings": {"network": "tcp", "security": "reality", "realitySettings": {}}}
    return [base, *rw_steps.transport_inbounds(base, "node.example.com", list(rw_plan.TRANSPORTS))]


def test_default_port_is_free_next_to_every_transport_the_shop_installs():
    assert masque.port_conflicts(_profile()) == []
    assert masque.DEFAULT_PORT not in rw_plan.MTPROTO_TAKEN


def test_port_443_is_taken_by_reality_on_tcp_and_hysteria_on_udp():
    assert masque.port_conflicts(_profile(), 443) == ["TCP 443 занят inbound «VLESS_TCP_REALITY»", "UDP 443 занят inbound «HYSTERIA2»"]
    assert masque.port_conflicts(_profile(), 443, ["h2"]) == ["TCP 443 занят inbound «VLESS_TCP_REALITY»"]
    assert masque.port_conflicts(_profile(), 8443, ["h3"]) == []          # gRPC holds TCP 8443, HTTP/3 needs UDP
    assert masque.port_conflicts(_profile(), 8443, ["h2"]) == ["TCP 8443 занят inbound «VLESS_GRPC_REALITY»"]


def test_own_inbound_is_not_a_conflict_but_another_masque_is():
    own = masque.inbound("node.example.com", CERT, KEY)
    assert masque.port_conflicts([own]) == []
    other = {**own, "tag": "MASQUE_2", "streamSettings": {**own["streamSettings"], "tlsSettings": {"alpn": ["h3"]}}}
    assert masque.port_conflicts([other]) == [f"UDP {masque.DEFAULT_PORT} занят inbound «MASQUE_2»"]
    assert masque.port_conflicts([{"tag": "x", "port": "bad"}, "junk", {"tag": "y"}]) == []


def test_readiness_lists_nodes_profiles_and_notes():
    nodes = [{"uuid": "n1", "name": "de-1", "versions": {"xray": "26.11.9"}}, {"uuid": "n2", "name": "cz-1", "xrayVersion": "26.7.28"},
             {"uuid": "n3"}]
    out = masque.readiness(nodes, [{"uuid": "p1", "name": "Основной", "config": {"inbounds": _profile()}}, {"uuid": "p2"}], 443)
    assert [(n["name"], n["xray"], n["state"]) for n in out["nodes"]] == [("de-1", "26.11.9", "ready"), ("cz-1", "26.7.28", "old"), ("—", None, "unknown")]
    assert out["nodes_ready"] == 1 and out["required"] == "v26.10.21" and out["first_tag"] == "v26.9.30"
    assert len(out["profiles"][0]["conflicts"]) == 2 and out["profiles"][1]["conflicts"] == []
    assert {b["key"] for b in out["blockers"]} == {"panel", "link", "reality"}
    assert out["example"]["port"] == 443 and out["example"]["settings"]["users"] == []


@pytest.mark.asyncio
async def test_page_reads_the_panel_and_changes_nothing(monkeypatch):
    from app import rw_extensions
    calls = []

    async def panel(method, path, **kw):
        calls.append((method, path))
        return {"response": [{"uuid": "n1", "name": "de-1", "versions": {"xray": "26.11.9"}}]} if path == "/api/nodes" else {"response": {"configProfiles": []}}

    monkeypatch.setattr(rw_extensions, "_panel", panel)
    out = await masque.state(port=2087, admin=None)
    assert calls == [("GET", "/api/nodes"), ("GET", "/api/config-profiles")]
    assert out["nodes_ready"] == 1 and out["profiles"] == []
