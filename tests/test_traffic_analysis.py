"""Traffic analysis on the node: signatures, the encrypted-BitTorrent heuristic, IPv4/IPv6 parsing,
nDPI CSV, attribution through the Xray log, real AF_PACKET capture, throughput, and the shop side."""
import importlib.util
import json
import os
import random
import socket
import struct
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app import platform_api, torrent_detection as torrent
from app.models import AbuseViolation, AppSetting, NodeAgent, Notification, TorrentDetection
from test_subscription_commerce import database

TOKEN = "dpi-agent-token-0123456789abcdef01"
DHT_PING = b"d1:ad2:id20:" + b"a" * 20 + b"e1:q4:ping1:t2:aa1:y1:qe"
UTP_SYN = bytes([0x41, 0x00]) + b"\x12\x34" + b"\x00" * 16
UDP_TRACKER = (0x41727101980).to_bytes(8, "big") + b"\x00\x00\x00\x00" + b"\x01\x02\x03\x04"
HANDSHAKE = b"\x13BitTorrent protocol" + b"\x00" * 8 + b"h" * 20 + b"p" * 20
TLS_HELLO = b"\x16\x03\x01\x02\x00\x01\x00\x01\xfc\x03\x03" + bytes(range(200))


def load_agent():
    spec = importlib.util.spec_from_file_location("node_agent_dpi", Path(__file__).resolve().parents[1] / "scripts/node-agent.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agent():
    return load_agent()


def noise(n, seed):
    return random.Random(seed).randbytes(n)


# ---------------------------------------------------------------- signatures

def test_signatures_and_false_positive_guards(agent):
    c = agent.classify_payload
    assert c("tcp", HANDSHAKE) == "bittorrent"
    assert c("tcp", b"GET /announce?info_hash=%12%34&peer_id=x HTTP/1.1\r\nHost: t\r\n\r\n") == "tracker"
    assert c("tcp", b"GET /scrape?info_hash=abc HTTP/1.1\r\n\r\n") == "tracker"
    assert c("udp", UDP_TRACKER) == "tracker"
    assert c("udp", DHT_PING) == "dht"
    assert c("udp", b"d1:rd2:id20:" + b"b" * 20 + b"e1:t2:aa1:y1:re") == "dht"
    assert c("udp", UTP_SYN) == "utp"
    # ordinary traffic stays unclassified
    assert c("tcp", TLS_HELLO) is None
    assert c("tcp", b"GET /index.html HTTP/1.1\r\nHost: example.org\r\n\r\n") is None
    assert c("udp", b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01") is None  # DNS
    assert c("udp", bytes([0xC3, 0, 0, 0, 1]) + noise(1200, 1)) is None  # QUIC initial
    assert c("udp", b"d4:spam4:eggse") is None, "plain bencode without KRPC keys is not DHT"
    assert c("udp", UTP_SYN[:10]) is None


def test_encrypted_heuristic_needs_both_directions_and_skips_known_protocols(agent):
    table = agent.FlowTable()
    flow = ("10.0.0.2", 40000), ("198.51.100.30", 51413)
    table.packet("tcp", flow[0], flow[1], True, noise(160, 2))
    assert table.drain() == {}, "one random-looking direction is not enough"
    table.packet("tcp", flow[0], flow[1], False, noise(120, 3))
    assert table.drain() == {("-", "encrypted"): 1}
    tls = ("10.0.0.2", 40001), ("198.51.100.31", 8443)
    table.packet("tcp", tls[0], tls[1], True, TLS_HELLO)
    table.packet("tcp", tls[0], tls[1], False, noise(200, 4))
    https = ("10.0.0.2", 40002), ("198.51.100.32", 443)
    table.packet("tcp", https[0], https[1], True, noise(200, 5))
    table.packet("tcp", https[0], https[1], False, noise(200, 6))
    small = ("10.0.0.2", 40003), ("198.51.100.33", 7000)
    table.packet("tcp", small[0], small[1], True, noise(40, 7))
    table.packet("tcp", small[0], small[1], False, noise(40, 8))
    assert table.drain() == {}, "TLS, port 443 and short exchanges are not counted"


def test_one_detection_per_flow_and_inspection_limit(agent):
    table = agent.FlowTable()
    flow = ("10.0.0.2", 5000), ("198.51.100.40", 6881)
    for _ in range(5):
        table.packet("tcp", flow[0], flow[1], True, HANDSHAKE)
    other = ("10.0.0.2", 5001), ("198.51.100.41", 6881)
    for _ in range(agent.FlowTable.INSPECT):
        table.packet("tcp", other[0], other[1], True, b"hello")
    table.packet("tcp", other[0], other[1], True, HANDSHAKE)  # too late: the flow was already judged
    assert table.drain() == {("-", "bittorrent"): 1}


# ---------------------------------------------------------------- packets

def ipv4_tcp(src, dst, sport, dport, payload, frag=0):
    tcp = struct.pack("!HHIIBBHHH", sport, dport, 1, 0, 5 << 4, 0x18, 65535, 0, 0) + payload
    header = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 1, frag, 64, 6, 0, socket.inet_aton(src), socket.inet_aton(dst))
    return header + tcp


def ipv6_udp(src, dst, sport, dport, payload):
    udp = struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload
    return struct.pack("!IHBB", 6 << 28, len(udp), 17, 64) + socket.inet_pton(socket.AF_INET6, src) + socket.inet_pton(socket.AF_INET6, dst) + udp


def test_ipv4_ipv6_parsing_and_fragments(agent):
    parsed = agent.parse_l3(ipv4_tcp("10.0.0.2", "198.51.100.50", 40000, 6881, HANDSHAKE))
    assert parsed[:5] == ("tcp", "10.0.0.2", 40000, "198.51.100.50", 6881) and parsed[5] == HANDSHAKE
    parsed = agent.parse_l3(ipv6_udp("2001:db8::2", "2001:db8::50", 40001, 6881, DHT_PING))
    assert parsed[:5] == ("udp", "2001:db8::2", 40001, "2001:db8::50", 6881) and parsed[5] == DHT_PING
    assert agent.parse_l3(ipv4_tcp("10.0.0.2", "198.51.100.50", 1, 2, b"x", frag=100)) is None
    assert agent.parse_l3(b"\x45\x00") is None


def test_attribution_through_the_xray_log_never_sends_destinations(agent, tmp_path):
    index = agent.DestinationIndex()
    log_file = tmp_path / "access.log"
    log_file.write_text("")
    reader = agent.XrayAccessLog(str(log_file), "TORRENT", index)
    reader.poll()
    log_file.write_text("2026/10/23 10:00:00 from 203.0.113.7:51234 accepted tcp:198.51.100.60:6881 [VLESS >> DIRECT] email: user_1\n"
                        "2026/10/23 10:00:00 from 203.0.113.7:51235 accepted udp:[2001:db8::60]:6881 [VLESS >> DIRECT] email: user_2\n")
    assert reader.poll() == {}, "not routed to TORRENT: no xray count, but the destination is indexed"
    table = agent.FlowTable(index)
    table.packet("tcp", ("10.0.0.2", 1), ("198.51.100.60", 6881), True, HANDSHAKE)
    table.packet("udp", ("2001:db8::2", 2), ("2001:db8::60", 6881), True, DHT_PING)
    table.packet("udp", ("10.0.0.2", 3), ("198.51.100.99", 6881), True, UTP_SYN)
    sent = []
    agent._post = lambda base, path, token, body: sent.append(body) or {}
    assert agent.torrent_report("https://shop", TOKEN, reader, {}, table) == {}
    items = sorted((i["client"], i["kind"], i["events"]) for i in sent[0]["items"])
    assert items == [("-", "utp", 1), ("user_1", "bittorrent", 1), ("user_2", "dht", 1)]
    assert "198.51.100" not in json.dumps(sent) and "2001:db8" not in json.dumps(sent)


def test_ndpi_csv_counts_bittorrent_flows_with_attribution(agent):
    index = agent.DestinationIndex()
    index.add("tcp", "198.51.100.70", 6881, "user_3")
    reader = agent.NdpiReader("eth0", index)
    reader.parse("#flow_id,protocol,src_ip,src_port,dst_ip,dst_port,ndpi_proto\n"
                 "1,TCP,10.0.0.2,40000,198.51.100.70,6881,BitTorrent\n"
                 "2,UDP,10.0.0.2,40001,198.51.100.71,6881,BitTorrent.uTP\n"
                 "3,TCP,10.0.0.2,40002,198.51.100.72,443,TLS.Google\n")
    assert reader.drain() == {("user_3", "ndpi"): 1, ("-", "ndpi"): 1}
    reader.parse("")
    assert reader.drain() == {}


def test_engine_selection(agent, monkeypatch):
    monkeypatch.setenv("AGENT_DPI_IFACE", "")
    assert agent.start_dpi(None) is None, "an interface is required"
    monkeypatch.setenv("AGENT_DPI_IFACE", "lo")
    monkeypatch.setenv("AGENT_DPI_ENGINE", "ndpi")
    started = []
    monkeypatch.setattr(agent.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: started.append(target)})())
    assert isinstance(agent.start_dpi(None), agent.NdpiReader)
    monkeypatch.setenv("AGENT_DPI_ENGINE", "builtin")
    assert isinstance(agent.start_dpi(None), agent.FlowTable)
    monkeypatch.setenv("AGENT_DPI_ENGINE", "auto")
    monkeypatch.setattr(agent.shutil, "which", lambda name: None)
    assert isinstance(agent.start_dpi(None), agent.FlowTable), "no nDPI installed: the built-in classifier"
    monkeypatch.setattr(agent.shutil, "which", lambda name: "/usr/bin/ndpiReader")
    assert isinstance(agent.start_dpi(None), agent.NdpiReader)


