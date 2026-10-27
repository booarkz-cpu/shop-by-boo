#!/usr/bin/env python3
"""Pull-based node agent for Remnawave VPN Shop.

Posts a heartbeat and optional connection observations. Applies only the
queued actions throttle and clear, and only when AGENT_APPLY_TC=1.
The token is sent in a header and is not written to stdout.

With AGENT_TERMINAL=1 the agent also serves terminal sessions opened from the
admin panel: it long-polls the shop (no port is opened on the node), runs the
shell on a pseudo-terminal as AGENT_TERMINAL_USER when set, never passes its
own environment (and so never the agent token) to the shell, reports when the
terminal reads a secret (echo off in line mode) so typed passwords are not recorded, and ends the shell
when the session closes or its time is up. See docs/ru/NODE_TERMINAL_CURRENT.md.

With AGENT_XRAY_ACCESS_LOG set, the agent counts connections that Xray routed to
the BitTorrent outbound (AGENT_TORRENT_TAG) per Xray client and posts only those
counts: no destinations, ports or log lines leave the node.
See docs/ru/TORRENT_DETECTION_CURRENT.md.

With AGENT_OBSERVE_ACCESS_LOG=1 the same log also feeds the abuse scoring: the agent
sends each client's distinct public source IPs (up to 8 per client per interval) as
connection observations; destinations and log lines still stay on the node.

With AGENT_DPI=1 (root, AGENT_DPI_IFACE) the agent also classifies traffic itself:
nDPI's ndpiReader when installed, otherwise a built-in classifier of the first packets
of each flow (BitTorrent handshake, DHT, uTP, trackers, and a heuristic for encrypted
BitTorrent). Flows are attributed to Xray clients by destination from the access log,
kept in memory only; again only counts per client and kind leave the node.
See docs/ru/TRAFFIC_ANALYSIS_CURRENT.md.
"""
from __future__ import annotations

import base64
import contextlib
import fcntl
import ipaddress
import json
import os
import pathlib
import pty
import pwd
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _metrics() -> dict:
    cpu = "0"
    try:
        cpu = pathlib.Path("/proc/loadavg").read_text().split()[0]
    except OSError:
        cpu = "0"
    mem = ""
    try:
        info = {}
        for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            info[key] = rest.strip().split()[0]
        total = int(info.get("MemTotal") or 0)
        avail = int(info.get("MemAvailable") or 0)
        if total:
            mem = str(round((total - avail) * 100 / total))
    except (OSError, ValueError):
        mem = ""
    disk = ""
    try:
        usage = shutil.disk_usage("/")
        disk = str(round(usage.used * 100 / usage.total))
    except OSError:
        disk = ""
    xray = False
    proc = pathlib.Path("/proc")
    if proc.is_dir():
        for comm in proc.glob("[0-9]*/comm"):
            try:
                if comm.read_text().strip() == "xray":
                    xray = True
                    break
            except OSError:
                continue
    return {"cpu": cpu[:32], "mem": mem[:32], "disk": disk[:32], "xray_ok": xray, "version": "2", "terminal": _env("AGENT_TERMINAL") == "1"}


def _observations() -> list:
    path = _env("OBSERVATIONS_FILE")
    if not path:
        return []
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return data[:200]


def _global_ip(value: str) -> str | None:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return None
    if not addr.is_global:
        return None
    return str(addr)


def _iface() -> str | None:
    name = _env("AGENT_IFACE")
    if not name or len(name) > 15:
        return None
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
    if any(ch not in allowed for ch in name):
        return None
    return name


NODE_COMMANDS = {
    # Remnawave node container managed by Docker Compose in AGENT_NODE_DIR (default /opt/remnanode).
    "update_node": (["docker", "compose", "pull"], ["docker", "compose", "up", "-d", "--remove-orphans"]),
    "restart_node": (["docker", "compose", "restart"],),
}


