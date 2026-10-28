#!/usr/bin/env python3
"""Hot standby agent («Резервные копии → Горячий резерв»). Standard library only; runs on the standby server.

Every minute (systemd timer) it reads how far the local database copy is behind, checks the primary by its public
address, by its IP and by the replication stream, and reports to the primary. When the primary fails both checks FAIL_LIMIT times in a row it
sends a Telegram alert from here (the primary cannot) and, only with AUTO_PROMOTE=1, promotes this server
(scripts/hot-standby.sh promote) and points the Cloudflare DNS records to it.

  sudo SHOP_URL=https://api.example.com STANDBY_TOKEN=… PRIMARY_IP=198.51.100.5 python3 corgi-standby install
  python3 corgi-standby run          # one round now, prints what it saw
  sudo python3 corgi-standby uninstall

/etc/corgi-standby.env (root only) also takes: FAIL_LIMIT (5), AUTO_PROMOTE (0), APP_DIR (/opt/vpn-shop),
TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (alerts), CF_API_TOKEN + CF_ZONE_ID + CF_RECORDS (comma-separated names) and
NEW_IP (this server's address; found automatically when empty).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV_FILE = Path("/etc/corgi-standby.env")
STATE_FILE = Path("/var/lib/corgi-standby.json")
UNIT = "corgi-standby"
VERSION = "1"


def settings() -> dict:
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    keys = ("SHOP_URL", "STANDBY_TOKEN", "PRIMARY_IP", "FAIL_LIMIT", "AUTO_PROMOTE", "APP_DIR", "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID", "CF_API_TOKEN", "CF_ZONE_ID", "CF_RECORDS", "NEW_IP")
    out = {k: os.environ.get(k) or values.get(k, "") for k in keys}
    if not out["SHOP_URL"].startswith("https://") or not out["STANDBY_TOKEN"] or not out["PRIMARY_IP"]:
        sys.exit("SHOP_URL (https://…), STANDBY_TOKEN and PRIMARY_IP are required")
    out["SHOP_URL"] = out["SHOP_URL"].rstrip("/")
    out["FAIL_LIMIT"] = int(out["FAIL_LIMIT"] or 5)
    out["AUTO_PROMOTE"] = out["AUTO_PROMOTE"] == "1"
    out["APP_DIR"] = out["APP_DIR"] or "/opt/vpn-shop"
    return out


def http(url: str, *, data: dict | None = None, headers: dict | None = None, method: str | None = None,
         timeout: int = 10) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, method=method or ("POST" if body else "GET"),
                                     headers={"Content-Type": "application/json", "User-Agent": f"CorgiLusi-Standby/{VERSION}", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode() or "{}"
    try:
        return json.loads(text)
    except ValueError:
        return {}


def primary_alive(cfg: dict, streaming: bool) -> bool:
    """Down only when nothing answers: no replication stream, no /health/live, no TCP on 443 or 22 of PRIMARY_IP."""
    if streaming:
        return True
    try:
        http(cfg["SHOP_URL"] + "/health/live")
        return True
    except Exception as exc:  # noqa: BLE001 — try the IP next
        print(f"health: {exc}", file=sys.stderr)
    for port in (443, 22):
        try:
            socket.create_connection((cfg["PRIMARY_IP"], port), timeout=8).close()
            return True
        except OSError:
            continue
    return False


def database(cfg: dict) -> tuple[bool, float | None, bool]:
    query = ("SELECT pg_is_in_recovery()::text || '|' || "
             "COALESCE(EXTRACT(EPOCH FROM now() - pg_last_xact_replay_timestamp())::text, '') || '|' || "
             "COALESCE((SELECT status FROM pg_stat_wal_receiver), '')")
    result = subprocess.run(["docker", "compose", "exec", "-T", "db", "psql", "-U", "vpnshop", "-d", "vpnshop", "-At", "-c", query],
                            cwd=cfg["APP_DIR"], capture_output=True, text=True, timeout=30, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:200] or "psql failed")
    recovery, lag, receiver = (result.stdout.strip().split("|") + ["", ""])[:3]
    return recovery == "true", (round(float(lag), 1) if lag else None), receiver == "streaming"


def telegram(cfg: dict, text: str) -> None:
    if not (cfg["TELEGRAM_BOT_TOKEN"] and cfg["TELEGRAM_CHAT_ID"]):
        return
    try:
        http(f"https://api.telegram.org/bot{cfg['TELEGRAM_BOT_TOKEN']}/sendMessage", data={"chat_id": cfg["TELEGRAM_CHAT_ID"], "text": text})
    except Exception as exc:  # noqa: BLE001
        print(f"telegram: {exc}", file=sys.stderr)


def switch_dns(cfg: dict) -> list[str]:
    """Point each CF_RECORDS name (A record) to this server; returns what was changed."""
    if not (cfg["CF_API_TOKEN"] and cfg["CF_ZONE_ID"] and cfg["CF_RECORDS"]):
        return []
    ip = cfg["NEW_IP"] or http("https://api.ipify.org?format=json").get("ip", "")
    headers = {"Authorization": f"Bearer {cfg['CF_API_TOKEN']}"}
    base = f"https://api.cloudflare.com/client/v4/zones/{cfg['CF_ZONE_ID']}/dns_records"
    changed = []
    for name in [n.strip() for n in cfg["CF_RECORDS"].split(",") if n.strip()]:
        found = http(f"{base}?type=A&name={urllib.parse.quote(name)}", headers=headers).get("result") or []
        for record in found:
            http(f"{base}/{record['id']}", data={"content": ip}, headers=headers, method="PATCH")
            changed.append(f"{name} → {ip}")
    return changed


def run_once(cfg: dict) -> dict:
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"fails": 0}
    try:
        in_recovery, lag, streaming = database(cfg)
    except Exception as exc:  # noqa: BLE001
        in_recovery, lag, streaming = True, None, False
        print(f"database: {exc}", file=sys.stderr)
    alive = primary_alive(cfg, streaming)
    state["fails"] = 0 if alive else int(state.get("fails", 0)) + 1
    report = {"in_recovery": in_recovery, "lag_seconds": lag, "primary_ok": alive, "auto_promote": cfg["AUTO_PROMOTE"],
              "fail_streak": state["fails"], "host": os.uname().nodename[:120], "version": VERSION}
    if alive:
        try:
            http(cfg["SHOP_URL"] + "/api/standby/heartbeat", data=report, headers={"Authorization": f"Bearer {cfg['STANDBY_TOKEN']}"})
        except Exception as exc:  # noqa: BLE001
            print(f"heartbeat: {exc}", file=sys.stderr)
        if state.get("alerted"):
            telegram(cfg, "✅ Основной сервер магазина снова отвечает. Резерв продолжает следовать за ним.")
            state["alerted"] = False
    elif in_recovery and state["fails"] >= cfg["FAIL_LIMIT"]:
        if cfg["AUTO_PROMOTE"] and not state.get("promoted"):
            telegram(cfg, f"🚨 Основной сервер не отвечает {state['fails']} мин. Повышаю резерв до основного…")
            done = subprocess.run(["bash", "scripts/hot-standby.sh", "promote"], cwd=cfg["APP_DIR"], env={**os.environ, "FORCE": "1"},
                                  capture_output=True, text=True, timeout=900, check=False)
            if done.returncode == 0:
                state["promoted"] = True
                try:
                    changed = switch_dns(cfg)
                except Exception as exc:  # noqa: BLE001
                    changed = [f"ошибка DNS: {exc}"]
                telegram(cfg, "✅ Резерв стал основным, магазин работает здесь. " + ("DNS: " + "; ".join(changed) if changed
                         else "Переключите DNS на этот сервер вручную.") + " Старый сервер, когда вернётся: hot-standby.sh demote.")
            else:
                telegram(cfg, f"⚠️ Повышение резерва не удалось: {(done.stderr or done.stdout)[-300:]}")
        elif not state.get("alerted"):
            telegram(cfg, f"🚨 Основной сервер магазина не отвечает {state['fails']} мин (по адресу и по IP). Резерв готов: "
                          "если основной не вернётся — на этом сервере bash scripts/hot-standby.sh promote.")
            state["alerted"] = True
    STATE_FILE.write_text(json.dumps(state))
    return report


def install() -> None:
    cfg = settings()
    script = Path(__file__).resolve()
    lines = [f"{k}={os.environ[k]}" for k in ("SHOP_URL", "STANDBY_TOKEN", "PRIMARY_IP", "FAIL_LIMIT", "AUTO_PROMOTE", "APP_DIR",
                                              "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CF_API_TOKEN", "CF_ZONE_ID", "CF_RECORDS", "NEW_IP")
             if os.environ.get(k)]
    old = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    keep = [line for line in old if line.split("=", 1)[0] not in {item.split("=", 1)[0] for item in lines}]
    ENV_FILE.write_text("\n".join(keep + lines) + "\n")
    ENV_FILE.chmod(0o600)
    Path(f"/etc/systemd/system/{UNIT}.service").write_text(
        f"[Unit]\nDescription=Corgi Lusi hot standby agent\nAfter=docker.service network-online.target\n\n"
        f"[Service]\nType=oneshot\nExecStart=/usr/bin/python3 {script} run\nTimeoutStartSec=1200\n")
    Path(f"/etc/systemd/system/{UNIT}.timer").write_text(
        "[Unit]\nDescription=Corgi Lusi hot standby agent every minute\n\n[Timer]\nOnBootSec=60\nOnUnitActiveSec=60\n\n"
        "[Install]\nWantedBy=timers.target\n")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", f"{UNIT}.timer"], check=True)
    print(json.dumps(run_once(cfg), ensure_ascii=False))
    print(f"Установлено: {UNIT}.timer каждую минуту, настройки в {ENV_FILE}.")


def uninstall() -> None:
    subprocess.run(["systemctl", "disable", "--now", f"{UNIT}.timer"], check=False)
    for path in (Path(f"/etc/systemd/system/{UNIT}.service"), Path(f"/etc/systemd/system/{UNIT}.timer"), STATE_FILE):
        path.unlink(missing_ok=True)
    subprocess.run(["systemctl", "daemon-reload"], check=False)
    print(f"Удалено. {ENV_FILE} оставлен — удалите сами, если не нужен.")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "run":
        print(json.dumps(run_once(settings()), ensure_ascii=False))
    elif command == "install":
        install()
    elif command == "uninstall":
        uninstall()
    else:
        sys.exit(__doc__)