@pytest.mark.skipif(not hasattr(socket, "AF_PACKET") or os.geteuid() != 0, reason="AF_PACKET capture needs root")
def test_real_capture_on_loopback(agent):
    table = agent.FlowTable()
    capture = agent.PacketCapture("lo", table)
    thread = threading.Thread(target=capture.run, daemon=True)
    thread.start()
    time.sleep(0.5)
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for _ in range(3):
        sender.sendto(DHT_PING, receiver.getsockname())
    sender.sendto(b"just a datagram", receiver.getsockname())
    deadline = time.monotonic() + 5
    counts = {}
    while time.monotonic() < deadline and not counts:
        time.sleep(0.1)
        counts = table.drain()
    capture.stop.set()
    thread.join(timeout=3)
    sender.close()
    receiver.close()
    assert counts.get(("-", "dht"), 0) >= 1 and table.packets >= 4


def test_classifier_throughput(agent):
    table = agent.FlowTable()
    packets = [("tcp", ("10.0.0.2", 10000 + i % 5000), ("198.51.100.%d" % (i % 250), 443 + i % 7), True, TLS_HELLO if i % 3 else b"x" * 1200)
               for i in range(60_000)]
    started = time.perf_counter()
    for proto, local, remote, out, payload in packets:
        table.packet(proto, local, remote, out, payload)
    elapsed = time.perf_counter() - started
    assert elapsed < 10, f"{len(packets) / elapsed:.0f} packets/s"


