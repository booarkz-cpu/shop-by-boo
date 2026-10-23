"""Node terminal: an interactive shell on a VPN node, opened from the admin panel.

Trust model (each line is enforced here or in the agent):

* **Two keys.** The shop must allow terminals (``TERMINAL_ENABLED=true`` in ``.env``,
  never from the panel) and the node owner must start the agent with
  ``AGENT_TERMINAL=1``. Either side alone cannot open a shell.
* **Who.** Only the ``admin`` role has ``nodes.terminal``; the administrator must have
  two-factor sign-in enabled and confirms every session with the account password
  and a fresh TOTP code (a code is accepted once).
* **Short-lived credentials.** A session must be claimed by the agent within two
  minutes; the agent then gets a per-session key (only its hash is stored). The
  session ends at ``TERMINAL_MAX_MINUTES``, after ``TERMINAL_IDLE_MINUTES`` without
  operator input, when either side disconnects, when the shell exits, when the agent
  is disabled, or when an administrator closes it.
* **Limits.** One live session per node, two per administrator, five in total;
  bounded input and output chunks and a transcript size cap.
* **Replay.** Input and output carry sequence numbers; a repeated or older sequence is
  ignored, so a retried request never types a command twice. A closed session cannot
  be reopened.
* **Audit.** Every input and output chunk is stored encrypted (AES-GCM) with the
  session; input typed while the node's terminal has echo off (password prompts) is
  recorded only as its length. Starting, closing and viewing a transcript are written
  to the audit log. Transcripts are kept ``TERMINAL_TRANSCRIPT_DAYS``.

Transport: the browser and the agent both use HTTP long polling, so no connection to
the node is ever opened from the shop and nothing new is exposed on the node. Data
between the two passes through Redis Streams (in-process queues without Redis), and
no database connection is held while a request waits.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import SessionLocal, get_db
from .models import AdminUser, NodeAgent, TerminalChunk, TerminalSession, TerminalSnippet
from .security import PERMISSIONS, bearer, current_admin, decrypt_secret, encrypt_secret, require_permission, verify_password, verify_totp

logger = logging.getLogger("vpnshop.node_terminal")

PERMISSION = "nodes.terminal"
CLAIM_SECONDS = 120
AGENT_ONLINE = timedelta(minutes=3)
MAX_WAIT = 25.0
MAX_INPUT = 8 * 1024
MAX_OUTPUT = 64 * 1024
TRANSCRIPT_LIMIT = 8 * 1024 * 1024
MAX_PER_NODE, MAX_PER_ADMIN, MAX_TOTAL = 1, 2, 5
LIVE = ("requested", "active")
FAILED_CONFIRMATIONS = 5
FAILURE_WINDOW = 900.0


def private(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(dependencies=[Depends(private)])
session_factory = SessionLocal  # tests replace it with their engine


def utcnow() -> datetime:
    return datetime.utcnow()


def max_minutes() -> int:
    return max(1, min(120, int(settings.terminal_max_minutes or 30)))


def idle_minutes() -> int:
    return max(1, min(60, int(settings.terminal_idle_minutes or 10)))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ---------------------------------------------------------------- relay

class MemoryRelay:
    """Single-process relay (development and tests)."""

    def __init__(self):
        self.streams: dict[str, list[dict]] = defaultdict(list)
        self.events: dict[str, asyncio.Event] = {}

    def _event(self, key: str) -> asyncio.Event:
        event = self.events.get(key)
        if event is None:
            event = self.events[key] = asyncio.Event()
        return event

    async def append(self, key: str, item: dict) -> None:
        self.streams[key].append(item)
        event = self.events.pop(key, None)
        if event:
            event.set()

    async def last(self, key: str) -> str:
        return str(len(self.streams.get(key, [])))

    async def read(self, key: str, cursor: str | None, timeout: float) -> tuple[list[dict], str]:
        position = int(cursor) if cursor and cursor.isdigit() else 0
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            items = self.streams.get(key, [])
            if len(items) > position:
                chunk = items[position:position + 200]
                return chunk, str(position + len(chunk))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return [], str(position)
            try:
                await asyncio.wait_for(self._event(key).wait(), remaining)
            except asyncio.TimeoutError:
                return [], str(position)

    async def drop(self, *keys: str) -> None:
        for key in keys:
            self.streams.pop(key, None)


class RedisRelay:
    """Cross-process relay on Redis Streams: any backend process can serve either side."""

    def __init__(self, client):
        self.client = client

    async def append(self, key: str, item: dict) -> None:
        await self.client.xadd(key, {"j": json.dumps(item)}, maxlen=5000, approximate=True)
        await self.client.expire(key, 3 * 3600)

    async def last(self, key: str) -> str:
        rows = await self.client.xrevrange(key, count=1)
        return rows[0][0] if rows else "0-0"

    async def read(self, key: str, cursor: str | None, timeout: float) -> tuple[list[dict], str]:
        cursor = cursor if cursor and "-" in cursor else "0-0"
        kwargs = {"count": 200}
        if timeout > 0:
            kwargs["block"] = int(timeout * 1000)
        result = await self.client.xread({key: cursor}, **kwargs)
        items = []
        for _stream, entries in result or []:
            for entry_id, fields in entries:
                cursor = entry_id
                try:
                    items.append(json.loads(fields.get("j") or fields.get(b"j") or "{}"))
                except (TypeError, ValueError):
                    continue
        return items, cursor

    async def drop(self, *keys: str) -> None:
        await self.client.delete(*keys)


_memory = MemoryRelay()
relay_override = None  # tests set a relay here


def relay():
    if relay_override is not None:
        return relay_override
    from . import main

    client = getattr(main, "redis_client", None)
    return RedisRelay(client) if client is not None else _memory


def key_in(sid: str) -> str:
    return f"term:{sid}:in"


def key_out(sid: str) -> str:
    return f"term:{sid}:out"


def key_wake(agent_id: int) -> str:
    return f"term:agent:{agent_id}:wake"


# ---------------------------------------------------------------- transcript and lifecycle

def _record(db: AsyncSession, session: TerminalSession, direction: str, data: bytes) -> None:
    db.add(TerminalChunk(session_id=session.id, direction=direction, size=len(data),
                         data_encrypted=encrypt_secret(base64.b64encode(data).decode()), created_at=utcnow()))
    if direction == "out":
        session.bytes_out += len(data)
    elif direction in ("in", "hidden"):
        session.bytes_in += len(data)


async def close(db: AsyncSession, session: TerminalSession, reason: str, actor: str = "system") -> None:
    """Closes a live session; the caller commits. Both sides are told through the relay."""
    if session.status == "closed":
        return
    session.status, session.closed_at, session.close_reason = "closed", utcnow(), reason[:255]
    session.agent_key_hash = None
    _record(db, session, "event", f"Сессия закрыта: {reason}".encode())
    from .main import audit

    await audit(db, "terminal.session.close", actor, session.id, {"node": session.agent_name, "reason": reason})
    await relay().append(key_in(session.id), {"k": "close", "reason": reason})
    await relay().append(key_out(session.id), {"k": "closed", "reason": reason})


async def enforce_limits(db: AsyncSession, session: TerminalSession, now: datetime | None = None) -> None:
    """Closes a session whose time is up. The caller commits."""
    if session.status not in LIVE:
        return
    now = now or utcnow()
    if session.status == "requested" and now - session.created_at > timedelta(seconds=CLAIM_SECONDS):
        await close(db, session, "Узел не подключился за 2 минуты")
        return
    if now >= session.expires_at:
        await close(db, session, f"Достигнут лимит длительности ({max_minutes()} мин)")
        return
    if session.status == "active" and session.last_activity_at and now - session.last_activity_at > timedelta(minutes=idle_minutes()):
        await close(db, session, f"Нет ввода {idle_minutes()} мин")
        return
    agent = await db.get(NodeAgent, session.agent_id)
    if agent is None or not agent.enabled:
        await close(db, session, "Агент узла отключён")
    elif not settings.terminal_enabled:
        await close(db, session, "Терминал выключен в настройках сервера")


def _session_row(s: TerminalSession) -> dict:
    return {"id": s.id, "agent_id": s.agent_id, "node": s.agent_name, "admin": s.admin_email, "reason": s.reason,
            "status": s.status, "close_reason": s.close_reason, "created_at": s.created_at.isoformat(),
            "claimed_at": s.claimed_at.isoformat() if s.claimed_at else None,
            "closed_at": s.closed_at.isoformat() if s.closed_at else None, "expires_at": s.expires_at.isoformat(),
            "bytes_in": s.bytes_in, "bytes_out": s.bytes_out, "exit_code": s.exit_code, "cols": s.cols, "rows": s.rows}


# ---------------------------------------------------------------- admin API

async def _admin(request: Request, db: AsyncSession) -> AdminUser:
    """Authenticates like require_permission, on a caller-owned short DB session."""
    admin = await current_admin(request, await bearer(request), db)
    if PERMISSION not in PERMISSIONS.get(admin.role, set()):
        raise HTTPException(403, "Insufficient permissions")
    return admin


def _allowed(admin) -> None:
    if PERMISSION not in PERMISSIONS.get(getattr(admin, "role", ""), set()):
        raise HTTPException(403, "Insufficient permissions")


async def _owned(db: AsyncSession, sid: str, admin) -> TerminalSession:
    session = await db.get(TerminalSession, sid, with_for_update=True, populate_existing=True)
    if session is None or session.admin_id != admin.id:
        raise HTTPException(404, "Сессия не найдена")
    return session


@router.get("/api/admin/terminal")
async def admin_terminal(db: AsyncSession = Depends(get_db), admin=Depends(require_permission(PERMISSION))):
    now = utcnow()
    for session in (await db.scalars(select(TerminalSession).where(TerminalSession.status.in_(LIVE)))).all():
        await enforce_limits(db, session, now)
    await db.commit()
    agents = (await db.scalars(select(NodeAgent).order_by(NodeAgent.name))).all()
    sessions = (await db.scalars(select(TerminalSession).order_by(TerminalSession.created_at.desc()).limit(30))).all()
    snippets = (await db.scalars(select(TerminalSnippet).order_by(TerminalSnippet.name))).all()
    return {
        "enabled": settings.terminal_enabled, "mfa_enabled": bool(admin.mfa_enabled),
        "can_audit": "security.manage" in PERMISSIONS.get(admin.role, set()),
        "limits": {"max_minutes": max_minutes(), "idle_minutes": idle_minutes(), "transcript_days": settings.terminal_transcript_days,
                   "per_node": MAX_PER_NODE, "per_admin": MAX_PER_ADMIN, "total": MAX_TOTAL},
        "agents": [{"id": a.id, "name": a.name, "enabled": a.enabled, "terminal_ready": a.terminal_ready,
                    "online": bool(a.last_seen_at and now - a.last_seen_at < AGENT_ONLINE),
                    "last_seen_at": a.last_seen_at.isoformat() if a.last_seen_at else None} for a in agents],
        "sessions": [_session_row(s) for s in sessions],
        "snippets": [{"id": s.id, "name": s.name, "command": s.command} for s in snippets],
    }


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: int
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=8)
    reason: str = Field(min_length=3, max_length=255)
    cols: int = Field(default=120, ge=20, le=400)
    rows: int = Field(default=32, ge=5, le=200)


_failures: dict[int, list[float]] = defaultdict(list)
_used_codes: dict[int, tuple[str, float]] = {}


def _confirm(admin: AdminUser, password: str, code: str) -> None:
    now = time.monotonic()
    recent = [t for t in _failures[admin.id] if now - t < FAILURE_WINDOW]
    _failures[admin.id] = recent
    if len(recent) >= FAILED_CONFIRMATIONS:
        raise HTTPException(429, "Слишком много неверных подтверждений, повторите через 15 минут")
    used = _used_codes.get(admin.id)
    code = code.strip()
    if not verify_password(password, admin.password_hash) or not verify_totp(admin, code) or (used and used[0] == code and now - used[1] < 120):
        _failures[admin.id].append(now)
        raise HTTPException(401, "Неверный пароль или код подтверждения")
    _used_codes[admin.id] = (code, now)


@router.post("/api/admin/terminal/sessions")
async def admin_terminal_start(body: StartIn, request: Request, db: AsyncSession = Depends(get_db), admin=Depends(require_permission(PERMISSION))):
    if not settings.terminal_enabled:
        raise HTTPException(503, "Терминал выключен: задайте TERMINAL_ENABLED=true в .env и перезапустите backend")
    if not admin.mfa_enabled:
        raise HTTPException(403, "Для терминала включите двухфакторный вход в разделе «Защита и 2FA»")
    _confirm(admin, body.password, body.code)
    agent = await db.get(NodeAgent, body.agent_id, with_for_update=True)
    now = utcnow()
    if agent is None or not agent.enabled:
        raise HTTPException(404, "Агент узла не найден или отключён")
    if not agent.terminal_ready:
        raise HTTPException(409, "На узле терминал не включён: запустите агент с AGENT_TERMINAL=1")
    if not agent.last_seen_at or now - agent.last_seen_at > AGENT_ONLINE:
        raise HTTPException(409, "Агент узла не на связи")
    for live in (await db.scalars(select(TerminalSession).where(TerminalSession.status.in_(LIVE)))).all():
        await enforce_limits(db, live, now)
    await db.flush()
    counts = {
        "node": select(func.count()).select_from(TerminalSession).where(TerminalSession.status.in_(LIVE), TerminalSession.agent_id == agent.id),
        "admin": select(func.count()).select_from(TerminalSession).where(TerminalSession.status.in_(LIVE), TerminalSession.admin_id == admin.id),
        "total": select(func.count()).select_from(TerminalSession).where(TerminalSession.status.in_(LIVE)),
    }
    if await db.scalar(counts["node"]) >= MAX_PER_NODE:
        raise HTTPException(409, "На этом узле уже открыта сессия")
    if await db.scalar(counts["admin"]) >= MAX_PER_ADMIN:
        raise HTTPException(409, f"У вас уже открыто {MAX_PER_ADMIN} сессии")
    if await db.scalar(counts["total"]) >= MAX_TOTAL:
        raise HTTPException(409, f"Открыто максимальное число сессий ({MAX_TOTAL})")
    session = TerminalSession(
        id=str(uuid.uuid4()), agent_id=agent.id, agent_name=agent.name, admin_id=admin.id, admin_email=admin.email,
        reason=body.reason.strip(), status="requested", cols=body.cols, rows=body.rows, created_at=now,
        expires_at=now + timedelta(minutes=max_minutes()), client_ip=(request.client.host if request.client else None))
    db.add(session)
    await db.flush()
    _record(db, session, "event", f"Запрошена администратором {admin.email}: {session.reason}".encode())
    from .main import audit

    await audit(db, "terminal.session.request", admin.email, session.id, {"node": agent.name, "reason": session.reason, "ip": session.client_ip})
    await db.commit()
    await relay().append(key_wake(agent.id), {"k": "wake", "sid": session.id})
    return _session_row(session)


@router.get("/api/admin/terminal/sessions/{sid}/output")
async def admin_terminal_output(sid: str, request: Request, cursor: str = Query(default="", max_length=64), wait: float = Query(default=20, ge=0, le=MAX_WAIT)):
    async with session_factory() as db:
        admin = await _admin(request, db)
        session = await _owned(db, sid, admin)
        await enforce_limits(db, session)
        await db.commit()
        status = session.status
    items, cursor = await relay().read(key_out(sid), cursor or None, wait if status != "closed" else 0)
    async with session_factory() as db:
        session = await db.get(TerminalSession, sid)
        return {"chunks": items, "cursor": cursor, "status": session.status, "close_reason": session.close_reason}


class InputIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seq: int = Field(ge=1)
    data: str | None = Field(default=None, max_length=MAX_INPUT)
    cols: int | None = Field(default=None, ge=20, le=400)
    rows: int | None = Field(default=None, ge=5, le=200)


@router.post("/api/admin/terminal/sessions/{sid}/input")
async def admin_terminal_input(sid: str, body: InputIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission(PERMISSION))):
    session = await _owned(db, sid, admin)
    await enforce_limits(db, session)
    if session.status == "closed":
        await db.commit()
        raise HTTPException(410, session.close_reason or "Сессия закрыта")
    if session.status != "active":
        await db.commit()
        raise HTTPException(409, "Узел ещё не подключился")
    if body.seq <= session.input_seq:
        await db.commit()  # releases the row lock
        return {"ok": True, "duplicate": True}
    session.input_seq = body.seq
    if body.cols and body.rows:
        session.cols, session.rows = body.cols, body.rows
        await relay().append(key_in(sid), {"k": "resize", "cols": body.cols, "rows": body.rows, "s": body.seq})
    if body.data:
        data = body.data.encode()
        session.last_activity_at = utcnow()
        if session.echo_off:
            _record(db, session, "hidden", f"[скрытый ввод: {len(data)} байт]".encode())
        else:
            _record(db, session, "in", data)
        await relay().append(key_in(sid), {"k": "data", "d": base64.b64encode(data).decode(), "s": body.seq})
    if session.bytes_in + session.bytes_out > TRANSCRIPT_LIMIT:
        await close(db, session, "Достигнут лимит журнала сессии (8 МБ)")
    await db.commit()
    return {"ok": True}


@router.post("/api/admin/terminal/sessions/{sid}/close")
async def admin_terminal_close(sid: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission(PERMISSION))):
    session = await db.get(TerminalSession, sid, with_for_update=True, populate_existing=True)
    if session is None:
        raise HTTPException(404, "Сессия не найдена")
    if session.admin_id != admin.id and "security.manage" not in PERMISSIONS.get(admin.role, set()):
        raise HTTPException(403, "Закрыть чужую сессию может администратор с правом управления безопасностью")
    await close(db, session, "Закрыта администратором" if session.admin_id == admin.id else f"Закрыта администратором {admin.email}", admin.email)
    await db.commit()
    return _session_row(session)


@router.get("/api/admin/terminal/sessions/{sid}/transcript")
async def admin_terminal_transcript(sid: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission(PERMISSION))):
    if "security.manage" not in PERMISSIONS.get(admin.role, set()):
        raise HTTPException(403, "Журнал сессий доступен администратору с правом управления безопасностью")
    session = await db.get(TerminalSession, sid)
    if session is None:
        raise HTTPException(404, "Сессия не найдена")
    chunks = (await db.scalars(select(TerminalChunk).where(TerminalChunk.session_id == sid).order_by(TerminalChunk.id).limit(5000))).all()
    out = []
    for chunk in chunks:
        try:
            text = base64.b64decode(decrypt_secret(chunk.data_encrypted)).decode("utf-8", "replace")
        except Exception:
            text = "[фрагмент не расшифровывается]"
        out.append({"direction": chunk.direction, "at": chunk.created_at.isoformat(), "size": chunk.size, "text": text})
    from .main import audit

    await audit(db, "terminal.transcript.view", admin.email, sid, {"node": session.agent_name})
    await db.commit()
    return {**_session_row(session), "chunks": out}


class SnippetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    command: str = Field(min_length=1, max_length=2000)


@router.post("/api/admin/terminal/snippets")
async def admin_snippet_create(body: SnippetIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission(PERMISSION))):
    snippet = TerminalSnippet(name=body.name.strip(), command=body.command, created_by=admin.email, created_at=utcnow())
    db.add(snippet)
    await db.flush()
    from .main import audit

    await audit(db, "terminal.snippet.create", admin.email, str(snippet.id), {"name": snippet.name})
    await db.commit()
    return {"id": snippet.id, "name": snippet.name, "command": snippet.command}


@router.post("/api/admin/terminal/snippets/{snippet_id}/delete")
async def admin_snippet_delete(snippet_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission(PERMISSION))):
    snippet = await db.get(TerminalSnippet, snippet_id)
    if snippet is None:
        raise HTTPException(404, "Сниппет не найден")
    await db.delete(snippet)
    from .main import audit

    await audit(db, "terminal.snippet.delete", admin.email, str(snippet_id), {"name": snippet.name})
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- agent API

async def _agent(db: AsyncSession, token: str) -> NodeAgent:
    from .platform_api import _agent as agent_by_token, _require_plugin

    await _require_plugin(db, "agent")
    return await agent_by_token(db, token)


async def _agent_session(db: AsyncSession, sid: str, agent: NodeAgent, key: str) -> TerminalSession:
    session = await db.get(TerminalSession, sid, with_for_update=True, populate_existing=True)
    if session is None or session.agent_id != agent.id:
        raise HTTPException(404, "Сессия не найдена")
    if session.status == "closed" or not session.agent_key_hash or not hmac.compare_digest(session.agent_key_hash, _hash(key or "")):
        raise HTTPException(410, session.close_reason or "Сессия закрыта")
    return session


@router.get("/api/agent/terminal/pending")
async def agent_terminal_pending(wait: float = Query(default=20, ge=0, le=MAX_WAIT), x_agent_token: str = Header(default="")):
    """Long poll: returns a session requested for this node and claims it, or nothing."""
    for attempt in (0, 1):
        async with session_factory() as db:
            agent = await _agent(db, x_agent_token)
            agent_id = agent.id
            if not settings.terminal_enabled:
                await db.commit()
                return {"session": None, "enabled": False}
            wake_cursor = await relay().last(key_wake(agent_id))
            pending = (await db.scalars(select(TerminalSession).where(TerminalSession.agent_id == agent_id, TerminalSession.status == "requested").order_by(TerminalSession.created_at))).all()
            for session in pending:
                await enforce_limits(db, session)
                if session.status != "requested":
                    continue
                key = secrets.token_urlsafe(32)
                now = utcnow()
                claimed = await db.execute(update(TerminalSession).where(TerminalSession.id == session.id, TerminalSession.status == "requested").values(
                    status="active", claimed_at=now, last_activity_at=now, agent_key_hash=_hash(key)))
                if claimed.rowcount != 1:
                    continue
                db.add(TerminalChunk(session_id=session.id, direction="event", size=0,
                                     data_encrypted=encrypt_secret(base64.b64encode("Узел подключился".encode()).decode()), created_at=now))
                await db.commit()
                await relay().append(key_out(session.id), {"k": "opened"})
                return {"session": {"id": session.id, "key": key, "cols": session.cols, "rows": session.rows,
                                    "max_seconds": max(1, int((session.expires_at - now).total_seconds())), "idle_seconds": idle_minutes() * 60}}
            await db.commit()
        if attempt == 0 and wait > 0:
            await relay().read(key_wake(agent_id), wake_cursor, wait)
    return {"session": None, "enabled": True}


class OutputIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seq: int = Field(ge=1)
    data: str = Field(default="", max_length=MAX_OUTPUT * 4 // 3 + 8)
    echo: bool | None = None
    exited: bool = False
    exit_code: int | None = None


@router.post("/api/agent/terminal/{sid}/output")
async def agent_terminal_output(sid: str, body: OutputIn, x_agent_token: str = Header(default=""), x_terminal_key: str = Header(default="")):
    async with session_factory() as db:
        agent = await _agent(db, x_agent_token)
        session = await _agent_session(db, sid, agent, x_terminal_key)
        if body.seq <= session.output_seq:
            await db.commit()
            return {"ok": True, "duplicate": True}
        session.output_seq = body.seq
        if body.echo is not None:
            session.echo_off = not body.echo
        if body.data:
            try:
                data = base64.b64decode(body.data, validate=True)
            except ValueError:
                raise HTTPException(422, "Неверный base64")
            if len(data) > MAX_OUTPUT:
                raise HTTPException(413, "Фрагмент вывода больше 64 КБ")
            _record(db, session, "out", data)
            await relay().append(key_out(sid), {"k": "data", "d": base64.b64encode(data).decode()})
        if body.exited:
            session.exit_code = body.exit_code
            await close(db, session, f"Оболочка завершилась (код {body.exit_code})" if body.exit_code is not None else "Оболочка завершилась", "agent")
        elif session.bytes_in + session.bytes_out > TRANSCRIPT_LIMIT:
            await close(db, session, "Достигнут лимит журнала сессии (8 МБ)")
        else:
            await enforce_limits(db, session)
        await db.commit()
        return {"ok": True, "status": session.status}


@router.get("/api/agent/terminal/{sid}/input")
async def agent_terminal_input(sid: str, cursor: str = Query(default="", max_length=64), wait: float = Query(default=20, ge=0, le=MAX_WAIT),
                               x_agent_token: str = Header(default=""), x_terminal_key: str = Header(default="")):
    async with session_factory() as db:
        agent = await _agent(db, x_agent_token)
        session = await _agent_session(db, sid, agent, x_terminal_key)
        await enforce_limits(db, session)
        await db.commit()
        if session.status == "closed":
            return {"items": [{"k": "close", "reason": session.close_reason}], "cursor": cursor}
    items, cursor = await relay().read(key_in(sid), cursor or None, wait)
    return {"items": items, "cursor": cursor}


# ---------------------------------------------------------------- maintenance

async def maintain(db: AsyncSession, now: datetime | None = None) -> dict:
    now = now or utcnow()
    closed = 0
    for session in (await db.scalars(select(TerminalSession).where(TerminalSession.status.in_(LIVE)))).all():
        await enforce_limits(db, session, now)
        closed += session.status == "closed"
    cutoff = now - timedelta(days=max(1, int(settings.terminal_transcript_days or 90)))
    old = (await db.scalars(select(TerminalSession.id).where(TerminalSession.status == "closed", TerminalSession.closed_at < cutoff))).all()
    if old:
        await db.execute(delete(TerminalChunk).where(TerminalChunk.session_id.in_(old)))
        await db.execute(delete(TerminalSession).where(TerminalSession.id.in_(old)))
        await relay().drop(*[k for sid in old for k in (key_in(sid), key_out(sid))])
    await db.commit()
    return {"closed": closed, "deleted": len(old)}


async def terminal_scheduler():
    while True:
        try:
            async with session_factory() as db:
                await maintain(db)
        except Exception as exc:
            logger.warning("Terminal maintenance failed: %s", type(exc).__name__)
        await asyncio.sleep(60)
