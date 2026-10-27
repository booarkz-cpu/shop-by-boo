#!/usr/bin/env python3
"""Автообновление магазина с GitHub — агент на сервере (только стандартная библиотека Python).

Команды (обычно через scripts/auto-update.sh, от root):
  install  — включить: ночная проверка выпусков и агент управления из админ-панели
  run      — проверить GitHub и обновиться сейчас (это запускает ночной таймер)
  agent    — раз в минуту: применить настройки из админ-панели, выполнить «Обновить сейчас»,
             записать состояние для панели
  status   — показать состояние
  disable  — выключить всё (таймеры удаляются; управление из панели перестаёт работать)

Связь с админ-панелью — два файла в каталоге $APP_DIR/.control (внутри backend это /data/control):
  auto-update.request.json  пишет панель: {"enabled": bool, "time": "HH:MM", "check_now": "<метка>"}
  auto-update.status.json   пишет агент: версии, расписание, итог последнего запуска, хвост журнала
Агент принимает из запроса только эти три поля и проверяет их формат; панель не может выполнить на
сервере ничего другого.

Само обновление — scripts/update-from-github.sh: проверка SHA-256 и манифеста, снимок файлов и дамп
базы, сборка, миграции, проверка здоровья, автоматический откат при сбое.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

APP_DIR = Path(os.environ.get("APP_DIR") or Path(__file__).resolve().parents[1])
CONF_DIR = Path(os.environ.get("AUTO_UPDATE_CONF_DIR", "/etc/vpn-shop"))
SYSTEMD_DIR = Path(os.environ.get("AUTO_UPDATE_SYSTEMD_DIR", "/etc/systemd/system"))
CONTROL_DIR = Path(os.environ.get("AUTO_UPDATE_CONTROL_DIR") or APP_DIR / ".control")
CONFIG = CONF_DIR / "auto-update.json"
FAILED = CONF_DIR / "auto-update.failed"
HANDLED = CONF_DIR / "auto-update.handled"
REQUEST = CONTROL_DIR / "auto-update.request.json"
STATUS = CONTROL_DIR / "auto-update.status.json"
UNIT = "vpn-shop-update"
AGENT = "vpn-shop-update-agent"
BACKEND_UID = 10001  # backend container user (backend/Dockerfile)
KEEP_SNAPSHOTS = 5
LOG_LINES = 40
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MARK_RE = re.compile(r"^[A-Za-z0-9:._-]{1,64}$")
DEFAULT = {"enabled": True, "time": "03:00"}

sys.path.insert(0, str(APP_DIR / "scripts"))


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- configuration

def load_config() -> dict:
    try:
        data = json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return dict(DEFAULT)
    return {"enabled": bool(data.get("enabled", True)),
            "time": data.get("time") if TIME_RE.match(str(data.get("time", ""))) else DEFAULT["time"]}


def save_config(config: dict) -> None:
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    write_atomic(CONFIG, json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def write_atomic(path: Path, text: str, mode: int = 0o640) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_request() -> dict:
    """The panel's request, reduced to the fields the agent accepts; malformed fields are ignored."""
    try:
        raw = json.loads(REQUEST.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    if isinstance(raw.get("enabled"), bool):
        out["enabled"] = raw["enabled"]
    if isinstance(raw.get("time"), str) and TIME_RE.match(raw["time"]):
        out["time"] = raw["time"]
    if isinstance(raw.get("check_now"), str) and MARK_RE.match(raw["check_now"]):
        out["check_now"] = raw["check_now"]
    return out


# ---------------------------------------------------------------- systemd

def systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", *args], capture_output=True, text=True)


def units(config: dict) -> dict[str, str]:
    script = APP_DIR / "scripts" / "auto_update.py"
    service = (f"[Unit]\nDescription=Корги Люси: автообновление магазина с GitHub\n"
               f"After=docker.service network-online.target\nWants=network-online.target\n\n"
               f"[Service]\nType=oneshot\nEnvironment=APP_DIR={APP_DIR}\n"
               f"ExecStart=/usr/bin/env python3 {script} run\nTimeoutStartSec=2h\nNice=5\n")
    timer = (f"[Unit]\nDescription=Корги Люси: ночная проверка новых выпусков\n\n"
             f"[Timer]\nOnCalendar=*-*-* {config['time']}:00 Europe/Moscow\nRandomizedDelaySec=900\nPersistent=true\n\n"
             f"[Install]\nWantedBy=timers.target\n")
    agent_service = (f"[Unit]\nDescription=Корги Люси: управление автообновлением из админ-панели\n"
                     f"After=docker.service\n\n[Service]\nType=oneshot\nEnvironment=APP_DIR={APP_DIR}\n"
                     f"ExecStart=/usr/bin/env python3 {script} agent\nTimeoutStartSec=2h\n")
    agent_timer = ("[Unit]\nDescription=Корги Люси: агент автообновления\n\n"
                   "[Timer]\nOnBootSec=1min\nOnUnitInactiveSec=1min\nAccuracySec=10s\n\n"
                   "[Install]\nWantedBy=timers.target\n")
    return {f"{UNIT}.service": service, f"{UNIT}.timer": timer,
            f"{AGENT}.service": agent_service, f"{AGENT}.timer": agent_timer}


def apply_schedule(config: dict) -> None:
    """Write the units and switch the nightly timer on or off; the agent timer always runs."""
    for name, text in units(config).items():
        path = SYSTEMD_DIR / name
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
    systemctl("daemon-reload")
    systemctl("enable", "--now", f"{AGENT}.timer")
    if config["enabled"]:
        systemctl("enable", f"{UNIT}.timer")
        systemctl("restart", f"{UNIT}.timer")
    else:
        systemctl("disable", "--now", f"{UNIT}.timer")


def next_run() -> str | None:
    result = systemctl("show", f"{UNIT}.timer", "-p", "NextElapseUSecRealtime", "--value")
    value = (result.stdout or "").strip()
    return value or None


# ---------------------------------------------------------------- versions, notifications

def installed_version() -> str:
    try:
        from github_release_fetch import current_distribution
        return current_distribution(APP_DIR)
    except Exception:  # noqa: BLE001 — a broken tree must not stop the status report
        return "?"


def latest_release() -> str:
    try:
        import github_release_fetch as g
        return str(g.fetch_json(g.API).get("tag_name") or "").lstrip("v")
    except Exception:  # noqa: BLE001 — GitHub unreachable
        return ""


def env_value(name: str) -> str:
    try:
        lines = (APP_DIR / ".env").read_text().splitlines()
    except OSError:
        return ""
    value = ""
    for line in lines:
        if line.startswith(name + "="):
            value = line.split("=", 1)[1].strip().strip("'\"")
    return value


def notify(text: str) -> None:
    token, chat = env_value("BOT_TOKEN"), env_value("ALERT_TELEGRAM_CHAT_ID") or env_value("ADMIN_TELEGRAM_ID")
    if not token or not chat:
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": "🔄 Корги Люси: " + text}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=15).read()
    except Exception as exc:  # noqa: BLE001 — a notification never fails the update
        print(f"Уведомление в Telegram не отправлено: {exc}", file=sys.stderr)


def prune_snapshots() -> None:
    folder = APP_DIR / ".rollback"
    for kind in ("tar.gz", "sql"):
        files = sorted(folder.glob(f"pre-update-*.{kind}"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[KEEP_SNAPSHOTS:]:
            old.unlink(missing_ok=True)


# ---------------------------------------------------------------- status for the panel

def write_status(**fields) -> None:
    try:
        current = json.loads(STATUS.read_text())
    except (OSError, ValueError):
        current = {}
    config = load_config()
    current.update({"enabled": config["enabled"], "time": config["time"], "installed": installed_version(),
                    "agent_seen_at": now(), "recovery_mode": (APP_DIR / ".rollback" / "RECOVERY_MODE").exists(),
                    "failed_release": FAILED.read_text().strip() if FAILED.exists() else None})
    current.update(fields)
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    write_atomic(STATUS, json.dumps(current, ensure_ascii=False, indent=2) + "\n", 0o644)


# ---------------------------------------------------------------- update

def run_update(trigger: str = "schedule") -> str:
    """Check GitHub and update. Returns updated | current | skipped | failed."""
    lock = open("/run/vpn-shop-update.lock" if os.access("/run", os.W_OK) else CONF_DIR / "update.lock", "w")
    try:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return "skipped"
    before = installed_version()
    latest = latest_release()
    if (APP_DIR / ".rollback" / "RECOVERY_MODE").exists():
        message = "Прошлое обновление не удалось и откатывается или требует проверки (.rollback/RECOVERY_MODE)."
        write_status(last_run_at=now(), last_result="skipped", last_message=message, latest=latest or None, running=False, trigger=trigger)
        return "skipped"
    if trigger == "schedule" and latest and FAILED.exists() and FAILED.read_text().strip() == latest:
        message = f"Выпуск {latest} уже не установился и был откачен — ждём следующего выпуска."
        write_status(last_run_at=now(), last_result="skipped", last_message=message, latest=latest, running=False, trigger=trigger)
        return "skipped"
    write_status(running=True, started_at=now(), latest=latest or None, trigger=trigger)
    proc = subprocess.run(["bash", str(APP_DIR / "scripts" / "update-from-github.sh")], cwd=APP_DIR,
                          env={**os.environ, "APP_DIR": str(APP_DIR)}, capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    print(output, end="")
    tail = output.strip().splitlines()[-LOG_LINES:]
    after = installed_version()
    if proc.returncode != 0:
        CONF_DIR.mkdir(parents=True, exist_ok=True)
        if latest:
            FAILED.write_text(latest)
        message = f"Обновление до {latest or 'нового выпуска'} не удалось; магазин возвращён к {before}, если откат прошёл."
        write_status(running=False, last_run_at=now(), last_result="failed", last_message=message, log_tail=tail)
        notify(message + " Журнал: journalctl -u " + UNIT)
        return "failed"
    FAILED.unlink(missing_ok=True)
    if after != before:
        prune_snapshots()
        message = f"Обновлено {before} → {after}, проверки здоровья пройдены."
        write_status(running=False, last_run_at=now(), last_result="updated", last_message=message, log_tail=tail)
        notify(message)
        return "updated"
    write_status(running=False, last_run_at=now(), last_result="current", last_message=f"Установлена актуальная версия {after}.", log_tail=tail)
    return "current"


# ---------------------------------------------------------------- commands

def prepare_control_dir() -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONTROL_DIR, 0o770)
    try:
        os.chown(CONTROL_DIR, 0, BACKEND_UID)  # root owns it; the backend group may write requests
    except PermissionError as exc:
        print(f"Не удалось назначить владельца {CONTROL_DIR}: {exc}", file=sys.stderr)


def cmd_install() -> None:
    config = load_config()
    save_config(config)
    prepare_control_dir()
    apply_schedule(config)
    write_status(next_run=next_run(), running=False)
    print(f"Автообновление включено: каждую ночь в {config['time']} по Москве; управление — админ-панель → «Обновления».")
    print(f"Журнал: journalctl -u {UNIT}. Выключить: sudo bash {APP_DIR}/scripts/auto-update.sh disable")


def cmd_ensure() -> None:
    """Called by update.sh before the containers start: the control dir exists with the right owner (or Docker
    would create it root-only), a server updated from an older release gets auto-update once, and units of a
    newer release are refreshed. An owner's «disable» is kept."""
    prepare_control_dir()
    if os.environ.get("CI") or os.geteuid() != 0 or not SYSTEMD_DIR.is_dir() or not shutil.which("systemctl"):
        return  # CI images, unprivileged builds and hosts without systemd only get the directory
    if not CONFIG.exists():
        cmd_install()
        return
    config = load_config()
    installed = (SYSTEMD_DIR / f"{AGENT}.timer").exists()
    if installed and any(not (SYSTEMD_DIR / n).exists() or (SYSTEMD_DIR / n).read_text() != t for n, t in units(config).items()):
        apply_schedule(config)


def cmd_agent() -> None:
    config = load_config()
    request = read_request()
    changed = False
    for key in ("enabled", "time"):
        if key in request and request[key] != config[key]:
            config[key] = request[key]
            changed = True
    if changed:
        save_config(config)
        apply_schedule(config)
    mark = request.get("check_now")
    handled = HANDLED.read_text().strip() if HANDLED.exists() else ""
    if mark and mark != handled:
        CONF_DIR.mkdir(parents=True, exist_ok=True)
        HANDLED.write_text(mark)  # first: a crash must not re-run the same request forever
        write_status(handled_check_now=mark)
        run_update(trigger="panel")
    write_status(next_run=next_run() if config["enabled"] else None)


def cmd_status() -> None:
    config = load_config()
    try:
        status = json.loads(STATUS.read_text())
    except (OSError, ValueError):
        status = {}
    print(f"Установлена версия: {installed_version()}")
    print(f"Автообновление: {'включено' if config['enabled'] else 'выключено'}, время {config['time']} МСК")
    for key, title in (("last_run_at", "Последний запуск"), ("last_result", "Итог"), ("last_message", "Сообщение"), ("next_run", "Следующая проверка")):
        if status.get(key):
            print(f"{title}: {status[key]}")


def cmd_disable() -> None:
    for name in (f"{UNIT}.timer", f"{AGENT}.timer"):
        systemctl("disable", "--now", name)
    for name in units(load_config()):
        (SYSTEMD_DIR / name).unlink(missing_ok=True)
    systemctl("daemon-reload")
    save_config({**load_config(), "enabled": False})
    write_status(enabled=False, next_run=None)
    print(f"Автообновление выключено. Включить снова: sudo bash {APP_DIR}/scripts/auto-update.sh install")


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command in {"install", "enable"}:
        cmd_install()
    elif command == "ensure":
        cmd_ensure()
    elif command == "run":
        return 0 if run_update() in {"updated", "current", "skipped"} else 1
    elif command == "agent":
        cmd_agent()
    elif command == "status":
        cmd_status()
    elif command == "disable":
        cmd_disable()
    else:
        print("Использование: auto_update.py install|run|agent|status|disable", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
