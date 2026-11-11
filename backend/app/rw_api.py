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
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import rw_jobs, rw_plan, rw_steps
from .db import get_db
from .models import AuditLog, RemnawaveDeploymentStep, RemnawaveInstallation, RemnawaveServer
from .rw_remote import RemoteError, load_private_key, scan_fingerprint
from .rw_ssh import key_state
from .security import encrypt_secret, require_permission, require_stepup

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


class ModuleIn(BaseModel):
    """v28.70.0: a node module for the servers of an installation (docs/ru/new/REMNAWAVE_EXTENSIONS.md)."""
    model_config = ConfigDict(extra="forbid")
    name: Literal["ipv6", "xray_core", "warp", "netbird", "xray_checker", "transports", "hardening", "watchdog", "selfsteal_site", "node_port",
                  "mss_clamp", "node_guard", "swap", "sni_scan", "mtproto", "geo_files", "cdn", "psiphon", "crowdsec"]
    # v28.98.0 (N7): Cloudflare CDN — what goes behind it, the CDN domain of the nodes, the owner's API token.
    cdn_nodes: bool = False
    cdn_subscription: bool = False
    cdn_domain: str | None = Field(default=None, max_length=253)
    cloudflare_token: SecretStr | None = Field(default=None, max_length=200)
    psiphon_port: int | None = Field(default=None, ge=1024, le=65535)           # v28.99.0 (N7)
    psiphon_protocol: Literal["OSSH", "TLS-OSSH"] | None = None
    mtproto_port: int | None = Field(default=None, ge=1024, le=65535)          # v28.94.0 (N7)
    mtproto_domain: str | None = Field(default=None, max_length=100)
    guard_ports: list[int] | None = Field(default=None, max_length=12)          # v28.92.0 (N7)
    guard_rate: int | None = Field(default=None, ge=5, le=5000)
    guard_allow: list[str] | None = Field(default=None, max_length=10)
    guard_mode: Literal["enforce", "observe"] | None = None
    swap_mb: int | None = Field(default=None, ge=256, le=16384)
    crowdsec_community: bool | None = None                                      # v28.114.0
    crowdsec_action: Literal["install", "status", "unban"] | None = None        # v28.115.0
    crowdsec_ip: str | None = Field(default=None, max_length=45)
    enabled: bool = True
    server_ids: list[int] = Field(default_factory=list, max_length=20)
    selfsteal_template: str | None = Field(default=None, max_length=40)         # v28.88.0; v28.91.0 — the catalogue or «custom»
    selfsteal_lang: Literal["ru", "en"] | None = None                           # v28.91.0
    selfsteal_upload: str | None = Field(default=None, pattern=r"^[a-f0-9]{16}$")  # v28.91.0: an uploaded site
    hardening: rw_plan.Hardening | None = None                                  # v28.84.0
    transports: list[rw_plan.TransportName] = Field(default_factory=list, max_length=5)  # v28.81.0
    fingerprint: rw_plan.Fingerprint | None = None                             # v28.90.0 (N5), with «transports»
    tls_min: rw_plan.TlsVersion | None = None                                   # v28.90.0 (N6), with «transports»
    tls_max: rw_plan.TlsVersion | None = None
    node_port_ips: list[str] | None = Field(default=None, max_length=10)       # v28.90.0 (N5), with «node_port»
    version: str | None = Field(default=None, pattern=r"^(latest|v\d{1,3}\.\d{1,3}\.\d{1,3})$")  # Xray core
    accept_warp_tos: bool = False
    setup_key: SecretStr | None = Field(default=None, max_length=200)          # NetBird
    management_url: str | None = Field(default=None, max_length=200)           # NetBird, self-hosted
    subscription_url: SecretStr | None = Field(default=None, max_length=2000)  # Xray Checker
    interval: int = Field(default=300, ge=60, le=86400)                        # Xray Checker


class ActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["update", "diagnose", "restore", "reinstall", "remove", "module", "start", "stop", "restart", "logs",
                    "snapshot", "remove_component", "restore_files", "change_domain"]
    # v28.97.0 (N7): with «change_domain» — the panel's new domain, and whether the former one keeps serving subscriptions.
    new_panel_domain: str | None = Field(default=None, max_length=253)
    keep_old_domain: bool = True
    # v28.93.0 (N7): with «restore_files» — the snapshot of the files («Установка → Снапшоты серверов»).
    snapshot: str | None = Field(default=None, pattern=r"^config-\d{1,9}-\d{8}T\d{6}Z\.tar\.gz\.enc$")
    # v28.92.0 (N7): with «remove_component» — which component to take off the servers.
    component: Literal["panel", "subscription_page", "proxy", "node", "selfsteal", "xray_checker"] | None = None
    # v28.67.0: with «update» — close or open the panel's pages (secret access link).
    panel_access: Literal["open", "cookie", "tinyauth", "gate"] | None = None
    # v28.78.0: with panel_access="tinyauth" — the login portal's domain (a sibling of the panel's domain).
    auth_domain: str | None = Field(default=None, max_length=253)
    # v28.77.0: with «update» — the template of the Remnawave subscription page.
    subpage_template: Literal["default", "orion"] | None = None
    module: ModuleIn | None = None


def server_out(row: RemnawaveServer) -> dict:
    preflight = row.preflight or {}
    return {"id": row.id, "name": row.name, "host": row.host, "ssh_port": row.ssh_port, "ssh_user": row.ssh_user,
            "auth_method": row.auth_method, "has_secret": bool(row.ssh_secret), "host_key_fingerprint": row.host_key_fingerprint,
            "purpose": (preflight.get("purpose") if isinstance(preflight, dict) else None) or [],
            "roles": row.roles or [], "status": row.status, "os": row.os, "arch": row.arch, "cpu_cores": row.cpu_cores,
            "ram_mb": row.ram_mb, "disk_gb": row.disk_gb, "checks": preflight.get("checks", []),
            "check_ok": preflight.get("ok"), "last_checked_at": row.last_checked_at.isoformat() + "Z" if row.last_checked_at else None,
            "ssh_key": key_state(row)}


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
async def delete_server(server_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_stepup("provision_nodes"))):
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
    return {r.id: {"name": r.name, "host": r.host, "status": r.status, "arch": r.arch} for r in rows}


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


def _gate_ready(access: str | None) -> None:
    """«Вход через магазин» needs the shop's public HTTPS address: the panel's Caddy asks it about every page."""
    if access == "gate":
        from .panel_gate import shop_base
        if not shop_base().startswith("https://") or "localhost" in shop_base():
            raise HTTPException(422, "Для входа через магазин задайте публичный адрес API магазина (API_DOMAIN)")


