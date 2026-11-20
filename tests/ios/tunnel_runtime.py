"""Exercise the simulator's real Swift/native engine using only loopback endpoints."""

import contextlib
import http.server
import json
import os
import platform
import socket
import struct
import subprocess
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IOS = ROOT / "apps/vpn-shop/ios"
CLIENT = socket.inet_aton("198.18.0.2")
SERVER = socket.inet_aton("192.0.2.53")
FAMILY = struct.pack("!I", socket.AF_INET)
QUESTION = b"\x05corgi\x04test\0\0\x01\0\x01"


class Endpoint(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/corgi":
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"corgi tunnel")


def simctl(*args):
    return subprocess.check_output(["xcrun", "simctl", *args], text=True)


def simulator():
    devices = json.loads(simctl("list", "devices", "available", "-j"))["devices"]
    return next(d["udid"] for runtime, group in devices.items() if ".iOS-" in runtime
                for d in group if d["name"].startswith("iPhone"))


def boot_simulator(device):
    """Boot once, then rebuild a runner simulator that stalls during data migration."""
    subprocess.run(["xcrun", "simctl", "boot", device], check=False)
    try:
        subprocess.run(
            ["xcrun", "simctl", "bootstatus", device, "-b"],
            check=True,
            timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        subprocess.run(["xcrun", "simctl", "shutdown", device], check=False)
        subprocess.run(["xcrun", "simctl", "erase", device], check=True)
        subprocess.run(["xcrun", "simctl", "boot", device], check=True)
        subprocess.run(
            ["xcrun", "simctl", "bootstatus", device, "-b"],
            check=True,
            timeout=300,
        )


def compile_probe(exe):
    frameworks = IOS / "Frameworks"
    xray = next((frameworks / "LibXray.xcframework").glob("ios-*-simulator/LibXray.framework"))
    hev = next((frameworks / "HevSocks5Tunnel.xcframework").glob("ios-*-simulator/libhev-socks5-tunnel.a"))
    sdk = subprocess.check_output(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"], text=True).strip()
    subprocess.run([
        "xcrun", "swiftc", "-swift-version", "6", "-sdk", sdk,
        "-target", f"{platform.machine()}-apple-ios16.0-simulator",
        "-F", xray.parent, "-framework", "LibXray", "-framework", "NetworkExtension",
        "-framework", "Security", "-framework", "SystemConfiguration",
        "-I", hev.parent / "Headers/HevSocks5Tunnel", hev, "-lresolv",
        IOS / "Shared/CorgiXray.swift", IOS / "CorgiTunnel/PacketTunnelProvider.swift",
        Path(__file__).with_name("TunnelRuntime.swift"), "-o", exe,
    ], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", exe], check=True)


def datagram(query):
    udp = struct.pack("!HHHH", 53001, 53, 8 + len(query), 0) + query
    header = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 1, 0, 64, 17, 0, CLIENT, SERVER)
    total = sum(struct.unpack("!10H", header))
    while total >> 16:
        total = (total & 0xffff) + (total >> 16)
    return FAMILY + header[:10] + struct.pack("!H", total ^ 0xffff) + header[12:] + udp


def check_dns(link, peer, dns, cycle):
    query = struct.pack("!6H", 300 + cycle, 0x0100, 1, 0, 0, 0) + QUESTION
    link.sendto(datagram(query), peer)
    incoming, sender = dns.recvfrom(2048)
    assert incoming == query, "DNS question changed on the way through hev and Xray"
    answer = (struct.pack("!6H", 300 + cycle, 0x8180, 1, 1, 0, 0) + QUESTION
              + b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + socket.inet_aton("192.0.2.42"))
    dns.sendto(answer, sender)
    frame, source = link.recvfrom(65535)
    assert peer == source and frame[:4] == FAMILY
    ip = frame[4:]
    assert ip[0] >> 4 == 4 and ip[9] == 17 and ip[12:20] == SERVER + CLIENT
    offset = (ip[0] & 0x0f) * 4
    sport, dport, length, _ = struct.unpack_from("!4H", ip, offset)
    assert (sport, dport, length) == (53, 53001, 8 + len(answer))
    assert ip[offset + 8:offset + length] == answer, "DNS answer did not reach the external fd"


def traffic(exe, device):
    with contextlib.ExitStack() as stack:
        web = stack.enter_context(http.server.ThreadingHTTPServer(("127.0.0.1", 0), Endpoint))
        threading.Thread(target=web.serve_forever, daemon=True).start()
        stack.callback(web.shutdown)
        endpoint = web.server_port
        dns = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        dns.bind(("127.0.0.1", endpoint))
        link = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        link.bind(("127.0.0.1", 0))
        listener = stack.enter_context(socket.socket())
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(30)
        dns.settimeout(15)
        link.settimeout(15)
        probe = subprocess.Popen(["xcrun", "simctl", "spawn", device, exe,
                                  str(listener.getsockname()[1]), str(link.getsockname()[1]), str(endpoint)])
        try:
            control, _ = listener.accept()
            with control:
                for cycle in (1, 2):
                    marker, peer = link.recvfrom(64)
                    assert marker == f"ready-{cycle}".encode(), marker
                    tcp_body = subprocess.check_output([
                        "curl", "--silent", "--show-error", "--fail", "--max-time", "10",
                        "--noproxy", "", "--socks5", "127.0.0.1:10808", "http://192.0.2.53/corgi",
                    ])
                    assert tcp_body == b"corgi tunnel"
                    check_dns(link, peer, dns, cycle)
                    control.sendall(b"S")
                    assert link.recvfrom(64) == (f"stopped-{cycle}".encode(), peer)
                    with socket.socket() as tcp:
                        tcp.settimeout(2)
                        assert tcp.connect_ex(("127.0.0.1", 10808)) != 0, "SOCKS listener survived stop"
                    print(f"cycle {cycle}: TCP, DNS over UDP through external fd, native stop and fd ownership OK", flush=True)
                    control.sendall(b"N")
            if probe.wait(timeout=15):
                raise RuntimeError("simulator probe failed")
        finally:
            if probe.poll() is None:
                probe.kill()
                probe.wait()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(dir=os.environ.get("RUNNER_TEMP")) as work:
        exe = Path(work) / "corgi-tunnel-runtime"
        compile_probe(exe)
        device = simulator()
        boot_simulator(device)
        traffic(exe, device)
