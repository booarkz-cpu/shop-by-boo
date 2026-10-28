"""Node autoscaling: add a VPN node when the existing ones are crowded, remove an added one when it is quiet.

The load is the number of users online per online node (Remnawave reports it). Every minute, with the node monitor:

* crowded — above ``up_at`` for ``sustain_minutes`` in a row, below ``max_nodes`` and after ``cooldown_minutes`` since
  the last change → **add a node**; fewer online nodes than ``min_nodes`` → add at once;
* quiet — below ``down_at`` for ``sustain_minutes`` → **remove** one node that the autoscaler added itself (never a
  node the owner created by hand), the one with the fewest users.

Mode ``recommend`` (the default) only sends the owner a Telegram message with what to do and why. Mode ``auto``
creates the server at Hetzner Cloud with a cloud-init that starts Remnawave Node, registers it in the panel with the
chosen config profile and inbounds, and does the reverse when removing. Secrets stay in ``.env``:
``HETZNER_API_TOKEN``; the node key is taken from the panel (``GET /api/keygen``) unless ``REMNANODE_SECRET_KEY``
overrides it.

The Remnawave calls (keygen, node create with a config profile, node delete) are checked against a real panel in CI
(tests/live/test_remnawave_live.py); the Hetzner Cloud calls follow its public reference and are tested with a mock.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.autoscale")
router = APIRouter()

CONFIG_KEY = "nodes.autoscale.config"
STATE_KEY = "nodes.autoscale.state"
HETZNER = "https://api.hetzner.cloud/v1"
REPEAT_RECOMMENDATION = timedelta(hours=6)
DEFAULT_CONFIG = {
    "enabled": False, "mode": "recommend", "up_at": 150, "down_at": 40, "min_nodes": 1, "max_nodes": 10,
    "sustain_minutes": 15, "cooldown_minutes": 60, "cpu_up_at": 0, "cpu_down_at": 0,
    "server_type": "cx22", "location": "hel1", "image": "ubuntu-24.04", "ssh_key": "",
    "node_port": 2222, "country_code": "FI", "config_profile_uuid": "", "inbound_uuids": [], "name_prefix": "auto",
}


class ConfigIn(BaseModel):
    enabled: bool
    mode: str = Field("recommend", pattern="^(recommend|auto)$")
    up_at: int = Field(150, ge=1, le=100000)
    down_at: int = Field(40, ge=0, le=100000)
    min_nodes: int = Field(1, ge=0, le=500)
    max_nodes: int = Field(10, ge=1, le=500)
    sustain_minutes: int = Field(15, ge=1, le=1440)
    cooldown_minutes: int = Field(60, ge=5, le=10080)
    cpu_up_at: int = Field(0, ge=0, le=100)  # node agents' average CPU, %: 0 → not used
    cpu_down_at: int = Field(0, ge=0, le=100)
    server_type: str = Field("cx22", max_length=40, pattern=r"^[a-z0-9-]+$")
    location: str = Field("hel1", max_length=40, pattern=r"^[a-z0-9-]+$")
    image: str = Field("ubuntu-24.04", max_length=60, pattern=r"^[a-z0-9.-]+$")
    ssh_key: str = Field("", max_length=80)
    node_port: int = Field(2222, ge=1, le=65535)
    country_code: str = Field("FI", min_length=2, max_length=2)
    config_profile_uuid: str = Field("", max_length=64, pattern=r"^[0-9a-fA-F-]*$")
    inbound_uuids: list[str] = Field(default_factory=list, max_length=20)
    name_prefix: str = Field("auto", min_length=1, max_length=20, pattern=r"^[a-z0-9-]+$")


async def _load(db, key, default):
    from .node_health import _load as load
    return await load(db, key, default)


async def _save(db, key, value):
    from .node_health import _save as save
    await save(db, key, value)


def provider_ready() -> dict:
    # The node key comes from REMNANODE_SECRET_KEY or, without it, from the panel itself (GET /api/keygen).
    return {"hetzner_token": bool(os.getenv("HETZNER_API_TOKEN")), "node_secret": True}


def parse_cpu(value) -> float | None:
    try:
        number = float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None
    return number * 100 if number <= 1 else number


async def fleet_cpu(db: AsyncSession, now: datetime) -> float | None:
    """Average CPU of node agents that reported in the last 5 minutes (node_agents.cpu, «23%» or «0.23»)."""
    from sqlalchemy import select

    from .models import NodeAgent
    values = [parse_cpu(a.cpu) for a in (await db.execute(select(NodeAgent).where(
        NodeAgent.enabled.is_(True), NodeAgent.last_seen_at >= now - timedelta(minutes=5)))).scalars()]
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def decide(config: dict, nodes: list[dict], state: dict, now: datetime, cpu: float | None = None) -> tuple[dict, dict]:
    """Pure decision: ({action, reason, load, online, cpu}, new state). ``action`` is "up", "down" or None.
    Crowded = users per node above ``up_at`` or agents' CPU above ``cpu_up_at``; quiet = both below their lower marks."""
    state = dict(state)
    online = [n for n in nodes if n.get("status") == "online"]
    users = sum(int(n.get("users_online") or 0) for n in online)
    load = round(users / len(online), 1) if online else 0.0
    info = {"action": None, "reason": "", "load": load, "online": len(online), "users": users, "cpu": cpu}
    cpu_up, cpu_down = int(config.get("cpu_up_at") or 0), int(config.get("cpu_down_at") or 0)
    hot_cpu = bool(cpu_up and cpu is not None and cpu > cpu_up)
    cool_cpu = not cpu_down or cpu is None or cpu < cpu_down
    last = datetime.fromisoformat(state["last_action_at"]) if state.get("last_action_at") else None
    cooled = not last or now - last >= timedelta(minutes=int(config["cooldown_minutes"]))
    sustain = timedelta(minutes=int(config["sustain_minutes"]))
    mine = {c["node_uuid"] for c in state.get("created", []) if c.get("node_uuid")}

    if load > config["up_at"] or hot_cpu:
        state.setdefault("high_since", now.isoformat())
    else:
        state.pop("high_since", None)
    if load < config["down_at"] and cool_cpu and not hot_cpu:
        state.setdefault("low_since", now.isoformat())
    else:
        state.pop("low_since", None)

    if len(online) < int(config["min_nodes"]) and len(online) < int(config["max_nodes"]) and cooled:
        info.update(action="up", reason=f"онлайн {len(online)} нод при минимуме {config['min_nodes']}")
    elif state.get("high_since") and now - datetime.fromisoformat(state["high_since"]) >= sustain:
        if len(online) >= int(config["max_nodes"]):
            info["reason"] = f"нагрузка {load} на ноду, но уже максимум {config['max_nodes']} нод"
        elif cooled:
            why = f"CPU нод {cpu}% (порог {cpu_up}%)" if hot_cpu and load <= config["up_at"] else f"{load} пользователей на ноду (порог {config['up_at']})"
            info.update(action="up", reason=f"{why} дольше {config['sustain_minutes']} мин")
    elif state.get("low_since") and now - datetime.fromisoformat(state["low_since"]) >= sustain and len(online) > int(config["min_nodes"]):
        candidates = sorted((n for n in online if n.get("uuid") in mine), key=lambda n: int(n.get("users_online") or 0))
        if candidates and cooled:
            info.update(action="down", node=candidates[0],
                        reason=f"{load} пользователей на ноду дольше {config['sustain_minutes']} мин (порог {config['down_at']})")
    return info, state


