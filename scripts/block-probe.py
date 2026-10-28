#!/usr/bin/env python3
"""Block probe for the shop's block monitor («Серверы → Монитор блокировок»). Standard library only.

Put it on a small server (or any always-on Linux box) in the region whose customers you want to watch — for example
a cheap VPS in Russia. Every 5 minutes it asks the shop what to check (API domains, reserve domains, VPN nodes),
tries each address and reports back. The probe never sees customer data; its token only allows these two calls.

  sudo SHOP_URL=https://api.example.com PROBE_TOKEN=… python3 corgi-probe install   # systemd timer every 5 minutes
  python3 corgi-probe run                                                         # one round now (prints results)
  sudo python3 corgi-probe uninstall
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV_FILE = Path("/etc/corgi-probe.env")
UNIT = "corgi-probe"
TIMEOUT = 8


def config() -> tuple[str, str]:
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    shop = os.environ.get("SHOP_URL") or values.get("SHOP_URL", "")
    token = os.environ.get("PROBE_TOKEN") or values.get("PROBE_TOKEN", "")
    if not shop.startswith("https://") or not token:
        sys.exit("SHOP_URL (https://…) and PROBE_TOKEN are required")
    return shop.rstrip("/"), token


def call(shop: str, token: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(shop + path, data=data, method="POST" if data else "GET",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                              "User-Agent": "CorgiLusi-Probe/1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode() or "{}")


def check(target: str) -> dict:
    """https://host/path — TLS handshake and an HTTP answer below 500; tcp://host:port — a TCP connection."""
    started = time.monotonic()
    try:
        parts = urllib.parse.urlsplit(target)
        if parts.scheme == "tcp":
            socket.create_connection((parts.hostname, parts.port or 443), timeout=TIMEOUT).close()
        elif parts.scheme == "https":
            request = urllib.request.Request(target, headers={"User-Agent": "Mozilla/5.0 CorgiLusi-Probe/1"})
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT, context=ssl.create_default_context()) as response:
                    status = response.status
            except urllib.error.HTTPError as exc:
                status = exc.code
            if status >= 500:
                raise OSError(f"HTTP {status}")
        else:
            raise ValueError("unsupported target")
        return {"target": target, "ok": True, "ms": int((time.monotonic() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001 — every failure is a result
        return {"target": target, "ok": False, "ms": int((time.monotonic() - started) * 1000), "error": f"{type(exc).__name__}: {exc}"[:200]}


def run() -> int:
    shop, token = config()
    targets = call(shop, token, "/api/probe/targets").get("targets", [])[:200]
    results = [check(t) for t in targets]
    out = call(shop, token, "/api/probe/report", {"results": results})
    for r in results:
        print(("OK  " if r["ok"] else "FAIL") + f" {r['ms']:>5} ms  {r['target']}  {r.get('error') or ''}")
    if out.get("blocked"):
        print("Blocked now:", ", ".join(out["blocked"]))
    return 0


def install() -> int:
    shop, token = config()
    if os.geteuid() != 0:
        sys.exit("run install with sudo")
    script = Path("/usr/local/bin/corgi-probe")
    if Path(__file__).resolve() != script:
        script.write_text(Path(__file__).read_text())
    script.chmod(0o755)
    ENV_FILE.write_text(f"SHOP_URL={shop}\nPROBE_TOKEN={token}\n")
    ENV_FILE.chmod(0o600)
    Path(f"/etc/systemd/system/{UNIT}.service").write_text(
        "[Unit]\nDescription=Corgi Lusi block probe\nAfter=network-online.target\n\n"
        f"[Service]\nType=oneshot\nExecStart=/usr/bin/python3 {script} run\nDynamicUser=yes\n"
        f"EnvironmentFile={ENV_FILE}\nNoNewPrivileges=yes\nProtectSystem=strict\nProtectHome=yes\nPrivateTmp=yes\n")
    Path(f"/etc/systemd/system/{UNIT}.timer").write_text(
        "[Unit]\nDescription=Corgi Lusi block probe every 5 minutes\n\n"
        "[Timer]\nOnBootSec=1min\nOnUnitActiveSec=5min\nRandomizedDelaySec=30\n\n[Install]\nWantedBy=timers.target\n")
    os.system("systemctl daemon-reload && systemctl enable --now corgi-probe.timer")
    print("Installed: the probe runs every 5 minutes (systemctl status corgi-probe.timer). First round now:")
    return run()


def uninstall() -> int:
    os.system("systemctl disable --now corgi-probe.timer 2>/dev/null")
    for path in (Path(f"/etc/systemd/system/{UNIT}.service"), Path(f"/etc/systemd/system/{UNIT}.timer"), ENV_FILE):
        path.unlink(missing_ok=True)
    os.system("systemctl daemon-reload")
    print("Removed. Delete the probe in the admin panel too.")
    return 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    sys.exit({"run": run, "install": install, "uninstall": uninstall}.get(command, lambda: sys.exit(__doc__))())
