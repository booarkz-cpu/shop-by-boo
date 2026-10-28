import logging
import asyncio
import httpx
import time
from datetime import datetime
from .config import settings

logger = logging.getLogger("remnawave.remnawave")

_SECRET_MARKERS = (
    "password",
    "token",
    "secret",
    "subscription",
    "trojan",
    "vless",
    "shortuuid",
    "suburl",
    "connectionkey",
    "rawkey",
    "sspassword",
)


def redact_remote(value):
    """Drop VPN credentials from a Remnawave payload before it reaches a read-only admin response."""
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("_", "")
            if any(marker in normalized for marker in _SECRET_MARKERS):
                continue
            clean[key] = redact_remote(item)
        return clean
    if isinstance(value, list):
        return [redact_remote(item) for item in value]
    return value

class RemnawaveError(RuntimeError):
    """A validated Remnawave request or reconciliation failure."""

_KEEP = object()


def unwrap(body):
    """Remnawave answers ``{"response": <payload>}`` (backend contract 2.x and 3.x).

    Callers work with the payload itself: a user object, ``{"users": [...], "total": N}``,
    a list of nodes. A body that is not wrapped is returned as is."""
    if isinstance(body, dict) and set(body) == {"response"}:
        return body["response"]
    return body


class RemnawaveCircuitOpen(RemnawaveError):
    """Remote calls are temporarily blocked after repeated failures."""

