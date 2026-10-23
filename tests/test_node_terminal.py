"""Node terminal: confirmation, claim, relay, replay, hidden input, limits, close, audit, retention and the agent's pty."""
import asyncio
import base64
import importlib.util
import json
import os
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.requests import Request

from app import node_terminal as term
from app import platform_api, totp
from app.config import settings
from app.models import AdminUser, AuditLog, NodeAgent, TerminalChunk, TerminalSession, TerminalSnippet
from app.security import encrypt_secret, hash_password
from test_subscription_commerce import database

TOKEN = "agent-token-for-tests-0123456789"
PASSWORD = "Correct-Horse-9"
SECRET = totp.random_base32()


def request():
    return Request({"type": "http", "client": ("203.0.113.5", 4321), "headers": [], "method": "POST", "path": "/"})


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def text_of(items) -> str:
    return "".join(base64.b64decode(i["d"]).decode() for i in items if i.get("k") == "data")


class Clock:
    """Valid TOTP codes that differ from the previous one (the last used code is refused)."""

    def code(self):
        used = {code for code, _ in term._used_codes.values()}
        now = int(time.time() // 30)
        return next(c for c in (totp.code(SECRET, for_time=(now + d) * 30) for d in (0, 1, -1)) if c not in used)


@pytest_asyncio.fixture
async def world(database, monkeypatch):
    monkeypatch.setattr(settings, "terminal_enabled", True)
    monkeypatch.setattr(settings, "terminal_max_minutes", 30)
    monkeypatch.setattr(settings, "terminal_idle_minutes", 10)
    monkeypatch.setattr(term, "session_factory", async_sessionmaker(database.bind, expire_on_commit=False))
    monkeypatch.setattr(term, "relay_override", term.MemoryRelay())
    term._failures.clear()
    term._used_codes.clear()
    admin = AdminUser(email="root@example.test", password_hash=hash_password(PASSWORD), role="admin", mfa_enabled=True, totp_secret_encrypted=encrypt_secret(SECRET))
    other = AdminUser(email="second@example.test", password_hash=hash_password(PASSWORD), role="admin", mfa_enabled=True, totp_secret_encrypted=encrypt_secret(SECRET))
    node = NodeAgent(name="nl-1", token_hash=platform_api._hash(TOKEN), enabled=True, created_at=datetime.utcnow())
    node2 = NodeAgent(name="de-1", token_hash=platform_api._hash(TOKEN + "x"), enabled=True, created_at=datetime.utcnow())
    database.add_all([admin, other, node, node2])
    await database.commit()
    await platform_api.agent_heartbeat(platform_api.HeartbeatIn(terminal=True), database, TOKEN)
    await platform_api.agent_heartbeat(platform_api.HeartbeatIn(terminal=True), database, TOKEN + "x")

    async def as_admin(request, db):
        return await db.get(AdminUser, admin.id)

    monkeypatch.setattr(term, "_admin", as_admin)
    return SimpleNamespace(db=database, admin=admin, other=other, node=node, node2=node2, clock=Clock())


async def start(w, admin=None, node=None, **extra):
    body = term.StartIn(agent_id=(node or w.node).id, password=PASSWORD, code=w.clock.code(), reason="проверка xray", cols=100, rows=30, **extra)
    return await term.admin_terminal_start(body, request(), w.db, admin or w.admin)


async def claim(token=TOKEN, wait=0):
    return (await term.agent_terminal_pending(wait=wait, x_agent_token=token))["session"]


async def chunks(db, sid):
    rows = (await db.scalars(select(TerminalChunk).where(TerminalChunk.session_id == sid).order_by(TerminalChunk.id))).all()
    from app.security import decrypt_secret

    return [(r.direction, base64.b64decode(decrypt_secret(r.data_encrypted)).decode()) for r in rows]


# ---------------------------------------------------------------- full flow

@pytest.mark.asyncio
async def test_session_flow_relay_replay_hidden_input_and_audit(world):
    w = world
    session = await start(w)
    assert session["status"] == "requested"
    info = await claim()
    assert info["id"] == session["id"] and info["cols"] == 100 and info["max_seconds"] > 1700
    assert await claim() is None, "a session is claimed once"
    sid, key = info["id"], info["key"]
    stored = await w.db.get(TerminalSession, sid)
    await w.db.refresh(stored)
    assert stored.agent_key_hash != key and len(stored.agent_key_hash) == 64

    await term.admin_terminal_input(sid, term.InputIn(seq=1, data="uptime\n"), w.db, w.admin)
    assert (await term.admin_terminal_input(sid, term.InputIn(seq=1, data="uptime\n"), w.db, w.admin))["duplicate"], "retried input is not typed twice"
    got = await term.agent_terminal_input(sid, cursor="", wait=0, x_agent_token=TOKEN, x_terminal_key=key)
    assert text_of(got["items"]) == "uptime\n"
    await term.agent_terminal_output(sid, term.OutputIn(seq=1, data=b64(" 12:00 up 3 days\r\n")), TOKEN, key)
    assert (await term.agent_terminal_output(sid, term.OutputIn(seq=1, data=b64("again")), TOKEN, key))["duplicate"]
    out = await term.admin_terminal_output(sid, request(), cursor="", wait=0)
    assert [i["k"] for i in out["chunks"]] == ["opened", "data"] and text_of(out["chunks"]) == " 12:00 up 3 days\r\n"
    assert out["status"] == "active"

    # A password prompt turns echo off: the typed secret is not stored.
    await term.agent_terminal_output(sid, term.OutputIn(seq=2, data=b64("[sudo] password: "), echo=False), TOKEN, key)
    await term.admin_terminal_input(sid, term.InputIn(seq=2, data="s3cret-pass\n"), w.db, w.admin)
    got = await term.agent_terminal_input(sid, cursor=got["cursor"], wait=0, x_agent_token=TOKEN, x_terminal_key=key)
    assert text_of(got["items"]) == "s3cret-pass\n", "the node still receives it"
    await term.agent_terminal_output(sid, term.OutputIn(seq=3, data=b64("\r\n"), echo=True), TOKEN, key)
    await term.admin_terminal_input(sid, term.InputIn(seq=3, cols=140, rows=40), w.db, w.admin)
    got = await term.agent_terminal_input(sid, cursor=got["cursor"], wait=0, x_agent_token=TOKEN, x_terminal_key=key)
    assert got["items"] == [{"k": "resize", "cols": 140, "rows": 40, "s": 3}]

    transcript = await chunks(w.db, sid)
    assert ("in", "uptime\n") in transcript and ("out", " 12:00 up 3 days\r\n") in transcript
    assert ("hidden", "[скрытый ввод: 12 байт]") in transcript
    assert not any("s3cret" in text for _, text in transcript)
    encrypted = (await w.db.scalars(select(TerminalChunk.data_encrypted).where(TerminalChunk.session_id == sid))).all()
    assert not any("uptime" in e or b64("uptime") in e for e in encrypted), "stored encrypted"

    closed = await term.admin_terminal_close(sid, w.db, w.admin)
    assert closed["status"] == "closed" and closed["close_reason"] == "Закрыта администратором"
    with pytest.raises(HTTPException) as gone:
        await term.agent_terminal_input(sid, cursor=got["cursor"], wait=0, x_agent_token=TOKEN, x_terminal_key=key)
    assert gone.value.status_code == 410, "the per-session key dies with the session"
    with pytest.raises(HTTPException) as gone:
        await term.agent_terminal_output(sid, term.OutputIn(seq=4, data=b64("late")), TOKEN, key)
    assert gone.value.status_code == 410
    with pytest.raises(HTTPException) as gone:
        await term.admin_terminal_input(sid, term.InputIn(seq=4, data="ls\n"), w.db, w.admin)
    assert gone.value.status_code == 410

    view = await term.admin_terminal_transcript(sid, w.db, w.admin)
    assert view["bytes_in"] > 0 and any(c["direction"] == "hidden" for c in view["chunks"])
    actions = (await w.db.scalars(select(AuditLog.action).where(AuditLog.target == sid))).all()
    assert set(actions) >= {"terminal.session.request", "terminal.session.close", "terminal.transcript.view"}
    details = " ".join((await w.db.scalars(select(AuditLog.details).where(AuditLog.target == sid))).all())
    assert PASSWORD not in details and "s3cret" not in details


@pytest.mark.asyncio
async def test_pending_long_poll_wakes_on_request(world):
    w = world

    async def later():
        await asyncio.sleep(0.2)
        return await start(w)

    started, info = await asyncio.gather(later(), claim(wait=5))
    assert info and info["id"] == started["id"]


# ---------------------------------------------------------------- guards

@pytest.mark.asyncio
async def test_start_requires_switch_mfa_confirmation_and_ready_online_node(world, monkeypatch):
    w = world
    monkeypatch.setattr(settings, "terminal_enabled", False)
    with pytest.raises(HTTPException) as off:
        await start(w)
    assert off.value.status_code == 503
    monkeypatch.setattr(settings, "terminal_enabled", True)
    with pytest.raises(HTTPException) as wrong:
        await term.admin_terminal_start(term.StartIn(agent_id=w.node.id, password="bad", code=w.clock.code(), reason="test"), request(), w.db, w.admin)
    assert wrong.value.status_code == 401
    code = w.clock.code()
    await term.admin_terminal_start(term.StartIn(agent_id=w.node.id, password=PASSWORD, code=code, reason="first"), request(), w.db, w.admin)
    with pytest.raises(HTTPException) as replay:
        await term.admin_terminal_start(term.StartIn(agent_id=w.node2.id, password=PASSWORD, code=code, reason="replayed code"), request(), w.db, w.admin)
    assert replay.value.status_code == 401, "a TOTP code confirms one session"
    w.other.mfa_enabled = False
    await w.db.commit()
    with pytest.raises(HTTPException) as nomfa:
        await start(w, admin=w.other, node=w.node2)
    assert nomfa.value.status_code == 403 and "двухфакторный" in nomfa.value.detail
    w.node2.terminal_ready = False
    await w.db.commit()
    with pytest.raises(HTTPException) as notready:
        await start(w, node=w.node2)
    assert notready.value.status_code == 409 and "AGENT_TERMINAL=1" in notready.value.detail
    w.node2.terminal_ready, w.node2.last_seen_at = True, datetime.utcnow() - timedelta(minutes=10)
    await w.db.commit()
    with pytest.raises(HTTPException) as offline:
        await start(w, node=w.node2)
    assert offline.value.status_code == 409 and "не на связи" in offline.value.detail
    assert "nodes.terminal" not in term.PERMISSIONS["operator"] and "nodes.terminal" in term.PERMISSIONS["admin"]


@pytest.mark.asyncio
async def test_concurrency_limits_and_confirmation_lockout(world):
    w = world
    await start(w)
    with pytest.raises(HTTPException) as busy:
        await start(w)
    assert busy.value.status_code == 409 and "уже открыта" in busy.value.detail
    await start(w, node=w.node2)
    third = NodeAgent(name="fi-1", token_hash=platform_api._hash("t3" * 16), enabled=True, created_at=datetime.utcnow(), terminal_ready=True, last_seen_at=datetime.utcnow())
    w.db.add(third)
    await w.db.commit()
    with pytest.raises(HTTPException) as per_admin:
        await start(w, node=third)
    assert per_admin.value.status_code == 409 and "2 сессии" in per_admin.value.detail
    for _ in range(5):
        with pytest.raises(HTTPException):
            await term.admin_terminal_start(term.StartIn(agent_id=third.id, password="wrong", code="000000", reason="guess"), request(), w.db, w.other)
    with pytest.raises(HTTPException) as locked:
        await start(w, admin=w.other, node=third)
    assert locked.value.status_code == 429


@pytest.mark.asyncio
async def test_agent_key_and_ownership_checks(world):
    w = world
    session = await start(w)
    info = await claim()
    with pytest.raises(HTTPException) as badkey:
        await term.agent_terminal_input(info["id"], cursor="", wait=0, x_agent_token=TOKEN, x_terminal_key="forged")
    assert badkey.value.status_code == 410
    with pytest.raises(HTTPException) as othernode:
        await term.agent_terminal_input(info["id"], cursor="", wait=0, x_agent_token=TOKEN + "x", x_terminal_key=info["key"])
    assert othernode.value.status_code == 404
    with pytest.raises(HTTPException) as notowner:
        await term.admin_terminal_input(session["id"], term.InputIn(seq=1, data="id\n"), w.db, w.other)
    assert notowner.value.status_code == 404, "only the administrator who opened it types into a session"
    closed = await term.admin_terminal_close(session["id"], w.db, w.other)
    assert closed["close_reason"] == "Закрыта администратором second@example.test"


# ---------------------------------------------------------------- limits

@pytest.mark.asyncio
async def test_time_limits_exit_disable_and_transcript_cap(world, monkeypatch):
    w = world
    unclaimed = await start(w)
    await term.maintain(w.db, now=datetime.utcnow() + timedelta(seconds=130))
    assert (await w.db.get(TerminalSession, unclaimed["id"])).close_reason == "Узел не подключился за 2 минуты"

    s = await start(w)
    info = await claim()
    await term.maintain(w.db, now=datetime.utcnow() + timedelta(minutes=11))
    assert "Нет ввода 10 мин" == (await w.db.get(TerminalSession, s["id"])).close_reason

    s = await start(w)
    info = await claim()
    row = await w.db.get(TerminalSession, s["id"])
    row.last_activity_at = datetime.utcnow() + timedelta(minutes=29)
    await w.db.commit()
    await term.maintain(w.db, now=datetime.utcnow() + timedelta(minutes=31))
    assert "лимит длительности" in (await w.db.get(TerminalSession, s["id"])).close_reason

    s = await start(w)
    info = await claim()
    result = await term.agent_terminal_output(s["id"], term.OutputIn(seq=1, data=b64("bye\r\n"), exited=True, exit_code=3), TOKEN, info["key"])
    assert result["status"] == "closed"
    row = await w.db.get(TerminalSession, s["id"])
    await w.db.refresh(row)
    assert row.exit_code == 3 and row.close_reason == "Оболочка завершилась (код 3)"

    s = await start(w)
    info = await claim()
    w.node.enabled = False
    await w.db.commit()
    await term.maintain(w.db)
    assert (await w.db.get(TerminalSession, s["id"])).close_reason == "Агент узла отключён"
    w.node.enabled = True
    await w.db.commit()

    monkeypatch.setattr(term, "TRANSCRIPT_LIMIT", 10)
    s = await start(w)
    info = await claim()
    result = await term.agent_terminal_output(s["id"], term.OutputIn(seq=1, data=b64("x" * 64)), TOKEN, info["key"])
    assert result["status"] == "closed"
    with pytest.raises(HTTPException) as big:
        await term.agent_terminal_output(s["id"], term.OutputIn(seq=2, data=b64("x")), TOKEN, info["key"])
    assert big.value.status_code == 410


@pytest.mark.asyncio
async def test_switch_off_closes_live_sessions_and_retention_deletes_old(world, monkeypatch):
    w = world
    s = await start(w)
    await claim()
    monkeypatch.setattr(settings, "terminal_enabled", False)
    assert (await term.agent_terminal_pending(wait=0, x_agent_token=TOKEN)) == {"session": None, "enabled": False}
    await term.maintain(w.db)
    assert (await w.db.get(TerminalSession, s["id"])).close_reason == "Терминал выключен в настройках сервера"
    result = await term.maintain(w.db, now=datetime.utcnow() + timedelta(days=91))
    assert result["deleted"] == 1
    assert await w.db.scalar(select(func.count()).select_from(TerminalSession)) == 0
    assert await w.db.scalar(select(func.count()).select_from(TerminalChunk)) == 0


@pytest.mark.asyncio
async def test_snippets_and_overview(world):
    w = world
    snippet = await term.admin_snippet_create(term.SnippetIn(name="Статус xray", command="systemctl status xray --no-pager"), w.db, w.admin)
    view = await term.admin_terminal(w.db, w.admin)
    assert view["enabled"] and view["mfa_enabled"] and view["snippets"][0]["command"].startswith("systemctl")
    assert {a["name"]: a["terminal_ready"] and a["online"] for a in view["agents"]} == {"nl-1": True, "de-1": True}
    await term.admin_snippet_delete(snippet["id"], w.db, w.admin)
    assert await w.db.scalar(select(func.count()).select_from(TerminalSnippet)) == 0


# ---------------------------------------------------------------- the agent's pty

def load_agent():
    spec = importlib.util.spec_from_file_location("node_agent", Path(__file__).resolve().parents[1] / "scripts/node-agent.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeShop:
    """The agent side of the shop protocol, in a thread: queued input, recorded output."""

    def __init__(self):
        self.inputs, self.outputs, self.lock = [], [], threading.Lock()
        shop = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _reply(self, body):
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                assert self.headers["X-Agent-Token"] == TOKEN and self.headers["X-Terminal-Key"] == "k"
                cursor = int(parse_qs(urlparse(self.path).query).get("cursor", ["0"])[0] or 0)
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    with shop.lock:
                        if len(shop.inputs) > cursor:
                            return self._reply({"items": shop.inputs[cursor:], "cursor": str(len(shop.inputs))})
                    time.sleep(0.02)
                self._reply({"items": [], "cursor": str(cursor)})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with shop.lock:
                    shop.outputs.append(body)
                self._reply({"ok": True, "status": "active"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def send(self, text=None, **item):
        with self.lock:
            self.inputs.append({"k": "data", "d": b64(text)} if text is not None else item)

    def text(self):
        with self.lock:
            return "".join(base64.b64decode(o["data"]).decode("utf-8", "replace") for o in self.outputs)

    def wait_for(self, needle, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if needle in self.text():
                return True
            time.sleep(0.05)
        raise AssertionError(f"{needle!r} not in output: {self.text()[-500:]!r}")


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setenv("AGENT_TOKEN", TOKEN)
    monkeypatch.setenv("AGENT_TERMINAL_SHELL", "/bin/sh")
    monkeypatch.delenv("AGENT_TERMINAL_USER", raising=False)
    shop = FakeShop()
    module = load_agent()
    yield module, shop
    shop.server.shutdown()


def test_agent_shell_env_has_no_token_hides_secrets_and_reports_exit(agent):
    module, shop = agent
    terminal = module.Terminal(shop.base, TOKEN, {"id": "s-1", "key": "k", "cols": 90, "rows": 25, "max_seconds": 60})
    runner = threading.Thread(target=terminal.run, daemon=True)
    runner.start()
    shop.send('echo "token=[$AGENT_TOKEN] session=$CORGI_TERMINAL_SESSION cols=$(stty size)"\n')
    shop.wait_for("session=s-1 cols=25 90")
    assert "token=[]" in shop.text() and TOKEN not in shop.text()
    shop.send("stty -echo; printf 'pass: '\n")
    shop.wait_for("pass: ")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not any(o.get("echo") is False for o in shop.outputs):
        time.sleep(0.05)
    assert any(o.get("echo") is False for o in shop.outputs), "echo off is reported before the secret is typed"
    shop.send("hunter2\n")
    shop.send("stty echo; echo done\n")
    shop.wait_for("done")
    shop.send(k="resize", cols=132, rows=43)
    shop.send("stty size\n")
    shop.wait_for("43 132")
    shop.send("exit 3\n")
    runner.join(timeout=10)
    assert not runner.is_alive()
    last = shop.outputs[-1]
    assert last["exited"] is True and last["exit_code"] == 3
    seqs = [o["seq"] for o in shop.outputs]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_agent_close_kills_the_shell_group(agent):
    module, shop = agent
    terminal = module.Terminal(shop.base, TOKEN, {"id": "s-2", "key": "k", "max_seconds": 60})
    runner = threading.Thread(target=terminal.run, daemon=True)
    runner.start()
    shop.send("sleep 300 & echo child=$!\n")
    shop.wait_for("child=")
    import re

    deadline = time.monotonic() + 5
    while not re.search(r"child=(\d+)", shop.text()) and time.monotonic() < deadline:
        time.sleep(0.05)
    child = int(re.findall(r"child=(\d+)", shop.text())[-1])
    shop.send(k="close", reason="test")
    runner.join(timeout=10)
    assert not runner.is_alive()
    time.sleep(0.3)
    try:
        os.kill(child, 0)
        alive = open(f"/proc/{child}/stat").read().split()[2] != "Z"
    except (ProcessLookupError, FileNotFoundError):
        alive = False
    assert not alive, "background jobs of the session are ended too"
    assert shop.outputs[-1]["exited"] is True


def test_agent_heartbeat_reports_terminal_flag(agent, monkeypatch):
    module, _ = agent
    assert module._metrics()["terminal"] is False
    monkeypatch.setenv("AGENT_TERMINAL", "1")
    assert module._metrics()["terminal"] is True
    monkeypatch.setenv("AGENT_TERMINAL_USER", "nobody-else-user")
    if os.geteuid() != 0:
        with pytest.raises(RuntimeError):
            module._shell_argv()
    else:
        argv = module._shell_argv()
        assert "runuser" in argv and argv[-2:] == ["/bin/sh", "-l"]


@pytest.mark.asyncio
async def test_redis_relay_streams_cursor_and_block():
    url = os.environ.get("REDIS_URL")
    if not url:
        pytest.skip("Redis relay runs where REDIS_URL is set (CI)")
    from redis.asyncio import Redis

    client = Redis.from_url(url, decode_responses=True)
    try:
        await client.ping()
    except Exception:
        pytest.skip("Redis is not reachable")
    relay = term.RedisRelay(client)
    key = "term:test-" + os.urandom(4).hex() + ":out"
    try:
        assert await relay.last(key) == "0-0"
        assert await relay.read(key, None, 0) == ([], "0-0")
        await relay.append(key, {"k": "data", "d": b64("one")})
        items, cursor = await relay.read(key, None, 0)
        assert text_of(items) == "one" and cursor != "0-0"

        async def later():
            await asyncio.sleep(0.2)
            await relay.append(key, {"k": "data", "d": b64("two")})

        (items, after), _ = await asyncio.gather(relay.read(key, cursor, 3), later())
        assert text_of(items) == "two" and after > cursor
        assert await client.ttl(key) > 0, "streams expire on their own"
    finally:
        await relay.drop(key)
        await client.aclose()


def test_agent_secret_detection_follows_line_mode(agent):
    """bash readline turns echo off too, but in raw mode: only canonical no-echo reads are secrets."""
    import pty as ptymod
    import termios as tm

    module, _ = agent
    master, slave = ptymod.openpty()
    try:
        attrs = tm.tcgetattr(slave)
        attrs[3] = (attrs[3] & ~tm.ECHO) | tm.ICANON  # getpass / sudo / read -s
        tm.tcsetattr(slave, tm.TCSANOW, attrs)
        assert module._echo_on(master) is False
        attrs[3] = attrs[3] & ~tm.ICANON  # readline, vim, top: raw mode, they echo themselves
        tm.tcsetattr(slave, tm.TCSANOW, attrs)
        assert module._echo_on(master) is True
        attrs[3] = attrs[3] | tm.ECHO | tm.ICANON
        tm.tcsetattr(slave, tm.TCSANOW, attrs)
        assert module._echo_on(master) is True
    finally:
        os.close(master)
        os.close(slave)