def cloud_init(config: dict, secret: str) -> str:
    secret = secret.replace("'", "")
    return "\n".join([
        "#cloud-config",
        "runcmd:",
        "  - curl -fsSL https://get.docker.com | sh",
        f"  - docker run -d --name remnanode --restart always --network host -e NODE_PORT={int(config['node_port'])} "
        f"-e 'SECRET_KEY={secret}' remnawave/node:latest",
    ]) + "\n"


async def _hetzner(method: str, path: str, client: httpx.AsyncClient | None = None, **kwargs) -> dict:
    headers = {"Authorization": f"Bearer {os.getenv('HETZNER_API_TOKEN', '')}"}
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        response = await client.request(method, HETZNER + path, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}
    finally:
        if own:
            await client.aclose()


async def scale_up(config: dict, now: datetime, panel=None, client=None) -> dict:
    from .remnawave import RemnawaveClient
    name = f"{config['name_prefix']}-{now:%m%d-%H%M}"
    panel = panel or RemnawaveClient()
    secret = os.getenv("REMNANODE_SECRET_KEY") or await panel.node_secret_key()
    if not secret:
        raise RuntimeError("панель не выдала ключ ноды (GET /api/keygen)")
    body = {"name": name, "server_type": config["server_type"], "location": config["location"], "image": config["image"],
            "user_data": cloud_init(config, secret), "labels": {"corgi": "autoscale"}}
    if config.get("ssh_key"):
        body["ssh_keys"] = [config["ssh_key"]]
    server = (await _hetzner("POST", "/servers", client, json=body))["server"]
    ip = server["public_net"]["ipv4"]["ip"]
    node = {"name": name, "address": ip, "port": int(config["node_port"]), "countryCode": config["country_code"].upper()}
    if config.get("config_profile_uuid"):
        node["configProfile"] = {"activeConfigProfileUuid": config["config_profile_uuid"], "activeInbounds": config.get("inbound_uuids") or []}
    try:
        created = await panel.create_node(node) or {}
    except Exception:
        # A server the panel does not know would only cost money: remove it and report the panel error.
        await _hetzner("DELETE", f"/servers/{server['id']}", client)
        raise
    return {"server_id": server["id"], "node_uuid": str(created.get("uuid") or ""), "name": name, "ip": ip, "created_at": now.isoformat()}


