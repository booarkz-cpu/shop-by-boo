"""Plugin runtime: signed packages, approved capabilities, scoped API and signed event delivery.

A plugin never runs inside the shop. It is an external HTTPS service described by a signed
package that contains only a manifest (and an optional README). The shop:

* installs a package only when its Ed25519 signature verifies against an active trusted
  publisher key added by an administrator (``plugin_publishers``);
* checks API compatibility (``api_version``), the capability and event allowlists and the
  endpoint (public HTTPS only, pinned DNS on every delivery);
* enables a version only after the administrator approves exactly the capabilities it
  requests; an upgrade that asks for more stays on the old version until approved; any
  earlier version can be rolled back to without a restart (hotload is data-driven);
* gives each plugin its own API token and signing secret (shown once, stored hashed or
  encrypted). The token reaches only ``/api/plugin/v1`` and only the approved scopes; plugin
  settings, including secrets, are visible only to that plugin;
* delivers events from an outbox scan with HMAC signatures, retries with backoff, and stops
  a plugin automatically after repeated failures.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import logging
import re
import secrets
import time
import zipfile
from base64 import b64decode, b64encode
from datetime import datetime, timedelta
from typing import Callable

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import (Notification, Payment, Plan, PluginDelivery, PluginEventCursor, PluginInstall, PluginPackage,
                     PluginPublisher, Subscription, User)
from .security import decrypt_secret, encrypt_secret, require_permission

logger = logging.getLogger("vpnshop.plugins")

SUPPORTED_API_VERSIONS = {1}
CAPABILITIES = {
    "users.read": "Читать профиль клиента: ID, имя, дата регистрации",
    "subscriptions.read": "Читать подписки клиента: тариф, статус, срок",
    "payments.read": "Читать платёж: сумма, валюта, статус, тариф",
    "notifications.send": "Отправлять клиенту уведомления в приложение",
}
EVENTS = {
    "user.registered": "users.read",
    "payment.succeeded": "payments.read",
    "subscription.activated": "subscriptions.read",
}
SETTING_TYPES = {"string", "secret", "bool", "int"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{2,63}$")
VERSION_RE = re.compile(r"^(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_PACKAGE_BYTES = 256 * 1024
PACKAGE_FILES = {"manifest.json", "signature.json", "README.md"}
MAX_ATTEMPTS = 6
FAILURE_LIMIT = 20
NOTIFY_PER_MINUTE = 60
RETENTION = timedelta(days=30)


def private(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(dependencies=[Depends(private)])


class PackageError(ValueError):
    """The package is malformed, unsigned, untrusted or incompatible."""


# ---------------------------------------------------------------- packages and signatures

def fingerprint(public_key_b64: str) -> str:
    return hashlib.sha256(b64decode(public_key_b64)).hexdigest()[:16]


def package_digest(files: dict[str, bytes]) -> bytes:
    """What a publisher signs: SHA-256 of sorted ``name\\0sha256\\n`` lines of all files except the signature."""
    lines = "".join(f"{name}\0{hashlib.sha256(data).hexdigest()}\n" for name, data in sorted(files.items()) if name != "signature.json")
    return hashlib.sha256(lines.encode()).digest()


def read_package(data: bytes) -> dict[str, bytes]:
    if len(data) > MAX_PACKAGE_BYTES:
        raise PackageError("Пакет больше 256 КБ")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PackageError("Пакет не является zip-архивом") from exc
    files: dict[str, bytes] = {}
    total = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        if info.filename not in PACKAGE_FILES:
            raise PackageError(f"Недопустимый файл в пакете: {info.filename[:80]}. Разрешены manifest.json, signature.json, README.md")
        total += info.file_size
        if total > MAX_PACKAGE_BYTES * 4:
            raise PackageError("Распакованный пакет слишком большой")
        files[info.filename] = archive.read(info)
    for required in ("manifest.json", "signature.json"):
        if required not in files:
            raise PackageError(f"В пакете нет {required}")
    return files


def verify_signature(files: dict[str, bytes], publishers: list[PluginPublisher]) -> PluginPublisher:
    try:
        signature = json.loads(files["signature.json"])
        key_b64, sig_b64 = str(signature["public_key"]), str(signature["signature"])
    except (ValueError, KeyError, TypeError) as exc:
        raise PackageError("signature.json должен содержать public_key и signature (base64)") from exc
    publisher = next((p for p in publishers if p.public_key == key_b64 and p.revoked_at is None), None)
    if publisher is None:
        raise PackageError("Пакет подписан неизвестным или отозванным ключом издателя")
    try:
        Ed25519PublicKey.from_public_bytes(b64decode(key_b64)).verify(b64decode(sig_b64), package_digest(files))
    except (InvalidSignature, ValueError) as exc:
        raise PackageError("Подпись пакета не совпадает: файлы изменены после подписи") from exc
    return publisher


def validate_manifest(raw: bytes) -> dict:
    from .main import validate_public_url

    try:
        manifest = json.loads(raw)
    except ValueError as exc:
        raise PackageError("manifest.json не является JSON") from exc
    if not isinstance(manifest, dict):
        raise PackageError("manifest.json должен быть объектом")
    plugin_id = str(manifest.get("id", ""))
    if not ID_RE.fullmatch(plugin_id):
        raise PackageError("id: 3–64 символа a-z, 0-9, точка, дефис")
    version = str(manifest.get("version", ""))
    if not VERSION_RE.fullmatch(version):
        raise PackageError("version: формат X.Y.Z")
    if manifest.get("api_version") not in SUPPORTED_API_VERSIONS:
        raise PackageError(f"api_version {manifest.get('api_version')!r} не поддерживается; магазин поддерживает {sorted(SUPPORTED_API_VERSIONS)}")
    name = " ".join(str(manifest.get("name", "")).split())
    if not 1 <= len(name) <= 120:
        raise PackageError("name: 1–120 символов")
    try:
        endpoint = validate_public_url(str(manifest.get("endpoint", "")), allow_empty=False)
    except HTTPException as exc:
        raise PackageError(f"endpoint: {exc.detail}") from exc
    capabilities = manifest.get("capabilities", [])
    events = manifest.get("events", [])
    if not isinstance(capabilities, list) or not isinstance(events, list):
        raise PackageError("capabilities и events должны быть списками")
    unknown = sorted(set(map(str, capabilities)) - set(CAPABILITIES))
    if unknown:
        raise PackageError(f"Неизвестные capabilities: {', '.join(unknown)}")
    unknown = sorted(set(map(str, events)) - set(EVENTS))
    if unknown:
        raise PackageError(f"Неизвестные события: {', '.join(unknown)}")
    missing = sorted({EVENTS[e] for e in events} - set(capabilities))
    if missing:
        raise PackageError(f"Событиям нужны capabilities: {', '.join(missing)}")
    settings = manifest.get("settings", [])
    if not isinstance(settings, list) or len(settings) > 20:
        raise PackageError("settings: список не длиннее 20")
    normalized_settings = []
    for item in settings:
        if not isinstance(item, dict) or not KEY_RE.fullmatch(str(item.get("key", ""))) or item.get("type") not in SETTING_TYPES:
            raise PackageError("settings: каждый элемент — key (a-z0-9_), type (string|secret|bool|int), label")
        normalized_settings.append({"key": item["key"], "type": item["type"], "label": str(item.get("label") or item["key"])[:120], "required": bool(item.get("required"))})
    if len({s["key"] for s in normalized_settings}) != len(normalized_settings):
        raise PackageError("settings: ключи должны быть уникальны")
    return {
        "id": plugin_id,
        "name": name,
        "version": version,
        "api_version": manifest["api_version"],
        "publisher": str(manifest.get("publisher", ""))[:120],
        "description": str(manifest.get("description", ""))[:1000],
        "endpoint": endpoint,
        "capabilities": sorted(set(map(str, capabilities))),
        "events": sorted(set(map(str, events))),
        "settings": normalized_settings,
    }


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


# ---------------------------------------------------------------- admin API

class PublisherIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    public_key: str = Field(min_length=40, max_length=64)


class EnableIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(max_length=32)
    capabilities: list[str] = Field(default_factory=list, max_length=20)
    events: list[str] = Field(default_factory=list, max_length=20)


class VersionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(max_length=32)


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, str | bool | int | None] = Field(default_factory=dict)


async def _audit(db: AsyncSession, action: str, admin, target: str, details: dict | None = None):
    from .main import audit

    await audit(db, action, getattr(admin, "email", "admin"), target, details or {})


async def _install(db: AsyncSession, plugin_id: str, lock: bool = False) -> PluginInstall:
    query = select(PluginInstall).where(PluginInstall.id == plugin_id)
    row = await db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(404, "Плагин не найден")
    return row


async def _package(db: AsyncSession, plugin_id: str, version: str) -> PluginPackage:
    row = await db.scalar(select(PluginPackage).where(PluginPackage.plugin_id == plugin_id, PluginPackage.version == version))
    if row is None:
        raise HTTPException(404, "Версия плагина не загружена")
    return row


def _settings(install: PluginInstall) -> dict:
    if not install.settings_encrypted:
        return {}
    try:
        return json.loads(decrypt_secret(install.settings_encrypted))
    except Exception:
        return {}


def _public_settings(install: PluginInstall, manifest: dict | None) -> list[dict]:
    values = _settings(install)
    out = []
    for item in (manifest or {}).get("settings", []):
        value = values.get(item["key"])
        out.append({**item, "value": None if item["type"] == "secret" else value, "configured": value not in (None, "")})
    return out


async def _view(db: AsyncSession, install: PluginInstall) -> dict:
    packages = (await db.scalars(select(PluginPackage).where(PluginPackage.plugin_id == install.id))).all()
    packages = sorted(packages, key=lambda p: version_key(p.version), reverse=True)
    active = next((p for p in packages if p.version == install.active_version), None)
    latest = packages[0] if packages else None
    since = datetime.utcnow() - timedelta(hours=24)
    stats = dict((await db.execute(select(PluginDelivery.status, func.count(PluginDelivery.id)).where(PluginDelivery.plugin_id == install.id, PluginDelivery.created_at >= since).group_by(PluginDelivery.status))).all())
    pending = None
    if latest and latest.version != install.active_version:
        new_caps = sorted(set(latest.manifest["capabilities"]) - set(install.approved_capabilities))
        pending = {"version": latest.version, "new_capabilities": new_caps, "new_events": sorted(set(latest.manifest["events"]) - set(install.approved_events))}
    return {
        "id": install.id,
        "name": install.name,
        "state": install.state,
        "active_version": install.active_version,
        "approved_capabilities": install.approved_capabilities,
        "approved_events": install.approved_events,
        "credentials_issued": bool(install.token_hash),
        "consecutive_failures": install.consecutive_failures,
        "last_error": install.last_error,
        "disabled_reason": install.disabled_reason,
        "enabled_at": install.enabled_at.isoformat() if install.enabled_at else None,
        "endpoint": (active or latest).manifest["endpoint"] if (active or latest) else None,
        "settings": _public_settings(install, (active or latest).manifest if (active or latest) else None),
        "pending_upgrade": pending,
        "deliveries_24h": {str(k): int(v) for k, v in stats.items()},
        "versions": [
            {"version": p.version, "publisher": p.manifest.get("publisher"), "publisher_fingerprint": p.publisher_fingerprint, "capabilities": p.manifest["capabilities"], "events": p.manifest["events"], "description": p.manifest.get("description"), "sha256": p.sha256, "uploaded_at": p.uploaded_at.isoformat(), "uploaded_by": p.uploaded_by}
            for p in packages
        ],
    }


@router.get("/api/admin/plugins")
async def admin_plugins(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    installs = (await db.scalars(select(PluginInstall).order_by(PluginInstall.name))).all()
    publishers = (await db.scalars(select(PluginPublisher).order_by(PluginPublisher.id))).all()
    return {
        "plugins": [await _view(db, row) for row in installs],
        "publishers": [{"id": p.id, "name": p.name, "fingerprint": p.fingerprint, "public_key": p.public_key, "revoked": p.revoked_at is not None, "created_at": p.created_at.isoformat()} for p in publishers],
        "capabilities": CAPABILITIES,
        "events": EVENTS,
        "api_versions": sorted(SUPPORTED_API_VERSIONS),
    }


@router.post("/api/admin/plugins/publishers")
async def add_publisher(body: PublisherIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    key = body.public_key.strip()
    try:
        raw = b64decode(key, validate=True)
        Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Нужен открытый ключ Ed25519 (32 байта) в base64") from exc
    if await db.scalar(select(PluginPublisher.id).where(PluginPublisher.public_key == key)):
        raise HTTPException(409, "Этот ключ уже добавлен")
    row = PluginPublisher(name=" ".join(body.name.split()), public_key=key, fingerprint=fingerprint(key))
    db.add(row)
    await _audit(db, "plugin.publisher.added", admin, row.fingerprint, {"name": row.name})
    await db.commit()
    return {"id": row.id, "fingerprint": row.fingerprint}


@router.post("/api/admin/plugins/publishers/{publisher_id}/revoke")
async def revoke_publisher(publisher_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    row = await db.get(PluginPublisher, publisher_id)
    if row is None:
        raise HTTPException(404, "Ключ не найден")
    if row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
    stopped = []
    for install in (await db.scalars(select(PluginInstall).where(PluginInstall.state == "enabled").with_for_update())).all():
        package = await db.scalar(select(PluginPackage).where(PluginPackage.plugin_id == install.id, PluginPackage.version == install.active_version))
        if package and package.publisher_fingerprint == row.fingerprint:
            install.state, install.disabled_reason, install.updated_at = "disabled", "Ключ издателя отозван", datetime.utcnow()
            stopped.append(install.id)
    await _audit(db, "plugin.publisher.revoked", admin, row.fingerprint, {"stopped": stopped})
    await db.commit()
    return {"ok": True, "stopped": stopped}


@router.post("/api/admin/plugins/upload")
async def upload(file: UploadFile = File(...), db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    data = await file.read(MAX_PACKAGE_BYTES + 1)
    return await ingest(db, data, admin)


async def ingest(db: AsyncSession, data: bytes, admin):
    """Verify a package (signature, manifest) and store it as a new version."""
    try:
        files = read_package(data)
        publishers = (await db.scalars(select(PluginPublisher))).all()
        publisher = verify_signature(files, list(publishers))
        manifest = validate_manifest(files["manifest.json"])
    except PackageError as exc:
        raise HTTPException(422, str(exc))
    if await db.scalar(select(PluginPackage.id).where(PluginPackage.plugin_id == manifest["id"], PluginPackage.version == manifest["version"])):
        raise HTTPException(409, f"Версия {manifest['version']} уже загружена; повысьте version в манифесте")
    install = await db.scalar(select(PluginInstall).where(PluginInstall.id == manifest["id"]).with_for_update())
    if install is None:
        install = PluginInstall(id=manifest["id"], name=manifest["name"], state="installed", approved_capabilities=[], approved_events=[])
        db.add(install)
    package = PluginPackage(plugin_id=manifest["id"], version=manifest["version"], manifest=manifest, sha256=hashlib.sha256(data).hexdigest(), publisher_fingerprint=publisher.fingerprint, uploaded_by=getattr(admin, "email", "admin"))
    db.add(package)
    await db.flush()
    await _audit(db, "plugin.uploaded", admin, manifest["id"], {"version": manifest["version"], "sha256": package.sha256, "publisher": publisher.fingerprint, "capabilities": manifest["capabilities"]})
    await db.commit()
    return await _view(db, install)


@router.post("/api/admin/plugins/{plugin_id}/enable")
async def enable(plugin_id: str, body: EnableIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    install = await _install(db, plugin_id, lock=True)
    package = await _package(db, plugin_id, body.version)
    publisher = await db.scalar(select(PluginPublisher).where(PluginPublisher.fingerprint == package.publisher_fingerprint))
    if publisher is None or publisher.revoked_at is not None:
        raise HTTPException(409, "Ключ издателя этой версии отозван")
    manifest = package.manifest
    if sorted(set(body.capabilities)) != manifest["capabilities"] or sorted(set(body.events)) != manifest["events"]:
        raise HTTPException(409, "Подтвердите ровно те capabilities и события, которые запрашивает эта версия")
    required = [s["key"] for s in manifest["settings"] if s["required"]]
    values = _settings(install)
    missing = [key for key in required if values.get(key) in (None, "")]
    if missing:
        raise HTTPException(409, f"Заполните обязательные настройки: {', '.join(missing)}")
    credentials = None
    if not install.token_hash or not install.signing_secret_encrypted:
        token, secret = "cpl_" + secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        install.token_hash = hashlib.sha256(token.encode()).hexdigest()
        install.signing_secret_encrypted = encrypt_secret(secret)
        credentials = {"api_token": token, "signing_secret": secret}
    previous = install.active_version
    install.active_version = package.version
    install.name = manifest["name"]
    install.approved_capabilities, install.approved_events = manifest["capabilities"], manifest["events"]
    install.state, install.disabled_reason, install.consecutive_failures = "enabled", None, 0
    install.enabled_at = install.enabled_at or datetime.utcnow()
    install.updated_at = datetime.utcnow()
    await _audit(db, "plugin.enabled", admin, plugin_id, {"version": package.version, "previous": previous, "capabilities": manifest["capabilities"], "events": manifest["events"]})
    await db.commit()
    view = await _view(db, install)
    if credentials:
        view["credentials"] = credentials
    return view


@router.post("/api/admin/plugins/{plugin_id}/rollback")
async def rollback(plugin_id: str, body: VersionIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    install = await _install(db, plugin_id, lock=True)
    package = await _package(db, plugin_id, body.version)
    manifest = package.manifest
    if not set(manifest["capabilities"]) <= set(install.approved_capabilities) or not set(manifest["events"]) <= set(install.approved_events):
        raise HTTPException(409, "Эта версия запрашивает права, которые не подтверждены; используйте включение с подтверждением")
    previous = install.active_version
    install.active_version = package.version
    install.approved_capabilities, install.approved_events = manifest["capabilities"], manifest["events"]
    install.updated_at = datetime.utcnow()
    await _audit(db, "plugin.rollback", admin, plugin_id, {"version": package.version, "previous": previous})
    await db.commit()
    return await _view(db, install)


@router.post("/api/admin/plugins/{plugin_id}/disable")
async def disable(plugin_id: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    install = await _install(db, plugin_id, lock=True)
    install.state, install.disabled_reason, install.updated_at = "disabled", "Выключен администратором", datetime.utcnow()
    await _audit(db, "plugin.disabled", admin, plugin_id)
    await db.commit()
    return await _view(db, install)


@router.post("/api/admin/plugins/{plugin_id}/rotate")
async def rotate(plugin_id: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    install = await _install(db, plugin_id, lock=True)
    token, secret = "cpl_" + secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    install.token_hash = hashlib.sha256(token.encode()).hexdigest()
    install.signing_secret_encrypted = encrypt_secret(secret)
    install.updated_at = datetime.utcnow()
    await _audit(db, "plugin.credentials.rotated", admin, plugin_id)
    await db.commit()
    view = await _view(db, install)
    view["credentials"] = {"api_token": token, "signing_secret": secret}
    return view


@router.post("/api/admin/plugins/{plugin_id}/settings")
async def save_settings(plugin_id: str, body: SettingsIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    install = await _install(db, plugin_id, lock=True)
    packages = (await db.scalars(select(PluginPackage).where(PluginPackage.plugin_id == plugin_id))).all()
    package = next((p for p in packages if p.version == install.active_version), None) or max(packages, key=lambda p: version_key(p.version))
    schema = {s["key"]: s for s in package.manifest["settings"]}
    unknown = sorted(set(body.values) - set(schema))
    if unknown:
        raise HTTPException(422, f"Неизвестные настройки: {', '.join(unknown)}")
    current = _settings(install)
    for key, value in body.values.items():
        kind = schema[key]["type"]
        if kind == "secret" and value in (None, ""):
            continue  # an empty secret field keeps the stored value
        if kind == "bool":
            value = bool(value)
        elif kind == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise HTTPException(422, f"{key}: нужно целое число")
        else:
            value = "" if value is None else str(value)[:2000]
        current[key] = value
    install.settings_encrypted = encrypt_secret(json.dumps(current, ensure_ascii=False))
    install.updated_at = datetime.utcnow()
    await _audit(db, "plugin.settings.updated", admin, plugin_id, {"keys": sorted(body.values)})
    await db.commit()
    return await _view(db, install)


@router.delete("/api/admin/plugins/{plugin_id}")
async def uninstall(plugin_id: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    install = await _install(db, plugin_id, lock=True)
    await db.execute(delete(PluginDelivery).where(PluginDelivery.plugin_id == plugin_id))
    await db.execute(delete(PluginPackage).where(PluginPackage.plugin_id == plugin_id))
    await db.delete(install)
    await _audit(db, "plugin.uninstalled", admin, plugin_id)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- plugin API v1

async def plugin_from_request(request: Request, db: AsyncSession, capability: str | None) -> PluginInstall:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token.startswith("cpl_"):
        raise HTTPException(401, "Plugin token required")
    install = await db.scalar(select(PluginInstall).where(PluginInstall.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    if install is None or install.state != "enabled":
        raise HTTPException(401, "Plugin is not enabled")
    if capability and capability not in install.approved_capabilities:
        raise HTTPException(403, f"Capability {capability} is not approved for this plugin")
    return install


@router.get("/api/plugin/v1/me")
async def plugin_me(request: Request, db: AsyncSession = Depends(get_db)):
    install = await plugin_from_request(request, db, None)
    return {"id": install.id, "version": install.active_version, "api_version": 1, "capabilities": install.approved_capabilities, "events": install.approved_events, "settings": _settings(install)}


@router.get("/api/plugin/v1/users/{user_id}")
async def plugin_user(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    await plugin_from_request(request, db, "users.read")
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(404, "User not found")
    return {"id": user.id, "username": user.username, "created_at": user.created_at.isoformat() + "Z"}


@router.get("/api/plugin/v1/users/{user_id}/subscriptions")
async def plugin_subscriptions(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    await plugin_from_request(request, db, "subscriptions.read")
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(404, "User not found")
    rows = (await db.scalars(select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.id))).all()
    plans = {p.id: p.name for p in (await db.scalars(select(Plan).where(Plan.id.in_([r.plan_id for r in rows if r.plan_id])))).all()} if rows else {}
    return {"items": [{"id": r.id, "plan": plans.get(r.plan_id), "status": r.lifecycle_status, "primary": r.is_primary, "expires_at": r.expires_at.isoformat() + "Z" if r.expires_at else None} for r in rows]}


@router.get("/api/plugin/v1/payments/{payment_id}")
async def plugin_payment(payment_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    await plugin_from_request(request, db, "payments.read")
    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(404, "Payment not found")
    plan = await db.get(Plan, payment.plan_id) if payment.plan_id else None
    return {"id": payment.id, "user_id": payment.user_id, "amount": str(payment.amount), "currency": payment.currency, "status": payment.status, "plan": plan.name if plan else None, "created_at": payment.created_at.isoformat() + "Z"}


class PluginNotificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=1000)
    dedupe_key: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")


@router.post("/api/plugin/v1/notifications")
async def plugin_notify(body: PluginNotificationIn, request: Request, db: AsyncSession = Depends(get_db)):
    install = await plugin_from_request(request, db, "notifications.send")
    user = await db.get(User, body.user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(404, "User not found")
    kind = f"plugin.{install.id}"[:64]
    recent = await db.scalar(select(func.count(Notification.id)).where(Notification.kind == kind, Notification.created_at >= datetime.utcnow() - timedelta(minutes=1)))
    if (recent or 0) >= NOTIFY_PER_MINUTE:
        raise HTTPException(429, "Notification rate limit: 60 per minute")
    key = f"plugin:{install.id}:{body.dedupe_key}"[:160]
    existing = await db.scalar(select(Notification).where(Notification.user_id == user.id, Notification.dedupe_key == key))
    if existing:
        return {"id": existing.id, "duplicate": True}
    row = Notification(user_id=user.id, channel="in_app", kind=kind, title=" ".join(body.title.split()), body=body.body.strip(), status="sent", sent_at=datetime.utcnow(), dedupe_key=key)
    db.add(row)
    await db.commit()
    return {"id": row.id, "duplicate": False}


# ---------------------------------------------------------------- events and delivery

async def _cursor(db: AsyncSession, source: str, current_max: int) -> PluginEventCursor | None:
    row = await db.get(PluginEventCursor, source, with_for_update=True)
    if row is None:
        # First run: start at the current end. Plugins never receive history from before the runtime existed.
        db.add(PluginEventCursor(source=source, last_id=current_max))
        await db.flush()
        return None
    return row


async def scan_events(db: AsyncSession, batch: int = 500) -> int:
    """Outbox scan: turns new users and payment notifications into deliveries for subscribed plugins."""
    installs = (await db.scalars(select(PluginInstall).where(PluginInstall.state == "enabled"))).all()
    created = 0
    max_user = await db.scalar(select(func.max(User.id))) or 0
    max_note = await db.scalar(select(func.max(Notification.id))) or 0
    users_cursor = await _cursor(db, "users", max_user)
    notes_cursor = await _cursor(db, "notifications", max_note)
    candidates: list[tuple[str, str, dict, datetime]] = []
    if users_cursor is not None:
        users = (await db.execute(select(User.id, User.created_at).where(User.id > users_cursor.last_id).order_by(User.id).limit(batch))).all()
        for user_id, created_at in users:
            candidates.append(("user.registered", f"user.registered:{user_id}", {"user_id": user_id}, created_at))
        if users:
            users_cursor.last_id = users[-1][0]
    if notes_cursor is not None:
        notes = (await db.execute(select(Notification.id, Notification.kind, Notification.user_id, Notification.dedupe_key, Notification.created_at).where(Notification.id > notes_cursor.last_id).order_by(Notification.id).limit(batch))).all()
        for _, kind, user_id, dedupe_key, created_at in notes:
            match = re.fullmatch(r"payment:(\d+):(success|ready)", dedupe_key or "")
            if not match:
                continue
            event = {"payment_success": "payment.succeeded", "subscription_ready": "subscription.activated"}.get(kind)
            if event:
                candidates.append((event, f"{event}:{match.group(1)}", {"payment_id": int(match.group(1)), "user_id": user_id}, created_at))
        if notes:
            notes_cursor.last_id = notes[-1][0]
    now = datetime.utcnow()
    for install in installs:
        wanted = [c for c in candidates if c[0] in install.approved_events and EVENTS[c[0]] in install.approved_capabilities and install.enabled_at and c[3] >= install.enabled_at]
        if not wanted:
            continue
        existing = set((await db.scalars(select(PluginDelivery.event_key).where(PluginDelivery.plugin_id == install.id, PluginDelivery.event_key.in_([c[1] for c in wanted])))).all())
        for event, key, payload, _ in wanted:
            if key in existing:
                continue
            db.add(PluginDelivery(plugin_id=install.id, event=event, event_key=key, payload=payload, status="queued", next_attempt_at=now, created_at=now))
            created += 1
    await db.commit()
    return created


def _default_client() -> httpx.AsyncClient:
    from .main import _pinned_public_http_client

    return _pinned_public_http_client(10)


client_factory: Callable[[], httpx.AsyncClient] = _default_client


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "v1=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


async def deliver_due(db: AsyncSession, now: datetime | None = None, limit: int = 50) -> dict[str, int]:
    now = now or datetime.utcnow()
    claimed = (await db.execute(select(PluginDelivery).where(PluginDelivery.status.in_(("queued", "sending")), PluginDelivery.next_attempt_at <= now).order_by(PluginDelivery.next_attempt_at, PluginDelivery.id).limit(limit).with_for_update(skip_locked=True))).scalars().all()
    ids = [row.id for row in claimed]
    for row in claimed:
        row.status, row.attempts, row.next_attempt_at = "sending", row.attempts + 1, now + timedelta(minutes=2)
    await db.commit()
    stats: dict[str, int] = {}
    for delivery_id in ids:
        outcome = await _deliver_one(db, delivery_id, now)
        stats[outcome] = stats.get(outcome, 0) + 1
    return stats


async def _deliver_one(db: AsyncSession, delivery_id: int, now: datetime) -> str:
    delivery = await db.get(PluginDelivery, delivery_id, populate_existing=True)
    if delivery is None or delivery.status != "sending":
        return "lost"
    install = await db.get(PluginInstall, delivery.plugin_id, populate_existing=True)
    if install is None or install.state != "enabled" or delivery.event not in install.approved_events:
        delivery.status, delivery.last_error = "skipped", "plugin disabled"
        await db.commit()
        return "skipped"
    package = await db.scalar(select(PluginPackage).where(PluginPackage.plugin_id == install.id, PluginPackage.version == install.active_version))
    body = json.dumps({"id": delivery.id, "event": delivery.event, "plugin": install.id, "version": install.active_version, "created_at": delivery.created_at.isoformat() + "Z", "data": delivery.payload}, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    headers = {"Content-Type": "application/json", "User-Agent": "CorgiShop-Plugins/1", "X-Corgi-Event": delivery.event, "X-Corgi-Delivery": str(delivery.id), "X-Corgi-Timestamp": timestamp, "X-Corgi-Signature": sign(decrypt_secret(install.signing_secret_encrypted), timestamp, body)}
    try:
        async with client_factory() as client:
            response = await client.post(package.manifest["endpoint"], content=body, headers=headers)
        status = response.status_code
        error = None if 200 <= status < 300 else f"HTTP {status}"
    except (httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
        status, error = 0, type(exc).__name__
    if error is None:
        delivery.status, delivery.sent_at, delivery.last_error = "sent", now, None
        install.consecutive_failures, install.last_error = 0, None
        outcome = "sent"
    else:
        permanent = 400 <= status < 500 and status not in (408, 425, 429)
        install.consecutive_failures += 1
        install.last_error = f"{delivery.event}: {error}"[:255]
        if permanent or delivery.attempts >= MAX_ATTEMPTS:
            delivery.status, delivery.last_error = "failed", error
            outcome = "failed"
        else:
            delivery.status, delivery.last_error = "queued", error
            delivery.next_attempt_at = now + timedelta(seconds=min(3600, 30 * 2 ** (delivery.attempts - 1)))
            outcome = "retry"
        if install.consecutive_failures >= FAILURE_LIMIT and install.state == "enabled":
            install.state = "failing"
            install.disabled_reason = f"Остановлен автоматически: {FAILURE_LIMIT} ошибок доставки подряд ({error})"
            logger.warning("Plugin %s stopped after %s failures", install.id, FAILURE_LIMIT)
    install.updated_at = now
    await db.commit()
    return outcome


async def cleanup(db: AsyncSession, now: datetime | None = None):
    await db.execute(delete(PluginDelivery).where(PluginDelivery.created_at < (now or datetime.utcnow()) - RETENTION, PluginDelivery.status.in_(("sent", "failed", "skipped"))))
    await db.commit()


async def plugin_scheduler():
    from .db import engine

    last_cleanup = 0.0
    while True:
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                await scan_events(db)
                await deliver_due(db)
                if time.time() - last_cleanup > 3600:
                    await cleanup(db)
                    last_cleanup = time.time()
        except Exception as exc:
            logger.warning("Plugin runtime cycle failed; retrying: %s", type(exc).__name__)
        await asyncio.sleep(5)


def sign_package(files: dict[str, bytes], private_key) -> bytes:
    """Builds a signed package. Used by `scripts/sign-plugin.py` and tests."""
    from cryptography.hazmat.primitives import serialization

    content = {name: data for name, data in files.items() if name != "signature.json"}
    public = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    signature = {"public_key": b64encode(public).decode(), "signature": b64encode(private_key.sign(package_digest(content))).decode()}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(content.items()):
            archive.writestr(name, data)
        archive.writestr("signature.json", json.dumps(signature))
    return buffer.getvalue()


# ---------------------------------------------------------------- catalog
#
# A catalog is a JSON index published by a plugin publisher on HTTPS:
#   {"catalog": 1, "name": "...", "plugins": [{"id", "name", "version", "description",
#    "package_url", "sha256", "homepage"}], "public_key": "<base64>", "signature": "<base64>"}
# The signature (Ed25519) covers SHA-256 of the canonical JSON of {"catalog", "name",
# "plugins"}; the key must be a trusted publisher. Installing downloads the package over
# HTTPS (pinned DNS, no redirects), checks its SHA-256 from the index and then runs the
# normal package verification, so a catalog can never bypass the package signature.

CATALOG_SETTING = "plugin_catalogs"
MAX_CATALOGS = 5
MAX_CATALOG_BYTES = 512 * 1024


def catalog_digest(index: dict) -> bytes:
    body = {"catalog": index.get("catalog"), "name": index.get("name"), "plugins": index.get("plugins")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).digest()


def verify_catalog(index: dict, publishers: list[PluginPublisher]) -> PluginPublisher:
    if not isinstance(index, dict) or index.get("catalog") != 1 or not isinstance(index.get("plugins"), list):
        raise PackageError("Каталог должен быть JSON с полями catalog=1 и plugins")
    if len(index["plugins"]) > 200:
        raise PackageError("В каталоге больше 200 плагинов")
    key_b64, sig_b64 = str(index.get("public_key") or ""), str(index.get("signature") or "")
    publisher = next((p for p in publishers if p.public_key == key_b64 and p.revoked_at is None), None)
    if publisher is None:
        raise PackageError("Каталог подписан неизвестным или отозванным ключом издателя")
    try:
        Ed25519PublicKey.from_public_bytes(b64decode(key_b64)).verify(b64decode(sig_b64), catalog_digest(index))
    except (InvalidSignature, ValueError) as exc:
        raise PackageError("Подпись каталога не совпадает") from exc
    for item in index["plugins"]:
        if not isinstance(item, dict) or not ID_RE.match(str(item.get("id", ""))) or not VERSION_RE.match(str(item.get("version", ""))):
            raise PackageError("Запись каталога: неверный id или version")
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) or not str(item.get("package_url", "")).startswith("https://"):
            raise PackageError(f"Запись {item.get('id')}: нужен sha256 и package_url на https://")
    return publisher


async def _fetch(url: str, limit: int) -> bytes:
    from .main import _pinned_public_http_client, validate_public_url
    validate_public_url(url, allow_empty=False)
    async with _pinned_public_http_client(15) as client:
        async with client.stream("GET", url, headers={"Accept": "application/json, application/zip"}) as response:
            if response.status_code != 200:
                raise PackageError(f"{url}: HTTP {response.status_code}")
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > limit:
                    raise PackageError(f"{url}: ответ больше {limit // 1024} КБ")
                chunks.append(chunk)
    return b"".join(chunks)


async def _catalog_urls(db: AsyncSession) -> list[str]:
    from .models import AppSetting
    row = await db.get(AppSetting, CATALOG_SETTING)
    try:
        urls = json.loads(row.value) if row and row.value else []
    except ValueError:
        urls = []
    return [u for u in urls if isinstance(u, str)][:MAX_CATALOGS]


async def _load_catalog(db: AsyncSession, url: str) -> tuple[dict, PluginPublisher]:
    raw = await _fetch(url, MAX_CATALOG_BYTES)
    try:
        index = json.loads(raw)
    except ValueError as exc:
        raise PackageError(f"{url}: не JSON") from exc
    publishers = (await db.scalars(select(PluginPublisher))).all()
    return index, verify_catalog(index, list(publishers))


class CatalogsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    urls: list[str] = Field(default_factory=list, max_length=MAX_CATALOGS)


@router.get("/api/admin/plugins/catalogs")
async def catalog_settings(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    return {"urls": await _catalog_urls(db)}


@router.put("/api/admin/plugins/catalogs")
async def save_catalogs(body: CatalogsIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    from .main import validate_public_url
    from .models import AppSetting
    urls = []
    for url in body.urls:
        url = url.strip()
        if not url.startswith("https://"):
            raise HTTPException(400, "Адрес каталога должен начинаться с https://")
        validate_public_url(url, allow_empty=False)
        if url not in urls:
            urls.append(url)
    row = await db.get(AppSetting, CATALOG_SETTING)
    if row:
        row.value = json.dumps(urls)
    else:
        db.add(AppSetting(key=CATALOG_SETTING, value=json.dumps(urls)))
    await _audit(db, "plugin.catalogs.updated", admin, "catalogs", {"urls": urls})
    await db.commit()
    return {"urls": urls}


@router.get("/api/admin/plugins/catalog")
async def catalog(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    installed = {row.id: row for row in (await db.scalars(select(PluginInstall))).all()}
    sources, entries = [], []
    for url in await _catalog_urls(db):
        try:
            index, publisher = await _load_catalog(db, url)
        except (PackageError, HTTPException, httpx.HTTPError) as exc:
            sources.append({"url": url, "ok": False, "error": str(getattr(exc, "detail", exc))[:300]})
            continue
        sources.append({"url": url, "ok": True, "name": str(index.get("name") or "")[:80], "publisher": publisher.name, "count": len(index["plugins"])})
        for item in index["plugins"]:
            current = installed.get(item["id"])
            entries.append({"catalog": url, "id": item["id"], "name": str(item.get("name") or item["id"])[:80], "version": item["version"],
                            "description": str(item.get("description") or "")[:500], "homepage": str(item.get("homepage") or "")[:300],
                            "installed_version": current.active_version if current else None,
                            "update": bool(current and current.active_version and version_key(item["version"]) > version_key(current.active_version))})
    return {"sources": sources, "plugins": entries}


class CatalogInstallIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog: str
    id: str
    version: str


@router.post("/api/admin/plugins/catalog/install")
async def catalog_install(body: CatalogInstallIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    if body.catalog not in await _catalog_urls(db):
        raise HTTPException(404, "Каталог не подключён")
    try:
        index, _ = await _load_catalog(db, body.catalog)
        item = next((x for x in index["plugins"] if x["id"] == body.id and x["version"] == body.version), None)
        if item is None:
            raise PackageError("Плагина с такой версией нет в каталоге")
        data = await _fetch(item["package_url"], MAX_PACKAGE_BYTES)
    except PackageError as exc:
        raise HTTPException(422, str(exc))
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Пакет не скачан: {exc}")
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise HTTPException(422, "SHA-256 скачанного пакета не совпадает с каталогом")
    view = await ingest(db, data, admin)
    await _audit(db, "plugin.catalog.installed", admin, body.id, {"version": body.version, "catalog": body.catalog})
    await db.commit()
    return view