@router.post("/installations/plan")
async def plan_installation(payload: rw_plan.PlanIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """The plan to review: steps, what changes on each server, pinned images. Nothing runs until it is approved."""
    ids = sorted(rw_plan.roles_of(payload))
    servers = await _servers_for(db, ids)
    unchecked = [servers[i]["name"] for i in ids if i in servers and servers[i]["status"] in ("new", "unreachable")]
    if unchecked:
        raise HTTPException(422, "Сначала проверьте серверы («Проверить»): " + ", ".join(unchecked))
    _gate_ready(payload.panel_access)
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
                  admin=Depends(require_stepup("provision_nodes"))):
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
        _gate_ready(payload.panel_access)
        params["panel_access"] = payload.panel_access
        if payload.panel_access == "tinyauth":
            params["auth_domain"] = payload.auth_domain or params.get("auth_domain")
    if payload.subpage_template:
        if payload.action != "update" or not params.get("subpage_server_id"):
            raise HTTPException(422, "Шаблон страницы подписки меняется действием «Обновить» установки со страницей подписки")
        params["subpage_template"] = payload.subpage_template
    params.pop("remove_component", None)
    params.pop("snapshot_file", None)
    if payload.action == "restore_files":
        if not payload.snapshot:
            raise HTTPException(422, "Выберите снапшот")
        params["snapshot_file"] = payload.snapshot
    elif payload.snapshot:
        raise HTTPException(422, "Снапшот задаётся действием «restore_files»")
    if payload.action == "change_domain":
        new = (payload.new_panel_domain or "").strip().lower().rstrip(".")
        if not rw_plan.DOMAIN.match(new):
            raise HTTPException(422, "Укажите новый домен панели")
        old = params.get("panel_domain")
        aliases = [a for a in params.get("panel_domain_aliases") or [] if a != new]
        if new == old:
            if payload.keep_old_domain or not aliases:
                raise HTTPException(422, "Это текущий домен панели")
            aliases = []  # «старые домены больше не нужны»: only the current domain stays
        elif payload.keep_old_domain:
            aliases = ([old] + [a for a in aliases if a != old])[:3]
        else:
            aliases = []
        taken = {params.get(k) for k in ("sub_domain", "node_domain", "selfsteal_domain", "auth_domain")} - {None}
        if new in taken:
            raise HTTPException(422, "Этот домен уже занят другим компонентом установки")
        params["panel_domain"], params["panel_domain_aliases"] = new, aliases
    elif payload.new_panel_domain:
        raise HTTPException(422, "Домен панели меняется действием «change_domain»")
    if payload.action == "remove_component":
        if not payload.component:
            raise HTTPException(422, "Выберите компонент")
        params["remove_component"] = payload.component
    elif payload.component:
        raise HTTPException(422, "Компонент задаётся действием «remove_component»")
    secrets = None
    if payload.action == "module":
        if not payload.module:
            raise HTTPException(422, "Выберите модуль")
        secrets = rw_jobs.load_secrets(source)
        params["module"] = await _module_params(payload.module, params, secrets)
    elif payload.module:
        raise HTTPException(422, "Модуль задаётся действием «module»")
    try:
        plan = rw_plan.build_action(payload.action, rw_plan.PlanIn(**params), servers)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(e["msg"] for e in exc.errors())) from exc
    row = RemnawaveInstallation(action=payload.action, mode=source.mode, server_ids=source.server_ids, params=params,
                                plan=plan, plan_sha256=rw_plan.plan_hash(plan, params), status="planned",
                                secrets=source.secrets, result={"state": (source.result or {}).get("state") or {}},
                                source_installation_id=source.id, created_by=admin.email)
    if secrets is not None:
        rw_jobs.store_secrets(row, secrets)
    db.add(row)
    await db.flush()
    await _audit(db, "rw.installation.planned", admin.email, str(row.id), {"action": payload.action, "source": source.id})
    await db.commit()
    return installation_out(row, [])