# ---------------------------------------------------------------- shop

async def make_agent(database):
    database.add(NodeAgent(name="nl-dpi", token_hash=platform_api._hash(TOKEN), enabled=True, created_at=datetime.utcnow()))
    await database.commit()


@pytest.mark.asyncio
async def test_kinds_are_stored_apart_and_the_heuristic_alone_neither_marks_nor_notifies(database):
    await make_agent(database)
    batch = torrent.TorrentBatch(items=[{"client": "user_1", "kind": "encrypted", "events": 4}, {"client": "-", "kind": "dht", "events": 9}])
    result = await torrent.agent_torrent(batch, database, TOKEN)
    assert result["accepted"] == 2 and result["matched"] == 1
    assert await database.scalar(select(func.count()).select_from(Notification).where(Notification.kind == "abuse.torrent")) == 0
    assert await torrent.recent_users(database, {1}) == set(), "a heuristic does not mark the abuse score"
    unattributed = await database.scalar(select(TorrentDetection).where(TorrentDetection.client == "-"))
    assert unattributed.user_id is None and unattributed.kind == "dht"
    await torrent.agent_torrent(torrent.TorrentBatch(items=[{"client": "user_1", "kind": "bittorrent", "events": 1},
                                                           {"client": "user_1", "kind": "encrypted", "events": 1}]), database, TOKEN)
    rows = {r.kind: r.events for r in (await database.scalars(select(TorrentDetection).where(TorrentDetection.client == "user_1"))).all()}
    assert rows == {"encrypted": 5, "bittorrent": 1}
    assert await torrent.recent_users(database, {1}) == {1}
    assert await database.scalar(select(func.count()).select_from(Notification).where(Notification.kind == "abuse.torrent")) == 1
    view = await torrent.admin_torrents(30, database, None)
    user_row = next(c for c in view["clients"] if c["client"] == "user_1")
    assert user_row["kinds"] == {"encrypted": 5, "bittorrent": 1} and user_row["likely_only"] is False
    assert view["kinds"] == {"encrypted": 5, "bittorrent": 1, "dht": 9}
    with pytest.raises(Exception):
        torrent.TorrentItem(client="user_1", kind="smtp", events=1)