def _node_actions(actions: list) -> list[str]:
    """update_node / restart_node from «Ноды → Мониторинг», only with AGENT_ALLOW_NODE_UPDATE=1.
    Fixed argv lists in the node directory: nothing from the shop reaches a shell."""
    done = []
    if _env("AGENT_ALLOW_NODE_UPDATE") != "1":
        return done
    folder = _env("AGENT_NODE_DIR", "/opt/remnanode")
    if not os.path.isfile(os.path.join(folder, "docker-compose.yml")):
        print(f"node-agent: {folder}/docker-compose.yml not found, node update skipped", file=sys.stderr, flush=True)
        return done
    for action in actions:
        kind = str(action.get("kind") or "")
        for argv in NODE_COMMANDS.get(kind, ()):
            result = subprocess.run(argv, cwd=folder, check=False, timeout=900)
            if result.returncode != 0:
                print(f"node-agent: {' '.join(argv)} exited {result.returncode}", file=sys.stderr, flush=True)
                break
        else:
            if kind in NODE_COMMANDS:
                done.append(kind)
    return done


def _apply(actions: list) -> None:
    _node_actions(actions)
    if _env("AGENT_APPLY_TC") != "1":
        return
    iface = _iface()
    if not iface:
        return
    for action in actions:
        kind = str(action.get("kind") or "")
        if kind not in {"throttle", "clear"}:
            continue
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        ips = payload.get("ips") if isinstance(payload.get("ips"), list) else []
        for raw in ips[:5]:
            ip = _global_ip(str(raw))
            if not ip:
                continue
            if kind == "clear":
                argv = ["tc", "filter", "del", "dev", iface, "protocol", "ip", "parent", "ffff:", "prio", "1"]
            else:
                try:
                    kbps = int(payload.get("kbps") or 1024)
                except (TypeError, ValueError):
                    continue
                if kbps < 64 or kbps > 100000:
                    continue
                argv = [
                    "tc", "filter", "replace", "dev", iface, "parent", "ffff:",
                    "protocol", "ip", "prio", "1", "u32",
                    "match", "ip", "dst", ip,
                    "police", "rate", f"{kbps}kbit", "burst", "32k", "drop",
                ]
            subprocess.run(argv, check=False)


def _post(base: str, path: str, token: str, body: dict) -> dict:
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Agent-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode()
    return json.loads(raw) if raw else {}


# ---------------------------------------------------------------- BitTorrent counts from the Xray access log

class DestinationIndex:
    """Recent Xray destinations -> client, kept only in memory.

    Every accepted connection in the access log maps (protocol, host, port) to the
    Xray client for 15 minutes, so a flow seen by the traffic classifier can be
    attributed to a client. Nothing from the index is ever sent."""

    TTL = 900.0
    LIMIT = 200_000

    def __init__(self):
        self.items: dict = {}
        self.lock = threading.Lock()

    def add(self, proto: str, host: str, port: int, client: str) -> None:
        with self.lock:
            key = (proto, host.lower(), port)
            self.items.pop(key, None)
            self.items[key] = (client, time.monotonic())
            while len(self.items) > self.LIMIT:
                self.items.pop(next(iter(self.items)))

    def client(self, proto: str, host: str, port: int) -> str | None:
        with self.lock:
            found = self.items.get((proto, host.lower(), port))
        if not found or time.monotonic() - found[1] > self.TTL:
            return None
        return found[0]


def _split_destination(value: str) -> tuple[str, int] | None:
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        return None
    return host.strip("[]"), int(port)