async def _module_params(mod: ModuleIn, params: dict, secrets: dict) -> dict:
    """What the module plan needs: release files with their SHA-256 (looked up now, so the approved plan fixes
    them), and the settings that change the files the wizard writes. Secrets go to the installation's encrypted
    secrets, never into the plan."""
    from . import rw_releases
    run = {"name": mod.name, "enabled": mod.enabled, "server_ids": mod.server_ids}
    try:
        if mod.name == "xray_core":
            if mod.enabled:
                version, release = await rw_releases.xray_core(None if mod.version in (None, "latest") else mod.version)
                run.update(version=version, release=release)
            params["xray_core"] = run.get("version")
        elif mod.name == "geo_files":  # v28.95.0 (N7)
            if mod.enabled:
                version, release = await rw_releases.geo_lists()
                run.update(version=version, release=release)
            params["geo_files"] = run.get("version")
        elif mod.name == "warp" and mod.enabled:
            if not mod.accept_warp_tos:
                raise HTTPException(422, "Подтвердите условия Cloudflare WARP: wgcf регистрирует учётную запись WARP")
            version, release = await rw_releases.wgcf()
            run.update(version=version, release=release)
    except rw_releases.ReleaseError as exc:
        raise HTTPException(502, str(exc)) from exc
    if mod.name == "netbird":
        if mod.enabled:
            key = mod.setup_key.get_secret_value().strip() if mod.setup_key else ""
            if not re.fullmatch(r"[A-Za-z0-9-]{8,200}", key):
                raise HTTPException(422, "Ключ установки NetBird (Setup key) из консоли NetBird")
            secrets["netbird_setup_key"] = key
        run["management_url"] = mod.management_url or None
    if mod.name == "hardening":
        run["hardening"] = (mod.hardening or rw_plan.Hardening()).model_dump()
    for key in ("guard_ports", "guard_rate", "guard_allow", "guard_mode", "swap_mb", "mtproto_port", "mtproto_domain", "psiphon_port", "psiphon_protocol",
                "crowdsec_community", "crowdsec_action", "crowdsec_ip"):
        if getattr(mod, key) is not None:
            run[key] = getattr(mod, key)
    if mod.name == "cdn":
        await _cdn_params(mod, params, secrets, run)
    if mod.name == "transports":
        # The chosen set replaces the current one; an empty set leaves only VLESS + TCP + REALITY.
        # v28.98.0: «cdn» is switched by the module «cdn» (it needs the token and the DNS), so it stays as it was here.
        keep_cdn = ["cdn"] if "cdn" in (params.get("transports") or []) else []
        params["transports"] = sorted((set(mod.transports) - {"cdn"}) | set(keep_cdn)) if mod.enabled else keep_cdn
        run["transports"] = params["transports"]
        for key in ("fingerprint", "tls_min", "tls_max"):
            if getattr(mod, key) is not None:
                params[key] = getattr(mod, key)
    if mod.name == "node_port":
        if mod.node_port_ips is not None:
            params["node_port_ips"] = mod.node_port_ips  # PlanIn checks the addresses
        run["server_ids"] = mod.server_ids
    if mod.name == "selfsteal_site":
        if not params.get("selfsteal_domain"):
            raise HTTPException(422, "У этой установки нет SelfSteal")
        if not mod.selfsteal_template:
            raise HTTPException(422, "Выберите сайт-шаблон")
        params["selfsteal_template"] = mod.selfsteal_template  # the plan writes the site from the installation's settings
        params["selfsteal_upload"] = mod.selfsteal_upload if mod.selfsteal_template == "custom" else None
        if mod.selfsteal_lang:
            params["selfsteal_lang"] = mod.selfsteal_lang
        if mod.selfsteal_template == "custom":
            from .rw_selfsteal import upload_path
            if not mod.selfsteal_upload or not upload_path(mod.selfsteal_upload).is_file():
                raise HTTPException(422, "Свой сайт не найден: загрузите архив в «SelfSteal → Свой сайт»")
    if mod.name == "xray_checker":
        if mod.enabled:
            url = mod.subscription_url.get_secret_value().strip() if mod.subscription_url else secrets.get("checker_subscription_url", "")
            if not re.fullmatch(r"https://[^\s\"'$`\\]{8,2000}", url or ""):
                raise HTTPException(422, "Адрес подписки для проверки: https://…")
            secrets["checker_subscription_url"] = url
            if len(mod.server_ids) != 1:
                raise HTTPException(422, "Выберите один сервер для Xray Checker")
            params["xray_checker_server_id"] = mod.server_ids[0]
            params["xray_checker_interval"] = mod.interval
            run["server_ids"] = []
        else:
            run["server_ids"] = [params["xray_checker_server_id"]] if params.get("xray_checker_server_id") else []
            params["xray_checker_server_id"] = None
    return run


async def _cdn_params(mod: ModuleIn, params: dict, secrets: dict, run: dict) -> None:
    """v28.98.0 (N7): «Cloudflare CDN» — the token is checked and kept with the installation's secrets; switching on
    adds the transport «cdn» (nodes) and/or marks the subscription; switching off removes what is on."""
    from . import cloudflare_cdn as cf
    token = mod.cloudflare_token.get_secret_value().strip() if mod.cloudflare_token else secrets.get("cloudflare_token", "")
    try:
        await cf.check_token(token)
    except cf.CloudflareError as exc:
        raise HTTPException(422, str(exc)) from exc
    secrets["cloudflare_token"] = token
    transports = set(params.get("transports") or [])
    if mod.enabled:
        if not (mod.cdn_nodes or mod.cdn_subscription):
            raise HTTPException(422, "Выберите, что вынести за CDN: трафик нод (XHTTP) и/или домен подписки")
        if mod.cdn_nodes:
            domain = (mod.cdn_domain or params.get("cdn_domain") or "").strip().lower().rstrip(".")
            if not rw_plan.DOMAIN.match(domain):
                raise HTTPException(422, "Домен CDN для нод, например cdn.example.com (в зоне Cloudflare этого токена)")
            try:
                await cf.zone_of(token, domain)
            except cf.CloudflareError as exc:
                raise HTTPException(422, str(exc)) from exc
            params["cdn_domain"] = domain
            transports.add("cdn")
        if mod.cdn_subscription:
            params["cdn_subscription"] = True
        run.update(cdn_nodes=mod.cdn_nodes, cdn_subscription=mod.cdn_subscription)
    else:
        nodes, sub = "cdn" in transports, bool(params.get("cdn_subscription"))
        if not (nodes or sub):
            raise HTTPException(409, "CDN этой установки не включён")
        run.update(cdn_nodes=nodes, cdn_subscription=sub)  # the parts that go back to direct
        transports.discard("cdn")
        params["cdn_subscription"] = False
    params["transports"] = sorted(transports)


