"""v28.98.0 (stage 20, N7): Cloudflare in front of the node's XHTTP and of the subscription domain — switched on and off
from «Установка» (owner's decision of 2026-11-07).

The owner's API token (Zone → DNS → Edit, Zone → Zone Settings → Read, Zone → Config Rules → Edit) is kept in the
installation's encrypted secrets. Everything here is a call of the Cloudflare API from the shop (no SSH):

* ``zone_of`` — the zone a domain belongs to (the longest suffix the token sees);
* ``apply_records`` — A records of the CDN domain → the node addresses and of the subscription domain → its server,
  with «proxied» on or off; what was there before is returned for «undo»;
* ``ensure_full_ssl`` — Cloudflare talks to the node over TLS with the node's own certificate (the SelfSteal one), so the
  CDN domain needs SSL mode «Full»: a configuration rule of this hostname only (the rest of the owner's zone keeps its
  mode); the rule is ours by its description and goes away with «off».

``REQUEST`` is the seam the tests replace."""
from __future__ import annotations

import ipaddress
import re

import httpx

API = "https://api.cloudflare.com/client/v4"
TOKEN = re.compile(r"^[A-Za-z0-9_-]{30,80}$")
RULE_TAG = "corgi-cdn"


class CloudflareError(RuntimeError):
    pass


async def _request(method: str, path: str, token: str, body: dict | None = None, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.request(method, API + path, json=body, params=params, headers={"Authorization": f"Bearer {token}"})
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or not data.get("success", False):
        errors = "; ".join(str(e.get("message", e)) for e in data.get("errors") or []) or f"HTTP {r.status_code}"
        raise CloudflareError(f"Cloudflare: {errors}")
    return data


REQUEST = _request


async def call(method: str, path: str, token: str, body: dict | None = None, params: dict | None = None) -> dict:
    return await REQUEST(method, path, token, body, params)


async def check_token(token: str) -> None:
    if not TOKEN.match(token or ""):
        raise CloudflareError("Токен Cloudflare: 30–80 символов из личного кабинета (My Profile → API Tokens)")
    data = await call("GET", "/user/tokens/verify", token)
    if (data.get("result") or {}).get("status") != "active":
        raise CloudflareError("Токен Cloudflare не активен")


async def zone_of(token: str, domain: str) -> dict:
    labels = domain.split(".")
    for i in range(len(labels) - 1):
        name = ".".join(labels[i:])
        found = (await call("GET", "/zones", token, params={"name": name})).get("result") or []
        if found:
            return {"id": found[0]["id"], "name": found[0]["name"]}
    raise CloudflareError(f"Зона домена {domain} не найдена этим токеном Cloudflare")


async def records(token: str, zone: str, name: str) -> list[dict]:
    data = await call("GET", f"/zones/{zone}/dns_records", token, params={"name": name, "type": "A", "per_page": 50})
    return [{"id": r["id"], "content": r["content"], "proxied": bool(r.get("proxied"))} for r in data.get("result") or []]


async def apply_records(token: str, name: str, addresses: list[str], proxied: bool) -> dict:
    """A records ``name`` → exactly ``addresses`` with «proxied». Returns ``{"zone", "before"}`` for «undo»."""
    for ip in addresses:
        if ipaddress.ip_address(ip).version != 4:
            raise CloudflareError(f"{ip}: нужен IPv4-адрес")
    zone = (await zone_of(token, name))["id"]
    before = await records(token, zone, name)
    keep = {r["content"]: r for r in before}
    for ip in addresses:
        if ip in keep:
            if keep[ip]["proxied"] != proxied:
                await call("PATCH", f"/zones/{zone}/dns_records/{keep[ip]['id']}", token, {"proxied": proxied})
        else:
            await call("POST", f"/zones/{zone}/dns_records", token, {"type": "A", "name": name, "content": ip, "proxied": proxied,
                                                                      "ttl": 1, "comment": RULE_TAG})
    for ip, r in keep.items():
        if ip not in addresses:
            await call("DELETE", f"/zones/{zone}/dns_records/{r['id']}", token)
    return {"zone": zone, "name": name, "before": before}


async def restore_records(token: str, saved: dict) -> None:
    """«undo» of ``apply_records``: the records of the name as they were."""
    zone, name = saved["zone"], saved["name"]
    now = await records(token, zone, name)
    for r in now:
        await call("DELETE", f"/zones/{zone}/dns_records/{r['id']}", token)
    for r in saved["before"]:
        await call("POST", f"/zones/{zone}/dns_records", token, {"type": "A", "name": name, "content": r["content"], "proxied": r["proxied"], "ttl": 1})


def _rule(host: str) -> dict:
    return {"description": f"{RULE_TAG} {host}", "expression": f'(http.host eq "{host}")', "action": "set_config",
            "action_parameters": {"ssl": "full"}, "enabled": True}


async def _entrypoint(token: str, zone: str) -> list[dict]:
    try:
        data = await call("GET", f"/zones/{zone}/rulesets/phases/http_config_settings/entrypoint", token)
    except CloudflareError as exc:
        if "not found" in str(exc).lower() or "HTTP 404" in str(exc):
            return []
        raise
    return list((data.get("result") or {}).get("rules") or [])


async def set_full_ssl(token: str, host: str, on: bool) -> None:
    """A configuration rule «SSL: Full» for ``host`` only; other rules of the owner stay as they are."""
    zone = (await zone_of(token, host))["id"]
    rules = [r for r in await _entrypoint(token, zone) if r.get("description") != f"{RULE_TAG} {host}"]
    if on:
        rules.append(_rule(host))
    keep = [{k: r[k] for k in ("description", "expression", "action", "action_parameters", "enabled") if k in r} for r in rules]
    await call("PUT", f"/zones/{zone}/rulesets/phases/http_config_settings/entrypoint", token, {"rules": keep})


async def zone_setting(token: str, domain: str, setting: str) -> str:
    zone = (await zone_of(token, domain))["id"]
    return str(((await call("GET", f"/zones/{zone}/settings/{setting}", token)).get("result") or {}).get("value") or "")