class XrayAccessLog:
    """Follows the Xray access log: counts BitTorrent-routed lines per client and,
    for the traffic classifier, remembers recent destinations per client.

    Starts at the end of the file (no backfill), follows rotation (new inode or a
    shorter file) and reads at most 8 MB per poll. Only counts are kept."""

    LINE = re.compile(r"\baccepted\s+(tcp|udp):(\S+)\s+\[([^\]]*)\]\s+email:\s*(\S+)")
    SOURCE = re.compile(r"\bfrom\s+(?:tcp:|udp:)?\[?([0-9A-Fa-f:.]+?)\]?:\d+\s+accepted\b")
    CHUNK = 8 * 1024 * 1024
    SOURCE_CLIENTS, SOURCE_IPS = 2000, 8

    def __init__(self, path: str, tag: str, index: DestinationIndex | None = None, sources: bool = False):
        self.path, self.tag, self.index = path, tag, index
        self.inode: int | None = None
        self.offset = 0
        self.rest = b""
        # AGENT_OBSERVE_ACCESS_LOG=1: client -> distinct public source IPs since the last drain.
        self.collect_sources = sources
        self.sources: dict = {}

    def _remember_source(self, text: str, client: str) -> None:
        match = self.SOURCE.search(text)
        ip = _global_ip(match.group(1)) if match else None
        if not ip:
            return
        seen = self.sources.get(client)
        if seen is None:
            if len(self.sources) >= self.SOURCE_CLIENTS:
                return
            seen = self.sources[client] = set()
        if len(seen) < self.SOURCE_IPS:
            seen.add(ip)

    def drain_sources(self) -> list:
        """Observations for the abuse scoring: one item per client and source IP."""
        items = [{"client": client, "ip": ip} for client, ips in self.sources.items() for ip in sorted(ips)]
        self.sources = {}
        return items[:200]

    def _routed(self, route: str) -> bool:
        target = re.split(r"->|>>", route)[-1].strip() if ("->" in route or ">>" in route) else ""
        return target == self.tag

    def poll(self) -> dict:
        try:
            stat = os.stat(self.path)
        except OSError:
            return {}
        if self.inode is None:
            self.inode, self.offset = stat.st_ino, stat.st_size  # start at the end
            return {}
        if stat.st_ino != self.inode or stat.st_size < self.offset:
            self.inode, self.offset, self.rest = stat.st_ino, 0, b""  # rotated or truncated
        if stat.st_size == self.offset:
            return {}
        try:
            with open(self.path, "rb") as handle:
                handle.seek(self.offset)
                data = handle.read(self.CHUNK)
        except OSError:
            return {}
        self.offset += len(data)
        lines = (self.rest + data).split(b"\n")
        self.rest = lines.pop()[-65536:]  # an unfinished last line waits for the next poll
        counts: dict = {}
        for raw in lines:
            text = raw.decode("utf-8", "replace")
            match = self.LINE.search(text)
            if not match:
                continue
            proto, destination, route, client = match.groups()
            client = client[:128]
            if self.collect_sources:
                self._remember_source(text, client)
            if self.index is not None:
                parsed = _split_destination(destination)
                if parsed:
                    self.index.add(proto, parsed[0], parsed[1], client)
            if self._routed(route):
                counts[client] = counts.get(client, 0) + 1
        return counts


# ---------------------------------------------------------------- traffic classifier

BT_HANDSHAKE = b"\x13BitTorrent protocol"
UDP_TRACKER_MAGIC = (0x41727101980).to_bytes(8, "big")
CONFIRMED = ("bittorrent", "dht", "utp", "tracker")
SKIP_PORTS = {22, 53, 443, 465, 853, 993, 995}


def _entropy_ratio(data: bytes) -> float:
    import math

    if not data:
        return 0.0
    counts = [0] * 256
    for byte in data:
        counts[byte] += 1
    total = len(data)
    entropy = -sum(c / total * math.log2(c / total) for c in counts if c)
    return entropy / math.log2(min(total, 256))