@router.get("/installations/{installation_id}/xray-checker")
async def xray_checker(installation_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    """The servers of the subscription as Xray Checker sees them (its API on 127.0.0.1:2112, read over SSH)."""
    row = await _installation(db, installation_id)
    sid = (row.params or {}).get("xray_checker_server_id")
    if row.action != "install" or not sid:
        raise HTTPException(404, "Xray Checker не установлен для этой установки")
    ctx = await rw_jobs._context(db, row)
    try:
        data = await rw_steps.checker_status(ctx, sid)
    except rw_steps.StepError as exc:
        raise HTTPException(502, f"Сервер недоступен: {exc}") from exc
    if not data.get("success"):
        raise HTTPException(502, "Xray Checker не ответил")
    proxies = [{"name": p.get("name"), "server": p.get("server"), "port": p.get("port"), "protocol": p.get("protocol"),
                "online": bool(p.get("online")), "latency_ms": p.get("latencyMs"), "last_check": p.get("lastCheck")}
               for p in data.get("data") or [] if isinstance(p, dict)]
    return {"server_id": sid, "total": len(proxies), "online": sum(p["online"] for p in proxies), "proxies": proxies}


@router.post("/installations/{installation_id}/credentials")
async def credentials(installation_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_stepup("provision_nodes"))):
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
    if row.params.get("panel_access") == "tinyauth" and secrets.get("tinyauth_password"):
        out["tinyauth"] = {"url": f"https://{row.params['auth_domain']}", "username": secrets["tinyauth_username"],
                           "password": secrets["tinyauth_password"]}
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


# ---------------------------------------------------------------- v28.70.0: Xray Checker alerts

async def check_xray_checkers() -> list[str]:
    """Every installation with Xray Checker: servers of the subscription that went offline since the last check are
    sent to the owner's alerts once (and again only after they came back)."""
    import logging

    from .db import SessionLocal
    from .main import send_alert
    sent = []
    async with SessionLocal() as db:
        rows = (await db.execute(select(RemnawaveInstallation).where(RemnawaveInstallation.action == "install",
                                                                     RemnawaveInstallation.status == "succeeded"))).scalars().all()
        for row in rows:
            sid = (row.params or {}).get("xray_checker_server_id")
            if not sid:
                continue
            try:
                data = await rw_steps.checker_status(await rw_jobs._context(db, row), sid)
            except Exception as exc:  # noqa: BLE001 — one server never stops the others
                logging.getLogger(__name__).warning("Xray Checker of installation %s unreachable: %s", row.id, exc)
                continue
            if not data.get("success"):
                continue
            down = sorted(str(p.get("name")) for p in data.get("data") or [] if isinstance(p, dict) and not p.get("online"))
            result = dict(row.result or {})
            if down and down != result.get("checker_down"):
                text = f"Xray Checker (установка №{row.id}): недоступны {len(down)} — " + ", ".join(down[:10])
                await send_alert(text)
                sent.append(text)
            result["checker_down"] = down
            row.result = result
        await db.commit()
    return sent


async def _checker_loop() -> None:
    await asyncio.sleep(600)
    while True:
        try:
            await check_xray_checkers()
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("Xray Checker alerts failed: %s", exc)
        await asyncio.sleep(3600)


async def _start_checker() -> None:
    from . import main
    main._track_task(_checker_loop())


router.add_event_handler("startup", _start_checker)
