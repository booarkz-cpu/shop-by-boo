"""Admin API of the Remnawave installation wizard (v28.66, stage 10; docs/ru/new/REMNAWAVE_INSTALLATION_WIZARD.md).

Typed routes only: the browser chooses servers of the registry, a mode and typed parameters; the commands that run
on the servers are fixed scripts of rw_steps. Reading needs ``read``; everything that touches a server or its
credentials needs ``provision_nodes``; connecting the shop to a new panel also needs ``settings.runtime.write``
and goes through the staged runtime settings (stage → apply, with the fingerprint)."""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import rw_jobs, rw_plan, rw_steps
from .db import get_db
from .models import AuditLog, RemnawaveDeploymentStep, RemnawaveInstallation, RemnawaveServer
from .rw_remote import RemoteError, load_private_key, scan_fingerprint
from .security import encrypt_secret, require_permission

router = APIRouter(prefix="/api/admin/rw", tags=["remnawave-installer"])
FINGERPRINT = r"^SHA256:[A-Za-z0-9+/]{43}$"
HOSTNAME = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?:\.(?!-)[A-Za-z0-9-]{1,63})*$")
ACTIVE = ("queued", "running")
CONNECT = None  # tests: fake SSH factory for the server check


def _host(value: str) -> str:
    value = value.strip()
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        if not HOSTNAME.match(value):
            raise ValueError("Укажите IP-адрес или имя хоста")
        return value.lower()
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
        raise ValueError("Этот адрес нельзя использовать для сервера")
    return str(ip)


class ScanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(max_length=253)
    ssh_port: int = Field(default=22, ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def host_ok(cls, value: str) -> str:
        return _host(value)


class ServerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-zА-Яа-яЁё0-9 ._-]+$")
    host: str = Field(max_length=253)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str = Field(default="root", min_length=1, max_length=32, pattern=r"^[a-z_][a-z0-9_-]*$")
    auth_method: Literal["key", "password"]
    private_key: str | None = Field(default=None, max_length=16000)
    password: str | None = Field(default=None, min_length=1, max_length=256)
    host_key_fingerprint: str = Field(pattern=FINGERPRINT)
    purpose: list[Literal["panel", "node", "subscription_page"]] = Field(default_factory=list, max_length=3)

    @field_validator("host")
    @classmethod
    def host_ok(cls, value: str) -> str:
        return _host(value)

    @model_validator(mode="after")
    def check(self):
        if self.auth_method == "key":
            if not self.private_key:
                raise ValueError("Вставьте закрытый ключ SSH")
            try:
                load_private_key(self.private_key)
            except RemoteError as exc:
                raise ValueError(str(exc)) from exc
        elif not self.password:
            raise ValueError("Укажите пароль SSH")
        return self


class ServerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[A-Za-zА-Яа-яЁё0-9 ._-]+$")
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    ssh_user: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[a-z_][a-z0-9_-]*$")
    auth_method: Literal["key", "password"] | None = None
    private_key: str | None = Field(default=None, max_length=16000)
    password: str | None = Field(default=None, min_length=1, max_length=256)
    host_key_fingerprint: str | None = Field(default=None, pattern=FINGERPRINT)
    purpose: list[Literal["panel", "node", "subscription_page"]] | None = Field(default=None, max_length=3)


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["update", "diagnose", "restore", "reinstall", "remove"]
    # v28.67.0: with «update» — close or open the panel's pages (secret access link).
    panel_access: Literal["open", "cookie"] | None = None


def server_out(row: RemnawaveServer) -> dict:
    preflight = row.preflight or {}
    return {"id": row.id, "name": row.name, "host": row.host, "ssh_port": row.ssh_port, "ssh_user": row.ssh_user,
            "auth_method": row.auth_method, "has_secret": bool(row.ssh_secret), "host_key_fingerprint": row.host_key_fingerprint,
            "purpose": (preflight.get("purpose") if isinstance(preflight, dict) else None) or [],
            "roles": row.roles or [], "status": row.status, "os": row.os, "arch": row.arch, "cpu_cores": row.cpu_cores,
            "ram_mb": row.ram_mb, "disk_gb": row.disk_gb, "checks": preflight.get("checks", []),
            "check_ok": preflight.get("ok"), "last_checked_at": row.last_checked_at.isoformat() + "Z" if row.last_checked_at else None}