def _random_looking(payload: bytes) -> bool:
    """Shape of an MSE/PE key exchange: 96 bytes of DH key plus up to 512 of padding,
    no known protocol prefix, near-maximal byte entropy."""
    if not 96 <= len(payload) <= 608:
        return False
    if payload[:1] in (b"\x16", b"\x17") or payload[:4] in (b"SSH-", b"GET ", b"POST", b"HTTP", b"PRI ") or payload.startswith(BT_HANDSHAKE):
        return False
    return _entropy_ratio(payload) >= 0.85


def classify_payload(proto: str, payload: bytes) -> str | None:
    """A confirmed BitTorrent-family protocol from the first bytes of one packet."""
    if proto == "tcp":
        if payload.startswith(BT_HANDSHAKE):
            return "bittorrent"
        head = payload[:512]
        if head.startswith(b"GET /") and (b"info_hash=" in head or head.startswith(b"GET /announce") or head.startswith(b"GET /scrape")):
            return "tracker"
        return None
    if len(payload) >= 16 and payload[:8] == UDP_TRACKER_MAGIC and payload[8:12] == b"\x00\x00\x00\x00":
        return "tracker"  # UDP tracker connect request (BEP 15)
    head = payload[:400]
    if head.startswith(b"d") and b"1:y1:" in head and (b"2:id20:" in head or b"1:t" in head) and (b"1:q" in head or b"1:r" in head):
        return "dht"  # bencoded KRPC (BEP 5)
    if len(payload) >= 20 and payload[0] == 0x41 and payload[1] in (0, 1, 2):
        return "utp"  # uTP ST_SYN, version 1 (BEP 29)
    return None


class FlowTable:
    """First packets of each flow -> one detection per flow, attributed via the Xray index.

    Counts are kept per (client, kind); unattributed flows use the client "-"."""

    LIMIT = 100_000
    INSPECT = 6

    def __init__(self, index: DestinationIndex | None = None):
        self.index = index
        self.flows: dict = {}
        self.counts: dict = {}
        self.lock = threading.Lock()
        self.packets = 0

    def _count(self, proto: str, remote: str, port: int, kind: str) -> None:
        client = (self.index.client(proto, remote, port) if self.index else None) or "-"
        with self.lock:
            key = (client, kind)
            self.counts[key] = self.counts.get(key, 0) + 1

    def packet(self, proto: str, local: tuple, remote: tuple, outgoing: bool, payload: bytes) -> None:
        self.packets += 1
        if not payload:
            return
        key = (proto, local, remote)
        flow = self.flows.get(key)
        if flow is None:
            if len(self.flows) >= self.LIMIT:
                self.flows.pop(next(iter(self.flows)))
            flow = self.flows[key] = {"seen": 0, "done": False, "out": None}
        if flow["done"]:
            return
        flow["seen"] += 1
        kind = classify_payload(proto, payload)
        if kind is None and proto == "tcp" and remote[1] not in SKIP_PORTS:
            if outgoing and flow["out"] is None:
                flow["out"] = _random_looking(payload)
            elif not outgoing and flow["out"] and _random_looking(payload):
                kind = "encrypted"  # heuristic: both directions open with key-exchange-shaped noise
        if kind:
            flow["done"] = True
            self._count(proto, remote[0], remote[1], kind)
        elif flow["seen"] >= self.INSPECT:
            flow["done"] = True

    def drain(self) -> dict:
        with self.lock:
            counts, self.counts = self.counts, {}
        return counts


