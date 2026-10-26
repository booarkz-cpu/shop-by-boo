"""Corgi Lusi v16 control-plane routes.

Earlier releases answered these routes with made-up data: a "signed" tunnel profile
without any keys, a node registration whose token was never stored, a failover that
did nothing. They are kept only to tell old clients where the real mechanism is.

* VPN access is issued by Remnawave: ``GET /api/me/subscription`` returns the
  subscription link.
* Nodes are managed in Remnawave; shop agents are created in
  ``POST /api/admin/platform/agents`` and report through ``/api/agent/*``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()

GONE_ACCESS = "Профиль туннеля выдаёт Remnawave: используйте ссылку подписки из GET /api/me/subscription"
GONE_NODES = "Узлы управляются в Remnawave, агенты узлов — в POST /api/admin/platform/agents"


async def _authenticated(request: Request, db: AsyncSession) -> None:
    from .main import user_from_token
    await user_from_token(request, db)


@router.post("/api/me/v16/tunnel-profile")
async def tunnel_profile(request: Request, db: AsyncSession = Depends(get_db)):
    await _authenticated(request, db)
    raise HTTPException(410, GONE_ACCESS)


@router.post("/api/me/v16/roaming")
async def roaming(request: Request, db: AsyncSession = Depends(get_db)):
    await _authenticated(request, db)
    raise HTTPException(410, GONE_ACCESS)


@router.post("/api/admin/v16/nodes/register")
async def register_node(admin=Depends(require_permission("provision_nodes"))):
    raise HTTPException(410, GONE_NODES)


@router.post("/api/admin/v16/nodes/{node_name}/failover")
async def node_failover(node_name: str, admin=Depends(require_permission("provision_nodes"))):
    raise HTTPException(410, GONE_NODES)


@router.get("/api/public/v16/release")
async def release():
    from .main import APP_VERSION
    return {
        "product": "Corgi Lusi",
        "platform": "Corgi Lusi Platform",
        "release": APP_VERSION,
        "channels": ["stable"],
        "languages": ["ru", "en", "uk"],
        "privacy": {"private_traffic_inspection": False, "payload_logging": False},
    }