def _iso(value):
    return value.isoformat() + "Z" if value else None


def installation_out(row: RemnawaveInstallation, steps: list[RemnawaveDeploymentStep] | None = None) -> dict:
    result = dict(row.result or {})
    result.pop("state", None)
    out = {"id": row.id, "action": row.action, "mode": row.mode, "title": (row.plan or {}).get("title"), "server_ids": row.server_ids,
           "params": row.params, "plan": row.plan, "plan_sha256": row.plan_sha256, "status": row.status, "error": row.error,
           "result": result, "created_by": row.created_by, "approved_by": row.approved_by, "cancel_requested": row.cancel_requested,
           "source_installation_id": row.source_installation_id, "created_at": _iso(row.created_at),
           "started_at": _iso(row.started_at), "finished_at": _iso(row.finished_at), "has_secrets": bool(row.secrets)}
    if steps is not None:
        total = len(steps) or 1
        finished = sum(1 for s in steps if s.status in ("done", "rolled_back", "skipped"))
        out["progress"] = round(100 * finished / total)
        out["steps"] = [{"id": s.id, "position": s.position, "kind": s.kind, "title": s.title, "server_id": s.server_id,
                         "status": s.status, "log": s.log_tail, "started_at": _iso(s.started_at), "finished_at": _iso(s.finished_at)}
                        for s in steps]
    return out


async def _audit(db: AsyncSession, action: str, actor: str, target: str, details: dict) -> None:
    db.add(AuditLog(action=action, actor=actor, target=target, details=json.dumps(details, ensure_ascii=False)))


async def _server(db: AsyncSession, server_id: int, lock: bool = False) -> RemnawaveServer:
    row = await db.get(RemnawaveServer, server_id, with_for_update=lock)
    if not row:
        raise HTTPException(404, "Сервер не найден")
    return row


async def _busy(db: AsyncSession, server_ids: list[int], exclude: int | None = None) -> list[int]:
    rows = (await db.execute(select(RemnawaveInstallation).where(RemnawaveInstallation.status.in_(ACTIVE)))).scalars().all()
    return sorted({sid for r in rows if r.id != exclude for sid in r.server_ids if sid in server_ids})


# ---------- meta ----------

@router.get("/meta")
async def meta(admin=Depends(require_permission("read"))):
    return {"modes": [{"key": m, "title": rw_plan.MODE_TITLES[m]} for m in rw_plan.MODES],
            "actions": [{"key": a, "title": rw_plan.ACTION_TITLES[a]} for a in rw_plan.ACTIONS],
            "images": rw_plan.IMAGES, "step_kinds": list(rw_steps.STEP_KINDS), "dirs": rw_plan.DIRS,
            "supported_os": sorted(f"{a} {b}" for a, b in rw_steps.SUPPORTED_OS)}


# ---------- servers ----------