def parse_l3(data: bytes) -> tuple | None:
    """(proto, src, sport, dst, dport, payload) from an IPv4/IPv6 packet."""
    if len(data) < 20:
        return None
    version = data[0] >> 4
    if version == 4:
        ihl = (data[0] & 0x0F) * 4
        number = data[9]
        total = int.from_bytes(data[2:4], "big") or len(data)
        if int.from_bytes(data[6:8], "big") & 0x1FFF:
            return None  # a later fragment carries no transport header
        src, dst = str(ipaddress.IPv4Address(data[12:16])), str(ipaddress.IPv4Address(data[16:20]))
        body = data[ihl:total]
    elif version == 6 and len(data) >= 40:
        number = data[6]
        src, dst = str(ipaddress.IPv6Address(data[8:24])), str(ipaddress.IPv6Address(data[24:40]))
        body = data[40:40 + int.from_bytes(data[4:6], "big")]
    else:
        return None
    if number == 6 and len(body) >= 20:
        offset = (body[12] >> 4) * 4
        return "tcp", src, int.from_bytes(body[0:2], "big"), dst, int.from_bytes(body[2:4], "big"), body[offset:]
    if number == 17 and len(body) >= 8:
        return "udp", src, int.from_bytes(body[0:2], "big"), dst, int.from_bytes(body[2:4], "big"), body[8:]
    return None


class PacketCapture:
    """AF_PACKET capture on one interface (needs CAP_NET_RAW); feeds the flow table."""

    def __init__(self, iface: str, table: FlowTable):
        self.iface, self.table = iface, table
        self.stop = threading.Event()

    def run(self) -> None:
        import socket

        sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(0x0003))
        sock.bind((self.iface, 0))
        sock.settimeout(1.0)
        while not self.stop.is_set():
            try:
                data, address = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                time.sleep(1)
                continue
            if address[1] not in (0x0800, 0x86DD):
                continue
            parsed = parse_l3(data)
            if not parsed:
                continue
            proto, src, sport, dst, dport, payload = parsed
            outgoing = address[2] == 4  # PACKET_OUTGOING
            local, remote = ((src, sport), (dst, dport)) if outgoing else ((dst, dport), (src, sport))
            self.table.packet(proto, local, remote, outgoing, payload)
        sock.close()


class NdpiReader:
    """Runs nDPI's ndpiReader for a capture window and counts BitTorrent flows from its CSV."""

    def __init__(self, iface: str, index: DestinationIndex | None, binary: str = "ndpiReader", seconds: int = 30):
        self.iface, self.index, self.binary, self.seconds = iface, index, binary, seconds
        self.counts: dict = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def parse(self, text: str) -> None:
        import csv
        import io as _io

        rows = list(csv.reader(_io.StringIO(text)))
        if not rows:
            return
        header = [h.strip().lstrip("#").lower() for h in rows[0]]

        def column(*names):
            return next((header.index(n) for n in names if n in header), None)

        src, dst = column("src_ip", "src_addr", "client_ip"), column("dst_ip", "dst_addr", "server_ip")
        sport, dport = column("src_port", "sport", "client_port"), column("dst_port", "dport", "server_port")
        for row in rows[1:]:
            if not any(re.search(r"(?i)bittorrent", cell or "") for cell in row):
                continue
            client = None
            if self.index is not None:
                for host, port in ((dst, dport), (src, sport)):
                    if host is None or port is None or host >= len(row) or port >= len(row) or not row[port].strip().isdigit():
                        continue
                    for proto in ("tcp", "udp"):
                        client = client or self.index.client(proto, row[host].strip(), int(row[port]))
            with self.lock:
                key = (client or "-", "ndpi")
                self.counts[key] = self.counts.get(key, 0) + 1

    def run(self) -> None:
        import tempfile

        while not self.stop.is_set():
            with tempfile.TemporaryDirectory() as tmp:
                out = os.path.join(tmp, "flows.csv")
                try:
                    subprocess.run([self.binary, "-i", self.iface, "-s", str(self.seconds), "-C", out, "-q"],
                                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=self.seconds + 60)
                    with open(out, encoding="utf-8", errors="replace") as handle:
                        self.parse(handle.read())
                except (OSError, subprocess.TimeoutExpired) as exc:
                    print(f"node-agent ndpiReader failed: {exc}", file=sys.stderr, flush=True)
                    time.sleep(30)

    def drain(self) -> dict:
        with self.lock:
            counts, self.counts = self.counts, {}
        return counts