async def scale_down(entry: dict, panel=None, client=None) -> None:
    from .remnawave import RemnawaveClient
    if entry.get("node_uuid"):
        await (panel or RemnawaveClient()).delete_node(entry["node_uuid"])
    await _hetzner("DELETE", f"/servers/{entry['server_id']}", client)


async def tick(db: AsyncSession, now: datetime | None = None, *, nodes=None, sender=None, panel=None, client=None) -> dict:
    """One pass (called by the node monitor every minute)."""
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    if not config["enabled"]:
        return {"action": None, "reason": "выключено"}
    now = now or datetime.utcnow()
    if nodes is None:
        from .node_health import node_snapshot
        snap = await node_snapshot()
        if snap.get("error"):
            return {"action": None, "reason": snap["error"]}
        nodes = snap["nodes"]
    if sender is None:
        from .ops_alerts import send as sender
    state = await _load(db, STATE_KEY, {})
    cpu = await fleet_cpu(db, now) if (config.get("cpu_up_at") or config.get("cpu_down_at")) else None
    info, state = decide(config, [n for n in nodes if n.get("status") != "disabled"], state, now, cpu)
    action = info["action"]
    if action:
        ready = provider_ready()
        if config["mode"] == "auto" and all(ready.values()):
            history = state.setdefault("history", [])
            try:
                if action == "up":
                    entry = await scale_up(config, now, panel, client)
                    state.setdefault("created", []).append(entry)
                    await sender(f"➕ Добавлена нода {entry['name']} ({entry['ip']}): {info['reason']}.")
                else:
                    entry = next(c for c in state.get("created", []) if c.get("node_uuid") == info["node"]["uuid"])
                    await scale_down(entry, panel, client)
                    state["created"] = [c for c in state["created"] if c is not entry]
                    await sender(f"➖ Удалена нода {entry['name']}: {info['reason']}.")
                history.append({"at": now.isoformat(), "action": action, "reason": info["reason"], "ok": True})
                state["last_action_at"] = now.isoformat()
                state.pop("high_since", None)
                state.pop("low_since", None)
            except Exception as exc:  # noqa: BLE001 — reported, retried after the cooldown
                logger.warning("autoscale %s failed: %s", action, exc)
                history.append({"at": now.isoformat(), "action": action, "reason": str(exc)[:200], "ok": False})
                state["last_action_at"] = now.isoformat()
                await sender(f"⚠️ Автомасштабирование: не удалось {'добавить' if action == 'up' else 'удалить'} ноду: {str(exc)[:200]}")
            state["history"] = history[-20:]
        else:
            last = state.get("recommended", {})
            when = datetime.fromisoformat(last["at"]) if last.get("at") else None
            if last.get("action") != action or not when or now - when >= REPEAT_RECOMMENDATION:
                what = "добавить ноду" if action == "up" else f"убрать ноду {info['node'].get('name')}"
                missing = "" if config["mode"] == "recommend" else " (режим «авто» ждёт HETZNER_API_TOKEN в .env)"
                await sender(f"📈 Рекомендация: {what} — {info['reason']}{missing}. Серверы → Автомасштабирование.")
                state["recommended"] = {"action": action, "at": now.isoformat()}
    else:
        state.pop("recommended", None)
    state["last"] = {**{k: v for k, v in info.items() if k != "node"}, "at": now.isoformat()}
    await _save(db, STATE_KEY, state)
    await db.commit()
    return info


@router.get("/api/admin/nodes/autoscale")
async def get_autoscale(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    state = await _load(db, STATE_KEY, {})
    return {"config": await _load(db, CONFIG_KEY, DEFAULT_CONFIG), "provider": provider_ready(), "last": state.get("last"),
            "created": state.get("created", []), "history": list(reversed(state.get("history", [])))}


@router.put("/api/admin/nodes/autoscale")
async def put_autoscale(payload: ConfigIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    from fastapi import HTTPException

    from .main import audit
    if payload.down_at >= payload.up_at:
        raise HTTPException(400, "Порог уменьшения должен быть ниже порога увеличения")
    if payload.min_nodes > payload.max_nodes:
        raise HTTPException(400, "Минимум нод больше максимума")
    value = payload.model_dump()
    await _save(db, CONFIG_KEY, value)
    await audit(db, "nodes.autoscale", admin.email, None, value)
    await db.commit()
    return {"ok": True}
