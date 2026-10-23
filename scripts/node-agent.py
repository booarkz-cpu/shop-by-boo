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


def _apply(actions: list) -> None:
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

class XrayAccessLog:
    """Follows the Xray access log and counts BitTorrent-routed lines per client.

    Starts at the end of the file (no backfill), follows rotation (new inode or a
    shorter file) and reads at most 8 MB per poll. Only counts are kept."""

    LINE = re.compile(r"\baccepted\s+(?:tcp|udp):\S+\s+\[([^\]]*)\]\s+email:\s*(\S+)")
    CHUNK = 8 * 1024 * 1024

    def __init__(self, path: str, tag: str):
        self.path, self.tag = path, tag
        self.inode: int | None = None
        self.offset = 0
        self.rest = b""

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
            match = self.LINE.search(raw.decode("utf-8", "replace"))
            if match and self._routed(match.group(1)):
                client = match.group(2)[:128]
                counts[client] = counts.get(client, 0) + 1
        return counts


def torrent_report(base: str, token: str, log: XrayAccessLog, pending: dict) -> dict:
    """Merges new counts into ``pending`` and posts them; keeps them on failure."""
    for client, events in log.poll().items():
        if client in pending or len(pending) < 2000:
            pending[client] = min(1_000_000, pending.get(client, 0) + events)
    while pending:
        batch = dict(list(pending.items())[:500])
        _post(base, "/api/agent/torrent", token, {"items": [{"client": c, "events": n} for c, n in batch.items()]})
        for client in batch:
            pending.pop(client, None)
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
    access_log = XrayAccessLog(_env("AGENT_XRAY_ACCESS_LOG"), _env("AGENT_TORRENT_TAG") or "TORRENT") if _env("AGENT_XRAY_ACCESS_LOG") else None
    pending_torrent: dict = {}
    if access_log:
        access_log.poll()  # remember the current end of the log
    while True:
        if access_log:
            try:
                torrent_report(base, token, access_log, pending_torrent)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                print(f"node-agent torrent report failed: {exc}", file=sys.stderr, flush=True)
        try:
            beat = _post(base, "/api/agent/heartbeat", token, _metrics())
            _apply(beat.get("actions") or [])
            items = _observations()
            if items:
                _post(base, "/api/agent/observations", token, {"items": items})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            print(f"node-agent delivery failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