def start_dpi(index: DestinationIndex | None):
    """AGENT_DPI=1: nDPI when installed (or AGENT_DPI_ENGINE=ndpi), else the built-in classifier."""
    iface = _env("AGENT_DPI_IFACE")
    if not iface or len(iface) > 15:
        print("node-agent: AGENT_DPI_IFACE is required for traffic analysis", file=sys.stderr, flush=True)
        return None
    engine = (_env("AGENT_DPI_ENGINE") or "auto").lower()
    if engine == "ndpi" or (engine == "auto" and shutil.which("ndpiReader")):
        source = NdpiReader(iface, index, shutil.which("ndpiReader") or "ndpiReader")
    else:
        source = FlowTable(index)
        capture = PacketCapture(iface, source)
        threading.Thread(target=capture.run, daemon=True).start()
        return source
    threading.Thread(target=source.run, daemon=True).start()
    return source


def torrent_report(base: str, token: str, log: XrayAccessLog | None, pending: dict, dpi=None) -> dict:
    """Merges new counts into ``pending`` ((client, kind) -> n) and posts them; keeps them on failure."""
    fresh = {(client, "xray"): n for client, n in (log.poll() if log else {}).items()}
    if dpi is not None:
        for key, n in dpi.drain().items():
            fresh[key] = fresh.get(key, 0) + n
    for key, events in fresh.items():
        if key in pending or len(pending) < 2000:
            pending[key] = min(1_000_000, pending.get(key, 0) + events)
    while pending:
        batch = dict(list(pending.items())[:500])
        _post(base, "/api/agent/torrent", token, {"items": [{"client": c, "kind": k, "events": n} for (c, k), n in batch.items()]})
        for key in batch:
            pending.pop(key, None)
    return pending


# ---------------------------------------------------------------- terminal

class SessionGone(Exception):
    """The shop closed the session (HTTP 410/404): stop the shell."""


def _call(base: str, method: str, path: str, token: str, body: dict | None = None, headers: dict | None = None, timeout: float = 40) -> dict:
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "X-Agent-Token": token, **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            raise SessionGone(str(exc.code)) from exc
        raise
    return json.loads(raw) if raw else {}


def _shell_argv() -> list[str]:
    shell = _env("AGENT_TERMINAL_SHELL") or ("/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh")
    user = _env("AGENT_TERMINAL_USER")
    argv = [shell, "-l"]
    if user:
        if os.geteuid() == 0:
            argv = ["runuser", "-u", user, "--", *argv]
        elif pwd.getpwuid(os.geteuid()).pw_name != user:
            raise RuntimeError(f"AGENT_TERMINAL_USER={user}, but the agent runs as another user and is not root")
    # setsid --ctty makes the pty the shell's controlling terminal (job control, Ctrl+C).
    return (["setsid", "--ctty"] if shutil.which("setsid") else []) + argv


def _shell_env(session_id: str) -> dict:
    """A fresh environment: nothing from the agent's own (AGENT_TOKEN stays out)."""
    user = _env("AGENT_TERMINAL_USER")
    try:
        home = pwd.getpwnam(user).pw_dir if user else pwd.getpwuid(os.geteuid()).pw_dir
    except KeyError:
        home = "/"
    return {"TERM": "xterm-256color", "LANG": os.environ.get("LANG") or "C.UTF-8", "HOME": home,
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "CORGI_TERMINAL_SESSION": session_id}


def _set_size(fd: int, cols: int, rows: int) -> None:
    cols, rows = max(20, min(400, int(cols))), max(5, min(200, int(rows)))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _echo_on(fd: int) -> bool:
    """False while the terminal reads a secret: echo off in canonical (line) mode, as
    getpass, sudo, passwd and read -s set it. Line editors (bash readline, vim, top)
    switch canonical mode off and echo by themselves, so their input stays recorded."""
    try:
        lflag = termios.tcgetattr(fd)[3]
    except termios.error:
        return True
    return bool(lflag & termios.ECHO) or not bool(lflag & termios.ICANON)


