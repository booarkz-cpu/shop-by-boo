"""Remnawave panel from the shop admin: config profiles with their inbounds, Internal Squads (members, inbounds) and
hosts, with the everyday actions — turn a host on or off, add every customer to a squad or take them out — and,
since v28.38, a full editor: create, edit and delete hosts (remark, address, port, inbound, SNI, Host header, path,
tag) and Internal Squads (name and inbounds). Editing the Xray config itself stays in the panel. Calls are checked against a real panel in CI
(tests/live/test_remnawave_live.py). «Серверы → Панель Remnawave» (web) and the mobile admin card.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .security import require_permission

router = APIRouter()


def _list(value, key):
    if isinstance(value, dict):
        value = value.get(key, value.get("response", []))
    return value if isinstance(value, list) else []


async def overview(panel=None) -> dict:
    from .remnawave import RemnawaveClient
    panel = panel or RemnawaveClient()
    profiles = _list(await panel._request("GET", "/api/config-profiles"), "configProfiles")
    squads = _list(await panel.list_internal_squads(), "internalSquads")
    hosts = _list(await panel._request("GET", "/api/hosts"), "hosts")
    return {
        "profiles": [{"uuid": p.get("uuid"), "name": p.get("name"),
                      "inbounds": [{"uuid": i.get("uuid"), "tag": i.get("tag"), "type": i.get("type"), "port": i.get("port")}
                                   for i in p.get("inbounds", [])]} for p in profiles],
        "squads": [{"uuid": s.get("uuid"), "name": s.get("name"), "members": (s.get("info") or {}).get("membersCount"),
                    "inbounds": [i.get("tag") for i in s.get("inbounds", [])],
                    "inbound_uuids": [i.get("uuid") for i in s.get("inbounds", [])]} for s in squads],
        "hosts": [{"uuid": h.get("uuid"), "remark": h.get("remark"), "address": h.get("address"), "port": h.get("port"),
                   "disabled": bool(h.get("isDisabled")), "sni": h.get("sni") or "", "host": h.get("host") or "",
                   "path": h.get("path") or "", "tag": h.get("tag") or "",
                   "profile": (h.get("inbound") or {}).get("configProfileUuid") or "",
                   "inbound": (h.get("inbound") or {}).get("configProfileInboundUuid") or ""} for h in hosts],
    }


class HostIn(BaseModel):
    disabled: bool


class HostEdit(BaseModel):
    remark: str = Field(..., min_length=1, max_length=40)
    address: str = Field(..., min_length=1, max_length=255)
    port: int = Field(..., ge=1, le=65535)
    profile: str = Field(..., min_length=1, max_length=64)
    inbound: str = Field(..., min_length=1, max_length=64)
    sni: str = Field("", max_length=255)
    host: str = Field("", max_length=255)
    path: str = Field("", max_length=255)
    tag: str = Field("", max_length=32, pattern=r"^[A-Z0-9_:]*$")


class SquadEdit(BaseModel):
    name: str = Field(..., min_length=2, max_length=30, pattern=r"^[A-Za-z0-9_\- ]+$")
    inbounds: list[str] = Field(default_factory=list, max_length=200)


def host_body(payload: HostEdit) -> dict:
    body = {"remark": payload.remark, "address": payload.address, "port": payload.port,
            "inbound": {"configProfileUuid": payload.profile, "configProfileInboundUuid": payload.inbound}}
    for key in ("sni", "host", "path"):
        body[key] = getattr(payload, key) or None
    body["tag"] = payload.tag or None
    return body


async def create_host(panel, payload: HostEdit) -> dict:
    return await panel._request("POST", "/api/hosts", json=host_body(payload))


async def update_host(panel, host_uuid: str, payload: HostEdit) -> dict:
    return await panel._request("PATCH", "/api/hosts", json={"uuid": host_uuid, **host_body(payload)})


async def delete_host(panel, host_uuid: str) -> dict:
    return await panel._request("DELETE", f"/api/hosts/{host_uuid}")


async def create_squad(panel, payload: SquadEdit) -> dict:
    return await panel._request("POST", "/api/internal-squads", json={"name": payload.name, "inbounds": payload.inbounds})


async def update_squad(panel, squad_uuid: str, payload: SquadEdit) -> dict:
    return await panel._request("PATCH", "/api/internal-squads", json={"uuid": squad_uuid, "name": payload.name, "inbounds": payload.inbounds})


async def delete_squad(panel, squad_uuid: str) -> dict:
    return await panel._request("DELETE", f"/api/internal-squads/{squad_uuid}")


async def _call(fn, *args):
    from .remnawave import RemnawaveClient
    try:
        return await fn(RemnawaveClient(), *args)
    except Exception as exc:  # noqa: BLE001 — the panel's own message (validation, conflict) goes to the admin
        raise HTTPException(502, f"Remnawave: {str(exc)[:300]}") from exc


@router.get("/api/admin/panel/overview")
async def panel_overview(admin=Depends(require_permission("ops.diagnostics"))):
    try:
        return await overview()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Remnawave: {str(exc)[:200]}") from exc


@router.put("/api/admin/panel/hosts/{host_uuid}")
async def set_host(host_uuid: str, payload: HostIn, admin=Depends(require_permission("provision_nodes"))):
    from .remnawave import RemnawaveClient
    action = "disable" if payload.disabled else "enable"
    try:
        await RemnawaveClient()._request("POST", f"/api/hosts/bulk/{action}", json={"uuids": [host_uuid]})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Remnawave: {str(exc)[:200]}") from exc
    return {"ok": True}


@router.post("/api/admin/panel/squads/{squad_uuid}/{action}")
async def squad_bulk(squad_uuid: str, action: str, admin=Depends(require_permission("provision_nodes"))):
    from .remnawave import RemnawaveClient
    panel = RemnawaveClient()
    if action == "add-all":
        await panel.squad_add_all_users(squad_uuid)
    elif action == "remove-all":
        await panel.squad_remove_all_users(squad_uuid)
    else:
        raise HTTPException(404, "Unknown action")
    return {"ok": True}


@router.post("/api/admin/panel/hosts")
async def host_create(payload: HostEdit, admin=Depends(require_permission("provision_nodes"))):
    return {"ok": True, "host": await _call(create_host, payload)}


@router.patch("/api/admin/panel/hosts/{host_uuid}")
async def host_update(host_uuid: str, payload: HostEdit, admin=Depends(require_permission("provision_nodes"))):
    return {"ok": True, "host": await _call(update_host, host_uuid, payload)}


@router.delete("/api/admin/panel/hosts/{host_uuid}")
async def host_delete(host_uuid: str, admin=Depends(require_permission("provision_nodes"))):
    await _call(delete_host, host_uuid)
    return {"ok": True}


@router.post("/api/admin/panel/squads")
async def squad_create(payload: SquadEdit, admin=Depends(require_permission("provision_nodes"))):
    return {"ok": True, "squad": await _call(create_squad, payload)}


@router.patch("/api/admin/panel/squads/{squad_uuid}")
async def squad_update(squad_uuid: str, payload: SquadEdit, admin=Depends(require_permission("provision_nodes"))):
    return {"ok": True, "squad": await _call(update_squad, squad_uuid, payload)}


@router.delete("/api/admin/panel/squads/{squad_uuid}")
async def squad_delete(squad_uuid: str, admin=Depends(require_permission("provision_nodes"))):
    await _call(delete_squad, squad_uuid)
    return {"ok": True}