class RemnawaveClient:
    _shared_client: httpx.AsyncClient | None = None
    _client_lock: asyncio.Lock | None = None

    def __init__(self):
        self.base=settings.remnawave_url.rstrip("/")
        self.headers={
            "Authorization":f"Bearer {settings.remnawave_token}",
            "Accept":"application/json",
            "Content-Type":"application/json",
        }
        if self.base.startswith("http://"):
            # A panel reached over the internal Docker network (http://remnawave:3000) refuses requests that do not
            # look proxied («Reverse proxy and HTTPS are required»): the shop says it is behind its own HTTPS proxy.
            self.headers.update({"X-Forwarded-Proto":"https","X-Forwarded-For":"127.0.0.1"})

    @classmethod
    async def _get_shared_client(cls) -> httpx.AsyncClient:
        if cls._shared_client is not None and not cls._shared_client.is_closed:
            return cls._shared_client
        if cls._client_lock is None:
            cls._client_lock = asyncio.Lock()
        async with cls._client_lock:
            if cls._shared_client is None or cls._shared_client.is_closed:
                cls._shared_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(15.0, connect=5.0),
                    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
                    trust_env=False,
                )
            return cls._shared_client

    @classmethod
    async def close_shared_client(cls):
        if cls._shared_client is not None and not cls._shared_client.is_closed:
            await cls._shared_client.aclose()
        cls._shared_client = None

    async def _request(self,method,path,**kwargs):
        # Redis-backed circuit breaker prevents retry storms when Remnawave is unavailable.
        from .main import redis_client
        fail_key="rw:cb:fail"; open_key="rw:cb:open"
        if redis_client is not None:
            try:
                if await redis_client.get(open_key): raise RemnawaveCircuitOpen("Remnawave circuit breaker is open")
            except RemnawaveCircuitOpen: raise
            except Exception as exc:
                logger.warning("Non-critical operation failed: %s", exc)
        from . import panel_api_stats
        started=time.monotonic(); status=599
        try:
            c=await self._get_shared_client()
            r=await c.request(method,f"{self.base}{path}",headers=self.headers,**kwargs)
            status=r.status_code
            if not r.is_error:
                ref=panel_api_stats.user_ref(method,path,kwargs)
                if ref: await panel_api_stats.remember_write(ref)
            if r.is_error:
                raise RemnawaveError(f"{method} {path}: {r.status_code}: {r.text[:1000]}")
            if redis_client is not None:
                try: await redis_client.delete(fail_key)
                except Exception as exc:
                    logger.warning("Redis circuit-breaker reset failed: %s", exc)
            panel_api_stats.record(None,method,path,status,(time.monotonic()-started)*1000)
            return unwrap(r.json()) if r.content else {}
        except Exception:
            panel_api_stats.record(None,method,path,status,(time.monotonic()-started)*1000)
            if redis_client is not None:
                try:
                    n=int(await redis_client.incr(fail_key)); await redis_client.expire(fail_key,300)
                    if n >= settings.remnawave_cb_failures:
                        await redis_client.set(open_key,"1",ex=settings.remnawave_cb_cooldown)
                except Exception as exc:
                    logger.warning("Non-critical operation failed: %s", exc)
            raise

    async def get_user(self,user_id:int|str):
        return await self._request("GET",f"/api/users/{user_id}")

    async def get_user_by_username(self,username:str):
        return await self._request("GET",f"/api/users/by-username/{username}")

    async def stream_users(self,telegram_id=None,cursor=None,size=250,status=None):
        params={"size":min(max(size,1),1000)}
        if telegram_id is not None: params["telegramId"]=telegram_id
        if cursor is not None: params["cursor"]=cursor
        if status: params["status"]=status
        return await self._request("GET","/api/users/stream",params=params)

    async def list_users(self,start=0,size=25):
        return await self._request("GET","/api/users",
                                   params={"start":start,"size":min(size,1000)})

    async def create_user(self,username,expire_at,traffic_limit_bytes=0,
                          traffic_limit_strategy="NO_RESET",
                          active_internal_squads=None,telegram_id=None,device_limit=None):
        payload={
            "username":username,
            "expireAt":expire_at.isoformat(),
            "trafficLimitBytes":traffic_limit_bytes,
            "trafficLimitStrategy":traffic_limit_strategy,
        }
        if active_internal_squads is not None:
            payload["activeInternalSquads"]=active_internal_squads
        if telegram_id is not None:
            payload["telegramId"]=telegram_id
        if device_limit:
            # Enforced by the panel when its HWID device limit is turned on; otherwise ignored.
            payload["hwidDeviceLimit"]=int(device_limit)
        return await self._request("POST","/api/users",json=payload)


    async def get_expiry(self,user_id:int|str):
        data=await self.get_user(user_id)
        value=data.get("expireAt") or data.get("expire_at") or data.get("expiresAt") or data.get("expires_at")
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z","+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    async def extend_idempotent(self,user_id:int|str,days:int,expected_before:datetime,expected_after:datetime):
        current=await self.get_expiry(user_id)
        if current and current >= expected_after:
            return {"already_applied":True,"user":None,"expires_at":current}
        # Never blindly extend when the remote expiry has advanced beyond the
        # operation's original starting point. That means another operation may have
        # won the race (or an earlier request may have succeeded before its response
        # was lost). Extending again would turn an uncertain retry into a double grant.
        if current and current > expected_before:
            raise RemnawaveError("Remote expiry advanced unexpectedly; reconciliation is required")
        await self.extend_user(user_id,days)
        verified=await self.get_expiry(user_id)
        if not verified or verified < expected_after:
            raise RemnawaveError("Remote extension could not be verified")
        return {"already_applied":False,"user":None,"expires_at":verified}

    async def patch_user(self,user_id:int|str,payload:dict):
        body=dict(payload); body["id"]=user_id
        return await self._request("PATCH","/api/users",json=body)

    async def extend_user(self,user_id:int|str,days:int):
        return await self._request("POST",f"/api/users/{user_id}/actions/extend",
                                   json={"days":days})

    async def update_entitlements(self,user_id:int|str,traffic_limit_gb:int|None,profile_id:str|None,device_limit=_KEEP):
        # None is an explicit unlimited/empty entitlement, not "leave the old
        # remote value untouched". Otherwise downgrading to an unlimited/no-profile
        # plan would silently retain the previous customer's restrictive quota or
        # privileged internal squad. This must mirror create_user semantics.
        payload={"trafficLimitBytes": int(traffic_limit_gb)*1024**3 if traffic_limit_gb is not None else 0,
                 "activeInternalSquads": [profile_id] if profile_id else []}
        if device_limit is not _KEEP:
            # None returns the user to the panel's default HWID limit.
            payload["hwidDeviceLimit"]=int(device_limit) if device_limit else None
        return await self.patch_user(user_id,payload)

    async def disable_user(self,user_id:int|str):
        return await self._request("POST",f"/api/users/{user_id}/actions/disable")

    async def enable_user(self,user_id:int|str):
        return await self._request("POST",f"/api/users/{user_id}/actions/enable")

    async def reset_traffic(self,user_id:int|str):
        return await self._request("POST",f"/api/users/{user_id}/actions/reset-traffic")

    async def get_subscription(self,user_id:int|str):
        return await self._request("GET",f"/api/subscriptions/by-id/{user_id}")

    async def get_connection_keys(self,user_id:int|str):
        return await self._request("GET",f"/api/subscriptions/connection-keys/{user_id}")

    async def accessible_nodes(self,user_id:int|str):
        return await self._request("GET",f"/api/users/{user_id}/accessible-nodes")

    async def list_internal_squads(self):
        return await self._request("GET","/api/internal-squads")
    async def squad_add_all_users(self,squad_uuid:str):
        """Every user joins the Internal Squad (its inbounds appear in their subscriptions); the panel runs it as a job."""
        return await self._request("POST",f"/api/internal-squads/{squad_uuid}/bulk-actions/add-users")
    async def squad_remove_all_users(self,squad_uuid:str):
        return await self._request("DELETE",f"/api/internal-squads/{squad_uuid}/bulk-actions/remove-users")

    async def hwid_devices(self,user_id:int|str)->list[dict]:
        """Devices (HWID) the panel has seen for this user; empty when the panel's HWID limit is off."""
        data=await self._request("GET",f"/api/hwid/devices/{user_id}")
        if isinstance(data,dict):
            data=data.get("devices") if isinstance(data.get("devices"),list) else data.get("response",data)
            if isinstance(data,dict): data=data.get("devices") or []
        return [x for x in (data or []) if isinstance(x,dict)]

    async def reset_hwid_devices(self,user_id:int|str):
        return await self._request("POST","/api/hwid/devices/delete-all",json={"userUuid":str(user_id)})

    async def restart_node(self,node_uuid:str):
        # The panel validates the body: {"forceRestart": bool} is required (no body → 400; checked live in CI).
        return await self._request("POST",f"/api/nodes/{node_uuid}/actions/restart",json={"forceRestart":False})

    async def restart_all_nodes(self):
        return await self._request("POST","/api/nodes/actions/restart-all",json={"forceRestart":False})

    async def node_secret_key(self)->str:
        """The SECRET_KEY a new node container starts with (panel «Создать ноду» dialog, GET /api/keygen)."""
        out=await self._request("GET","/api/keygen")
        return str((out or {}).get("secretKey") or (out or {}).get("pubKey") or "")

    async def create_node(self,payload:dict):
        return await self._request("POST","/api/nodes",json=payload)

    async def delete_node(self,node_uuid:str):
        return await self._request("DELETE",f"/api/nodes/{node_uuid}")

    async def list_nodes(self,start=0,size=25):
        return await self._request("GET","/api/nodes",
                                   params={"start":start,"size":min(size,1000)})
