"""Remnawave panel from the shop admin: config profiles with their inbounds, Internal Squads (members, inbounds) and
hosts, with the everyday actions — turn a host on or off, add every customer to a squad or take them out.
Editing the Xray config itself stays in the panel. Calls are checked against a real panel in CI
(tests/live/test_remnawave_live.py). «Серверы → Панель Remnawave» (web) and the mobile admin card.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

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
                    "inbounds": [i.get("tag") for i in s.get("inbounds", [])]} for s in squads],
        "hosts": [{"uuid": h.get("uuid"), "remark": h.get("remark"), "address": h.get("address"), "port": h.get("port"),
                   "disabled": bool(h.get("isDisabled"))} for h in hosts],
    }


class HostIn(BaseModel):
    disabled: bool


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