class Terminal:
    """One shell on a pseudo-terminal, connected to one shop session."""

    def __init__(self, base: str, token: str, info: dict):
        self.base, self.token = base, token
        self.sid, self.key = str(info["id"]), str(info["key"])
        self.cols, self.rows = int(info.get("cols") or 120), int(info.get("rows") or 32)
        self.deadline = time.monotonic() + max(1, int(info.get("max_seconds") or 1800))
        self.stop = threading.Event()
        self.seq = 0
        self.lock = threading.Lock()
        self.echo = True

    def _headers(self) -> dict:
        return {"X-Terminal-Key": self.key}

    def _send(self, data: bytes = b"", exited: bool = False, exit_code: int | None = None) -> None:
        with self.lock:
            self.seq += 1
            body = {"seq": self.seq, "data": base64.b64encode(data).decode(), "echo": self.echo, "exited": exited, "exit_code": exit_code}
            for attempt in range(5):
                try:
                    result = _call(self.base, "POST", f"/api/agent/terminal/{self.sid}/output", self.token, body, self._headers(), timeout=20)
                    if result.get("status") == "closed":
                        self.stop.set()
                    return
                except SessionGone:
                    self.stop.set()
                    return
                except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
                    time.sleep(min(5, 0.5 * 2 ** attempt))  # the same seq is retried; the shop ignores repeats
            self.stop.set()

    def _read_output(self, master: int) -> None:
        pending = b""
        while not self.stop.is_set():
            ready, _, _ = select.select([master], [], [], 0.05)
            echo = _echo_on(master)
            if ready:
                try:
                    data = os.read(master, 16384)
                except OSError:
                    data = b""
                if not data:
                    break
                pending += data
                if len(pending) < 32768:
                    continue
            if pending or echo != self.echo:
                self.echo = echo
                self._send(pending[:65536])
                pending = pending[65536:]
        if pending:
            self._send(pending[:65536])

    def _read_input(self, master: int) -> None:
        cursor = ""
        while not self.stop.is_set():
            try:
                query = urllib.parse.urlencode({"cursor": cursor, "wait": 20})
                result = _call(self.base, "GET", f"/api/agent/terminal/{self.sid}/input?{query}", self.token, None, self._headers(), timeout=40)
            except SessionGone:
                self.stop.set()
                return
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
                time.sleep(2)
                continue
            cursor = str(result.get("cursor") or cursor)
            for item in result.get("items") or []:
                kind = item.get("k")
                if kind == "data":
                    with contextlib.suppress(OSError, ValueError):
                        os.write(master, base64.b64decode(item.get("d") or ""))
                elif kind == "resize":
                    with contextlib.suppress(OSError, ValueError, TypeError):
                        _set_size(master, item.get("cols") or self.cols, item.get("rows") or self.rows)
                elif kind == "close":
                    self.stop.set()
                    return

    def run(self) -> None:
        try:
            argv = _shell_argv()
        except RuntimeError as exc:
            self._send(f"\r\n{exc}\r\n".encode(), exited=True, exit_code=126)
            return
        master, slave = pty.openpty()
        _set_size(master, self.cols, self.rows)
        try:
            proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=_shell_env(self.sid), cwd="/",
                                    close_fds=True, start_new_session=not argv[0] == "setsid")
        except OSError as exc:
            os.close(master)
            os.close(slave)
            self._send(f"\r\nНе удалось запустить оболочку: {exc}\r\n".encode(), exited=True, exit_code=127)
            return
        os.close(slave)
        print(f"node-agent terminal session {self.sid} started", file=sys.stderr, flush=True)
        reader = threading.Thread(target=self._read_output, args=(master,), daemon=True)
        poller = threading.Thread(target=self._read_input, args=(master,), daemon=True)
        reader.start()
        poller.start()
        while not self.stop.is_set() and proc.poll() is None and time.monotonic() < self.deadline:
            time.sleep(0.2)
        code = proc.poll()
        if code is None:
            self._kill(proc)
            code = proc.poll()
        else:
            reader.join(timeout=2)  # flush the shell's last output
            self._kill(proc)  # jobs the shell left behind in its session
        self.stop.set()
        reader.join(timeout=2)
        with contextlib.suppress(OSError):
            os.close(master)
        self._send(exited=True, exit_code=code)
        print(f"node-agent terminal session {self.sid} ended", file=sys.stderr, flush=True)

    @staticmethod
    def _members(session_id: int) -> list[int]:
        """Every process of the shell's session, background job groups included."""
        out = []
        for stat in pathlib.Path("/proc").glob("[0-9]*/stat"):
            try:
                fields = stat.read_text().rsplit(")", 1)[1].split()
            except (OSError, IndexError):
                continue
            if len(fields) > 3 and fields[3] == str(session_id):
                out.append(int(stat.parent.name))
        return out

    def _kill(self, proc: subprocess.Popen) -> None:
        for sig, wait in ((signal.SIGHUP, 2.0), (signal.SIGKILL, 2.0)):
            targets = set(self._members(proc.pid)) | {proc.pid}
            for pid in targets:
                try:
                    os.kill(pid, sig)
                except (ProcessLookupError, PermissionError):
                    continue
            try:
                proc.wait(timeout=wait)
            except subprocess.TimeoutExpired:
                continue
            if not [p for p in self._members(proc.pid) if p != proc.pid]:
                return