@router.get("/servers")
async def list_servers(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    rows = (await db.execute(select(RemnawaveServer).order_by(RemnawaveServer.id))).scalars().all()
    return {"servers": [server_out(r) for r in rows]}


@router.post("/servers/scan")
async def scan(payload: ScanIn, admin=Depends(require_permission("provision_nodes"))):
    """The host key fingerprint, to compare with the one the hosting shows (or ``ssh-keygen -lf``) before saving."""
    try:
        return await asyncio.to_thread(scan_fingerprint, payload.host, payload.ssh_port)
    except RemoteError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/servers")
async def create_server(payload: ServerIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    if await db.scalar(select(RemnawaveServer.id).where(RemnawaveServer.name == payload.name)):
        raise HTTPException(409, "Сервер с таким названием уже есть")
    secret = payload.private_key if payload.auth_method == "key" else payload.password
    row = RemnawaveServer(name=payload.name, host=payload.host, ssh_port=payload.ssh_port, ssh_user=payload.ssh_user,
                          auth_method=payload.auth_method, ssh_secret=encrypt_secret(secret), host_key_fingerprint=payload.host_key_fingerprint,
                          roles=[], status="new", preflight={"purpose": payload.purpose})
    db.add(row)
    await db.flush()
    await _audit(db, "rw.server.created", admin.email, str(row.id), {"host": row.host, "ssh_port": row.ssh_port, "auth": row.auth_method})
    await db.commit()
    return server_out(row)


@router.patch("/servers/{server_id}")
async def patch_server(server_id: int, payload: ServerPatch, db: AsyncSession = Depends(get_db),
                       admin=Depends(require_permission("provision_nodes"))):
    row = await _server(db, server_id, lock=True)
    if await _busy(db, [server_id]):
        raise HTTPException(409, "На сервере идёт установка")
    changed = []
    for field in ("name", "ssh_port", "ssh_user", "host_key_fingerprint"):
        value = getattr(payload, field)
        if value is not None and value != getattr(row, field):
            setattr(row, field, value); changed.append(field)
    method = payload.auth_method or row.auth_method
    secret = payload.private_key if method == "key" else payload.password
    if payload.auth_method and payload.auth_method != row.auth_method and not secret:
        raise HTTPException(422, "При смене способа входа нужен новый ключ или пароль")
    if secret:
        if method == "key":
            try:
                load_private_key(secret)
            except RemoteError as exc:
                raise HTTPException(422, str(exc)) from exc
        row.auth_method = method; row.ssh_secret = encrypt_secret(secret); changed.append("credentials")
    if payload.purpose is not None:
        row.preflight = {**(row.preflight or {}), "purpose": payload.purpose}; changed.append("purpose")
    if {"ssh_port", "ssh_user", "host_key_fingerprint", "credentials"} & set(changed):
        row.status = "new" if not row.roles else row.status
    row.updated_at = datetime.utcnow()
    await _audit(db, "rw.server.updated", admin.email, str(row.id), {"fields": changed})
    await db.commit()
    return server_out(row)


@router.delete("/servers/{server_id}")
async def delete_server(server_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    row = await _server(db, server_id, lock=True)
    if row.roles:
        raise HTTPException(409, "На сервере установлены компоненты Remnawave: сначала выполните «Удаление» в мастере")
    if await _busy(db, [server_id]):
        raise HTTPException(409, "На сервере идёт установка")
    await _audit(db, "rw.server.deleted", admin.email, str(row.id), {"host": row.host})
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


@router.post("/servers/{server_id}/check")
async def check_server(server_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """SSH with the pinned host key, then the read-only preflight (nothing changes on the server)."""
    row = await _server(db, server_id)
    purpose = (row.preflight or {}).get("purpose") or ["node"]
    ctx = rw_steps.Context(plan=rw_plan.PlanIn(mode="node", node_server_ids=[row.id], tls="internal"),
                           servers={row.id: rw_jobs.server_dict(row)}, secrets={}, state={}, connect=CONNECT)
    try:
        out = await rw_steps.preflight(ctx, row.id, purpose, [], 2222 if "node" in purpose else None)
    except rw_steps.StepError as exc:
        row.status = "unreachable"; row.last_checked_at = datetime.utcnow()
        row.preflight = {**(row.preflight or {}), "ok": False, "checks": [{"key": "ssh", "status": "error", "detail": str(exc)}]}
        await db.commit()
        raise HTTPException(422, str(exc)) from exc
    out["checks"].insert(0, {"key": "ssh", "status": "ok", "detail": f"SSH {row.ssh_user}@{row.host}:{row.ssh_port}, ключ сервера совпал"})
    out["purpose"] = purpose
    await rw_jobs._remember_facts(db, row.id, out)
    if row.status in ("new", "unreachable"):
        row.status = "ready" if out["ok"] else "check_failed"
    await db.commit()
    return server_out(row)


# ---------- installations ----------

async def _servers_for(db: AsyncSession, ids: list[int]) -> dict[int, dict]:
    rows = (await db.execute(select(RemnawaveServer).where(RemnawaveServer.id.in_(ids)))).scalars().all()
    return {r.id: {"name": r.name, "host": r.host, "status": r.status} for r in rows}


def _shop_panel() -> str | None:
    from .config import settings
    return (settings.remnawave_url or "").rstrip("/") if settings.remnawave_url and settings.remnawave_token else None


async def _steps(db: AsyncSession, installation_id: int) -> list[RemnawaveDeploymentStep]:
    return (await db.execute(select(RemnawaveDeploymentStep).where(RemnawaveDeploymentStep.installation_id == installation_id)
                             .order_by(RemnawaveDeploymentStep.position))).scalars().all()


async def _installation(db: AsyncSession, installation_id: int, lock: bool = False) -> RemnawaveInstallation:
    row = await db.get(RemnawaveInstallation, installation_id, with_for_update=lock)
    if not row:
        raise HTTPException(404, "Установка не найдена")
    return row


@router.get("/installations")
async def list_installations(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    rows = (await db.execute(select(RemnawaveInstallation).order_by(RemnawaveInstallation.id.desc()).limit(100))).scalars().all()
    out = []
    for row in rows:
        item = installation_out(row, await _steps(db, row.id))
        item.pop("plan"); item.pop("params")
        for st in item.pop("steps"):
            if st["status"] == "running":
                item["current_step"] = st["title"]
        out.append(item)
    return {"installations": out}


@router.get("/installations/{installation_id}")
async def get_installation(installation_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    row = await _installation(db, installation_id)
    return installation_out(row, await _steps(db, row.id))


@router.post("/installations/plan")
async def plan_installation(payload: rw_plan.PlanIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """The plan to review: steps, what changes on each server, pinned images. Nothing runs until it is approved."""
    ids = sorted(rw_plan.roles_of(payload))
    servers = await _servers_for(db, ids)
    unchecked = [servers[i]["name"] for i in ids if i in servers and servers[i]["status"] in ("new", "unreachable")]
    if unchecked:
        raise HTTPException(422, "Сначала проверьте серверы («Проверить»): " + ", ".join(unchecked))
    try:
        plan = rw_plan.build_plan(payload, servers, _shop_panel())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    params = payload.model_dump()
    row = RemnawaveInstallation(action="install", mode=payload.mode, server_ids=ids, params=params, plan=plan,
                                plan_sha256=rw_plan.plan_hash(plan, params), status="planned", created_by=admin.email)
    db.add(row)
    await db.flush()
    await _audit(db, "rw.installation.planned", admin.email, str(row.id), {"mode": payload.mode, "servers": ids})
    await db.commit()
    return installation_out(row, [])


@router.post("/installations/{installation_id}/approve")
async def approve(installation_id: int, payload: ApproveIn, db: AsyncSession = Depends(get_db),
                  admin=Depends(require_permission("provision_nodes"))):
    row = await _installation(db, installation_id, lock=True)
    if row.status != "planned":
        raise HTTPException(409, "План уже запущен или отменён")
    if not hmac.compare_digest(payload.plan_sha256, row.plan_sha256):
        raise HTTPException(409, "План изменился: просмотрите его заново")
    servers = await _servers_for(db, row.server_ids)
    try:
        params = rw_plan.PlanIn(**row.params)
        fresh = (rw_plan.build_plan(params, servers, _shop_panel()) if row.action == "install"
                 else rw_plan.build_action(row.action, params, servers))
    except ValueError as exc:
        raise HTTPException(409, f"План больше не выполним: {exc}") from exc
    if rw_plan.plan_hash(fresh, row.params) != row.plan_sha256:
        raise HTTPException(409, "Серверы или подключение магазина изменились после составления плана: составьте план заново")
    busy = await _busy(db, row.server_ids, exclude=row.id)
    if busy:
        raise HTTPException(409, f"На серверах {busy} уже идёт другая установка")
    if row.action == "install":
        rw_jobs.store_secrets(row, rw_steps.new_secrets())
    for st in row.plan["steps"]:
        db.add(RemnawaveDeploymentStep(installation_id=row.id, server_id=st["server_id"], position=st["position"], kind=st["kind"],
                                       title=st["title"][:200], params=st["params"], status="pending"))
    row.status = "queued"; row.approved_by = admin.email
    await _audit(db, "rw.installation.approved", admin.email, str(row.id), {"action": row.action, "plan_sha256": row.plan_sha256})
    await db.commit()
    return installation_out(row, await _steps(db, row.id))


@router.post("/installations/{installation_id}/cancel")
async def cancel(installation_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    row = await _installation(db, installation_id, lock=True)
    if row.status in ("planned", "queued"):
        row.status = "cancelled"; row.finished_at = datetime.utcnow()
        for st in await _steps(db, row.id):
            st.status = "skipped"
    elif row.status == "running":
        row.cancel_requested = True  # the runner stops before the next step and undoes what was done
    else:
        raise HTTPException(409, "Установка уже завершена")
    await _audit(db, "rw.installation.cancelled", admin.email, str(row.id), {"status": row.status})
    await db.commit()
    return installation_out(row, await _steps(db, row.id))


@router.post("/installations/{installation_id}/actions")
async def action(installation_id: int, payload: ActionIn, db: AsyncSession = Depends(get_db),
                 admin=Depends(require_permission("provision_nodes"))):
    """A plan of update / diagnose / restore / reinstall / remove over what a successful installation put in place.
    It is approved like an installation; secrets and node records are carried over."""
    source = await _installation(db, installation_id)
    if source.action != "install" or source.status != "succeeded":
        raise HTTPException(409, "Действие доступно для успешно завершённой установки")
    servers = await _servers_for(db, source.server_ids)
    params = dict(source.params)
    if payload.panel_access:
        if payload.action != "update" or not params.get("panel_server_id"):
            raise HTTPException(422, "Доступ к панели меняется действием «Обновить» установки с панелью")
        params["panel_access"] = payload.panel_access
    try:
        plan = rw_plan.build_action(payload.action, rw_plan.PlanIn(**params), servers)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = RemnawaveInstallation(action=payload.action, mode=source.mode, server_ids=source.server_ids, params=params,
                                plan=plan, plan_sha256=rw_plan.plan_hash(plan, params), status="planned",
                                secrets=source.secrets, result={"state": (source.result or {}).get("state") or {}},
                                source_installation_id=source.id, created_by=admin.email)
    db.add(row)
    await db.flush()
    await _audit(db, "rw.installation.planned", admin.email, str(row.id), {"action": payload.action, "source": source.id})
    await db.commit()
    return installation_out(row, [])


@router.post("/installations/{installation_id}/credentials")
async def credentials(installation_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """The panel administrator's login, shown on request and written to the audit log (the API token never is)."""
    row = await _installation(db, installation_id)
    if row.action != "install" or not row.secrets or not (row.params or {}).get("panel_server_id"):
        raise HTTPException(404, "Эта установка не создавала администратора панели")
    secrets = rw_jobs.load_secrets(row)
    if "panel_token" not in secrets:
        raise HTTPException(409, "Администратор панели ещё не создан")
    await _audit(db, "rw.installation.credentials_viewed", admin.email, str(row.id), {})
    await db.commit()
    out = {"panel_url": f"https://{row.params['panel_domain']}", "username": secrets["panel_admin_username"],
           "password": secrets["panel_admin_password"], "access_url": None}
    if row.params.get("panel_access") == "cookie" and secrets.get("panel_cookie_name"):
        out["access_url"] = f"https://{row.params['panel_domain']}/?{secrets['panel_cookie_name']}={secrets['panel_cookie_value']}"
    return out


@router.post("/installations/{installation_id}/connect-shop")
async def connect_shop(installation_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes")),
                       writer=Depends(require_permission("settings.runtime.write"))):
    """Stage REMNAWAVE_URL and REMNAWAVE_TOKEN of the new panel; the administrator applies the change in the same
    two-step flow as any runtime setting (the response carries the change and its fingerprint)."""
    from .runtime_settings import StageSettingsIn, _state, stage_change
    row = await _installation(db, installation_id)
    if row.action != "install" or row.status != "succeeded" or not (row.params or {}).get("panel_server_id"):
        raise HTTPException(409, "Подключить можно панель, установленную мастером и прошедшую проверку")
    if row.params.get("tls") != "acme":
        raise HTTPException(409, "У панели внутренний сертификат: магазин не сможет его проверить. Переустановите с Let's Encrypt")
    token = rw_jobs.load_secrets(row).get("panel_token")
    if not token:
        raise HTTPException(409, "Нет токена API панели")
    state = await _state(db)
    staged = await stage_change(StageSettingsIn(base_version=state.version, changes={
        "remnawave_url": f"https://{row.params['panel_domain']}", "remnawave_token": token},
        reason=f"Мастер Remnawave: панель установки #{row.id}"), db, admin.email)
    return staged
