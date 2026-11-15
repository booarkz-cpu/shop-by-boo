"""«Серверы → SelfSteal» (v28.91.0, stage 20, N8): the sites the nodes show to strangers, in one place.

* overview — every node the shop knows (installations of the wizard) next to the nodes of the connected panel:
  «известно про N из M»; for each — country, name, address, domain, the site on it and the last outside check;
* check — selfsteal_check from the shop's server against the node's own address;
* catalogue — 22 templates (selfsteal_sites) with a preview of the build a node would get;
* own sites — archives the administrator uploads (zip / tar.gz, checked file by file), kept as tar.gz in
  MEDIA_DIR/selfsteal-sites; putting one on a node is the module «Сайт SelfSteal» of the installation (plan →
  approval → steps → rollback), like a catalogue template.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import rw_plan, selfsteal_check, selfsteal_sites
from .config import settings
from .db import get_db
from .models import RemnawaveInstallation, RemnawaveServer
from .security import require_permission

router = APIRouter(prefix="/api/admin/rw/selfsteal")
SITES_KEY, CHECKS_KEY = "rw.selfsteal.sites", "rw.selfsteal.checks"
MAX_SITES = 30


def upload_dir() -> Path:
    return Path(settings.media_dir) / "selfsteal-sites"


def upload_path(site_id: str | None) -> Path:
    if not site_id or len(site_id) != 16 or any(c not in "0123456789abcdef" for c in site_id):
        return upload_dir() / "-missing-"
    return upload_dir() / f"{site_id}.tar.gz"


async def _load(db: AsyncSession, key: str, default: dict) -> dict:
    from .node_health import _load as load
    return await load(db, key, default)


async def _save(db: AsyncSession, key: str, value: dict) -> None:
    from .node_health import _save as save
    await save(db, key, value)


async def _sites(db: AsyncSession) -> list[dict]:
    return list((await _load(db, SITES_KEY, {"items": []}))["items"])


async def _save_sites(db: AsyncSession, items: list[dict]) -> None:
    await _save(db, SITES_KEY, {"items": items})


async def _audit(db: AsyncSession, action: str, actor: str, target: str, details: dict) -> None:
    from .main import audit
    await audit(db, action, actor, target, details)


# ---------------------------------------------------------------- overview

async def known_nodes(db: AsyncSession) -> list[dict]:
    """Nodes installed by the wizard and still in place: the latest settings of each installation (its params)."""
    rows = (await db.execute(select(RemnawaveInstallation).where(RemnawaveInstallation.action == "install",
                                                                 RemnawaveInstallation.status == "succeeded")
                             .order_by(RemnawaveInstallation.id))).scalars().all()
    removed = {r.source_installation_id for r in (await db.execute(select(RemnawaveInstallation).where(
        RemnawaveInstallation.action == "remove", RemnawaveInstallation.status == "succeeded"))).scalars().all()}
    out = []
    for row in rows:
        if row.id in removed:
            continue
        params = row.params or {}
        for sid in params.get("node_server_ids") or ([params["panel_server_id"]] if params.get("mode") == "panel_node" else []):
            server = await db.get(RemnawaveServer, sid)
            if not server:
                continue
            domain = params.get("selfsteal_domain")
            template = params.get("selfsteal_template") or "cloud"
            site = None
            if domain:
                site = {"template": template, "title": rw_plan.SELFSTEAL_TEMPLATES.get(template, template),
                        "lang": params.get("selfsteal_lang") or "ru", "upload": params.get("selfsteal_upload")}
            out.append({"key": f"{row.id}:{sid}", "installation_id": row.id, "server_id": sid, "name": server.name,
                        "address": server.host, "country": params.get("country_code") or "XX", "domain": domain, "site": site})
    return out


async def panel_nodes() -> list[dict] | None:
    """Nodes of the panel the shop is connected to; None when it is not connected or does not answer."""
    from .remnawave import RemnawaveClient, RemnawaveNotConfigured
    try:
        data = await RemnawaveClient()._request("GET", "/api/nodes")
    except RemnawaveNotConfigured:
        return None
    except Exception:  # noqa: BLE001 — the overview still shows what the shop knows
        return None
    rows = data if isinstance(data, list) else (data or {}).get("nodes") or []
    return [{"name": n.get("name") or "", "address": n.get("address") or "", "country": n.get("countryCode") or "XX"} for n in rows]


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    known = await known_nodes(db)
    checks = await _load(db, CHECKS_KEY, {})
    for node in known:
        node["check"] = checks.get(node["key"])
    panel = await panel_nodes()
    addresses = {n["address"] for n in known} | {n["domain"] for n in known if n["domain"]}
    unknown = [n | {"key": None, "domain": None, "site": None, "check": None, "unknown": True}
               for n in (panel or []) if n["address"] not in addresses]
    total = len(known) + len(unknown) if panel is not None else len(known)
    return {"known": len(known), "total": total, "panel_connected": panel is not None, "nodes": known + unknown,
            "templates": len(selfsteal_sites.CATALOGUE)}


# ---------------------------------------------------------------- the outside check

class CheckIn(BaseModel):
    key: str


@router.post("/check")
async def check(payload: CheckIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    node = next((n for n in await known_nodes(db) if n["key"] == payload.key), None)
    if not node:
        raise HTTPException(404, "Нода не найдена среди установок мастера")
    if not node["domain"]:
        raise HTTPException(422, "У этой ноды нет домена SelfSteal: проверять нечего")
    try:
        address = selfsteal_check.node_address(node["address"])
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc) if isinstance(exc, ValueError) else "Адрес ноды не разрешается") from exc
    report = await selfsteal_check.check(node["domain"], address)
    checks = await _load(db, CHECKS_KEY, {})
    checks[node["key"]] = report
    await _save(db, CHECKS_KEY, checks)
    await _audit(db, "rw.selfsteal.checked", admin.email, node["key"], {"domain": node["domain"], "remarks": report["remarks"]})
    await db.commit()
    return report


# ---------------------------------------------------------------- the catalogue

@router.get("/catalogue")
async def catalogue(admin=Depends(require_permission("read"))):
    return {"themes": {k: v[0] for k, v in selfsteal_sites.THEMES.items()}, "templates": selfsteal_sites.catalogue()}


@router.get("/preview/{template}")
async def preview(template: str, domain: str = "node.example.com", lang: str = "ru", page: str = "index.html",
                  admin=Depends(require_permission("read"))):
    """One page of the build a node with ``domain`` would get, as one self-contained document for a sandboxed frame of
    the admin panel: the styles and pictures inline, links to the other pages of the preview."""
    import base64
    import re
    from urllib.parse import quote
    domain = domain.lower()
    if not rw_plan.DOMAIN.match(domain):
        raise HTTPException(422, "Некорректный домен")
    try:
        files = selfsteal_sites.build_site(template, domain, lang)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if page not in files or not page.endswith(".html"):
        raise HTTPException(404, "Нет такой страницы")
    text = files[page].decode()
    text = text.replace("<link rel='stylesheet' href='/style.css'>", f"<style>{files['style.css'].decode()}</style>")
    for name in ("hero.svg", "favicon.svg"):
        text = text.replace(f"/{name}", "data:image/svg+xml;base64," + base64.b64encode(files[name]).decode())

    def link(m: re.Match) -> str:
        target = m.group(1).strip("/")
        target = f"{target}/index.html" if target else "index.html"
        return f"href='?domain={quote(domain)}&lang={lang}&page={quote(target)}'"
    text = re.sub(r"href='(/[a-z0-9/-]*)'", link, text)
    # Only the admin panel may show it in a frame (the API answers X-Frame-Options: DENY everywhere else).
    ancestors = " ".join(["'self'", *settings.admin_cors_origins_list()])
    return Response(text, media_type="text/html; charset=utf-8", headers={
        "Content-Security-Policy": f"default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; "
                                   f"frame-ancestors {ancestors}",
        "X-Frame-Options": "SAMEORIGIN", "X-Content-Type-Options": "nosniff"})


# ---------------------------------------------------------------- own sites (uploaded archives)

@router.get("/sites")
async def list_sites(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    return {"sites": await _sites(db), "limits": {"archive_mb": selfsteal_sites.MAX_ARCHIVE // 2**20,
                                                                  "files": selfsteal_sites.MAX_FILES}}


@router.post("/sites")
async def upload_site(file: UploadFile = File(...), name: str = Form(""), db: AsyncSession = Depends(get_db),
                      admin=Depends(require_permission("provision_nodes"))):
    data = await file.read(selfsteal_sites.MAX_ARCHIVE + 1)
    try:
        files = selfsteal_sites.read_archive(data, file.filename or "")
    except selfsteal_sites.SiteError as exc:
        raise HTTPException(422, str(exc)) from exc
    bundle = selfsteal_sites.pack(files)
    site_id = hashlib.sha256(bundle).hexdigest()[:16]
    sites = [s for s in await _sites(db) if s["id"] != site_id]
    if len(sites) >= MAX_SITES:
        raise HTTPException(409, f"Своих сайтов уже {MAX_SITES}: удалите ненужные")
    upload_dir().mkdir(parents=True, exist_ok=True)
    tmp = upload_path(site_id).with_suffix(".part")
    tmp.write_bytes(bundle)
    tmp.replace(upload_path(site_id))
    title = selfsteal_sites.page_title(files)
    entry = {"id": site_id, "name": (name.strip() or title or file.filename or site_id)[:80], "title": title,
             "files": len(files), "size": sum(len(b) for b in files.values()), "archive": (file.filename or "")[:120],
             "uploaded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "by": admin.email}
    await _save_sites(db, [entry, *sites])
    await _audit(db, "rw.selfsteal.site_uploaded", admin.email, site_id, {"files": entry["files"], "size": entry["size"]})
    await db.commit()
    return entry


@router.delete("/sites/{site_id}")
async def delete_site(site_id: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    sites = await _sites(db)
    if not any(s["id"] == site_id for s in sites):
        raise HTTPException(404, "Нет такого сайта")
    in_use = [n["name"] for n in await known_nodes(db) if (n["site"] or {}).get("upload") == site_id]
    if in_use:
        raise HTTPException(409, f"Сайт стоит на нодах: {', '.join(in_use)} — сначала выберите им другой")
    upload_path(site_id).unlink(missing_ok=True)
    await _save_sites(db, [s for s in sites if s["id"] != site_id])
    await _audit(db, "rw.selfsteal.site_deleted", admin.email, site_id, {})
    await db.commit()
    return {"deleted": site_id}