def terminal_loop(base: str, token: str) -> None:
    """Waits for sessions requested for this node; serves one at a time."""
    while True:
        try:
            result = _call(base, "GET", "/api/agent/terminal/pending?wait=20", token, timeout=40)
            info = result.get("session")
            if info:
                Terminal(base, token, info).run()
            elif result.get("enabled") is False:
                time.sleep(60)  # terminals are switched off in the shop
        except SessionGone:
            time.sleep(10)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            print(f"node-agent terminal poll failed: {exc}", file=sys.stderr, flush=True)
            time.sleep(5)


def main() -> None:
    base = _env("SHOP_API_BASE")
    token = _env("AGENT_TOKEN")
    if not base or not token:
        raise SystemExit("SHOP_API_BASE and AGENT_TOKEN are required")
    interval = 60
    try:
        interval = max(15, int(_env("AGENT_INTERVAL", "60")))
    except ValueError:
        interval = 60
    if _env("AGENT_TERMINAL") == "1":
        threading.Thread(target=terminal_loop, args=(base, token), daemon=True).start()
    dpi_on = _env("AGENT_DPI") == "1"
    index = DestinationIndex() if dpi_on and _env("AGENT_XRAY_ACCESS_LOG") else None
    access_log = XrayAccessLog(_env("AGENT_XRAY_ACCESS_LOG"), _env("AGENT_TORRENT_TAG") or "TORRENT", index,
                               sources=_env("AGENT_OBSERVE_ACCESS_LOG") == "1") if _env("AGENT_XRAY_ACCESS_LOG") else None
    pending_torrent: dict = {}
    if access_log:
        access_log.poll()  # remember the current end of the log
    dpi = start_dpi(index) if dpi_on else None
    while True:
        if access_log or dpi:
            try:
                torrent_report(base, token, access_log, pending_torrent, dpi)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                print(f"node-agent torrent report failed: {exc}", file=sys.stderr, flush=True)
        try:
            beat = _post(base, "/api/agent/heartbeat", token, _metrics())
            _apply(beat.get("actions") or [])
            items = _observations()
            if access_log and access_log.collect_sources:
                items = (items + access_log.drain_sources())[:200]
            if items:
                _post(base, "/api/agent/observations", token, {"items": items})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            print(f"node-agent delivery failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
