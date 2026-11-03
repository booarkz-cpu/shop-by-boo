"""Domain Manager, certificates and proxy routes (v28.67, stage 11; docs/ru/new/SUBSCRIPTION_DOMAIN.md).

* **Domains.** The administrator adds a domain with its purpose (subscription portal, Remnawave panel, subscription
  page, node) and who serves it: ``shop`` — the shop's own Caddy (deploy/Caddyfile issues the certificate on demand
  after asking ``/caddy/ask``, so a domain added here works without editing files or restarting anything);
  ``remnawave`` — Caddy on a server of the installation wizard; ``external`` — only checked.
* **Checks.** DNS through DNS-over-HTTPS (A, AAAA, CNAME, TXT, CAA — the same resolver as the mail domain check);
  TLS by connecting to the address DNS gave, with the domain as SNI (certificate, issuer, expiry, whether it is
  trusted); HTTPS answer. A domain that resolves to a private, loopback or link-local address is not connected to:
  the check cannot be turned into a request into the shop's own network.
* **DNS records.** With a Cloudflare API token (runtime setting ``cloudflare_api_token``) the A record of a domain is
  created or updated to the expected address from the admin panel; without a token the panel shows what to create.
* **Certificates.** Issued by Caddy with ACME HTTP-01 / TLS-ALPN-01 (Let's Encrypt, ZeroSSL as fallback). DNS-01 needs
  a Caddy build with a DNS provider module, which the standard image does not have: not offered (status in docs).
* Daily re-check; a certificate that expires within 14 days or does not verify raises an alert."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import ssl
from datetime import datetime, timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import AuditLog, RemnawaveDomain, RemnawaveInstallation, RemnawaveServer
from .security import require_permission

logger = logging.getLogger("vpnshop.rw_domains")
router = APIRouter()
DOMAIN = re.compile(r"^(?=.{4,253}$)(?!-)[a-z0-9-]{1,63}(?:\.(?!-)[a-z0-9-]{1,63})+$")
PURPOSES = {"subscription": "Портал подписки", "panel": "Панель Remnawave", "subscription_page": "Страница подписки Remnawave",
            "node": "Нода (SNI)", "other": "Другое"}
EXPIRING = timedelta(days=14)
CF_API = "https://api.cloudflare.com/client/v4"
connect = None  # tests: async (ip, port, domain) -> (cert_dict | None, verified: bool, error: str | None)
http_get = None  # tests: async (domain, ip) -> status code


def _iso(value):
    return value.isoformat() + "Z" if value else None


def domain_out(row: RemnawaveDomain) -> dict:
    return {"id": row.id, "domain": row.domain, "purpose": row.purpose, "purpose_title": PURPOSES.get(row.purpose, row.purpose),
            "served_by": row.served_by, "server_id": row.server_id, "expected_ip": row.expected_ip, "enabled": row.enabled,
            "dns_status": row.dns_status, "dns_records": row.dns_records or {}, "dns_checked_at": _iso(row.dns_checked_at),
            "cert_status": row.cert_status, "cert_issuer": row.cert_issuer, "cert_expires_at": _iso(row.cert_expires_at),
            "cert_checked_at": _iso(row.cert_checked_at), "http_status": row.http_status, "last_error": row.last_error,
            "created_at": _iso(row.created_at)}


class DomainIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str = Field(max_length=253)
    purpose: Literal["subscription", "panel", "subscription_page", "node", "other"]
    served_by: Literal["shop", "remnawave", "external"] = "shop"
    server_id: int | None = None
    expected_ip: str | None = Field(default=None, max_length=64)

    @field_validator("domain")
    @classmethod
    def domain_ok(cls, value: str) -> str:
        value = value.strip().lower().rstrip(".")
        if not DOMAIN.match(value):
            raise ValueError("Некорректный домен")
        return value

    @field_validator("expected_ip")
    @classmethod
    def ip_ok(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        ip = ipaddress.ip_address(value.strip())
        if not ip.is_global:
            raise ValueError("Ожидаемый адрес должен быть публичным")
        return str(ip)


class DomainPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    expected_ip: str | None = Field(default=None, max_length=64)

    @field_validator("expected_ip")
    @classmethod
    def ip_ok(cls, value: str | None) -> str | None:
        return DomainIn.ip_ok(value)


async def _audit(db: AsyncSession, action: str, actor: str, target: str, details: str = "") -> None:
    db.add(AuditLog(action=action, actor=actor, target=target, details=details or None))


async def _domain(db: AsyncSession, domain_id: int) -> RemnawaveDomain:
    row = await db.get(RemnawaveDomain, domain_id)
    if not row:
        raise HTTPException(404, "Домен не найден")
    return row


# ---------------------------------------------------------------- checks

def _resolver():
    from .mail_domain import Resolver, client_factory
    return Resolver, client_factory


async def _query(resolver, name: str, rtype: str) -> list[str]:
    from .mail_domain import DnsError
    try:
        return await resolver.query(name, rtype)
    except DnsError:
        raise
    except KeyError:
        return []


async def expected_addresses(db: AsyncSession, row: RemnawaveDomain, resolver) -> list[str]:
    """Where the domain must point: the address the administrator gave, else the server of the wizard, else the
    addresses of the shop's API domain (the shop's Caddy)."""
    if row.expected_ip:
        return [row.expected_ip]
    if row.served_by == "remnawave" and row.server_id:
        server = await db.get(RemnawaveServer, row.server_id)
        if server:
            try:
                return [str(ipaddress.ip_address(server.host))]
            except ValueError:
                return await resolver.addresses(server.host)
    if row.served_by == "shop" and DOMAIN.match(settings.api_domain or ""):
        return await resolver.addresses(settings.api_domain)
    return []


async def check_dns(db: AsyncSession, row: RemnawaveDomain, resolver) -> dict:
    from .mail_domain import DnsError
    try:
        records = {t: await _query(resolver, row.domain, t) for t in ("A", "AAAA", "CNAME", "TXT", "CAA")}
        expected = await expected_addresses(db, row, resolver)
    except DnsError as exc:
        return {"status": "error", "records": {}, "expected": [], "detail": str(exc)}
    got = set(records["A"]) | set(records["AAAA"])
    issuers = [c for c in records["CAA"] if re.search(r"\bissue\b", c)]
    caa_blocks = bool(issuers) and not any("letsencrypt.org" in c for c in issuers)
    if not got:
        status, detail = "missing", "Нет записи A или AAAA"
    elif expected and not got & set(expected):
        status, detail = "mismatch", f"Указывает на {', '.join(sorted(got))}, а нужно {', '.join(expected)}"
    elif caa_blocks:
        status, detail = "caa", "Запись CAA запрещает выпуск сертификата Let's Encrypt"
    else:
        status, detail = "ok", f"{', '.join(sorted(got))}" + (" (как ожидается)" if expected else "")
    return {"status": status, "records": records, "expected": expected, "detail": detail}


async def _tls_probe(ip: str, port: int, domain: str) -> tuple[dict | None, bool, str | None]:
    """The certificate the address presents for ``domain``: verified with the system trust store, else read
    without verification to show what is wrong."""
    if connect:
        return await connect(ip, port, domain)
    async def handshake(verify: bool):
        context = ssl.create_default_context()
        if not verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port, ssl=context, server_hostname=domain), 10)
        try:
            der = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
        finally:
            writer.close()
        return der
    error = None
    try:
        der, verified = await handshake(True), True
    except ssl.SSLCertVerificationError as exc:
        error = exc.verify_message or "сертификат не прошёл проверку"
        try:
            der, verified = await handshake(False), False
        except (OSError, ssl.SSLError, asyncio.TimeoutError):
            return None, False, error
    except (OSError, ssl.SSLError, asyncio.TimeoutError) as exc:
        return None, False, f"TLS не установлен: {type(exc).__name__}"
    from cryptography import x509
    cert = x509.load_der_x509_certificate(der)
    issuer = cert.issuer.get_attributes_for_oid(x509.NameOID.ORGANIZATION_NAME) or cert.issuer.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
    try:
        names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        names = []
    return {"issuer": issuer[0].value if issuer else "", "not_after": cert.not_valid_after_utc.replace(tzinfo=None),
            "names": names}, verified, error


def public_ip(addresses: list[str]) -> str | None:
    for value in addresses:
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            continue
        if ip.is_global:
            return str(ip)
    return None


async def check_tls(row: RemnawaveDomain, addresses: list[str]) -> dict:
    ip = public_ip(addresses)
    if not ip:
        return {"status": "missing", "detail": "Нет публичного адреса: подключение не выполнялось"}
    cert, verified, error = await _tls_probe(ip, 443, row.domain)
    if not cert:
        return {"status": "missing", "detail": error or "Сертификата нет"}
    left = cert["not_after"] - datetime.utcnow()
    if left <= timedelta(0):
        status = "expired"
    elif not verified:
        status = "invalid"
    elif left < EXPIRING:
        status = "expiring"
    else:
        status = "valid"
    detail = f"{cert['issuer']}, до {cert['not_after']:%Y-%m-%d}" + (f"; {error}" if error else "")
    return {"status": status, "issuer": cert["issuer"][:200], "expires_at": cert["not_after"], "names": cert["names"], "detail": detail}


async def check_http(row: RemnawaveDomain, addresses: list[str]) -> int | None:
    ip = public_ip(addresses)
    if not ip:
        return None
    if http_get:
        return await http_get(row.domain, ip)
    # The request goes to the address DNS gave (no second lookup), with the domain in SNI and Host; the certificate
    # is verified against the domain (an untrusted one is reported by the TLS check, here there is no answer).
    transport = httpx.AsyncHTTPTransport(retries=0)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=10, follow_redirects=False) as client:
            r = await client.get(f"https://{ip}/", headers={"Host": row.domain, "User-Agent": "CorgiShop-DomainCheck/1"},
                                 extensions={"sni_hostname": row.domain})
            return r.status_code
    except httpx.HTTPError:
        return None


async def run_check(db: AsyncSession, row: RemnawaveDomain) -> dict:
    Resolver, factory = _resolver()
    async with factory() as client:
        resolver = Resolver(client)
        dns = await check_dns(db, row, resolver)
    addresses = [*dns["records"].get("A", []), *dns["records"].get("AAAA", [])]
    tls = await check_tls(row, addresses) if dns["status"] != "error" else {"status": "unknown", "detail": "DNS не проверен"}
    http = await check_http(row, addresses) if tls["status"] not in ("missing", "unknown") else None
    now = datetime.utcnow()
    row.dns_status, row.dns_records, row.dns_checked_at = dns["status"], {**dns["records"], "expected": dns["expected"]}, now
    row.cert_status, row.cert_checked_at = tls["status"], now
    row.cert_issuer, row.cert_expires_at = tls.get("issuer"), tls.get("expires_at")
    row.http_status = http
    problems = [d for d, ok in ((dns["detail"], dns["status"] == "ok"), (tls["detail"], tls["status"] == "valid")) if not ok]
    row.last_error = "; ".join(problems)[:2000] or None
    row.updated_at = now
    await db.commit()
    return {"domain": domain_out(row), "dns": dns["detail"], "tls": tls["detail"], "http": http}


# ---------------------------------------------------------------- Caddy on-demand TLS

@router.get("/caddy/ask", include_in_schema=False)
async def caddy_ask(domain: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Caddy asks before issuing a certificate on demand: 200 only for an enabled shop domain. A request that came
    through the proxy (it carries X-Forwarded-For) is not Caddy asking — 404, so the list is not readable from outside."""
    if request.headers.get("x-forwarded-for"):
        raise HTTPException(404)
    name = domain.strip().lower().rstrip(".")
    if not DOMAIN.match(name):
        raise HTTPException(404)
    found = await db.scalar(select(RemnawaveDomain.id).where(RemnawaveDomain.domain == name, RemnawaveDomain.enabled.is_(True),
                                                             RemnawaveDomain.served_by == "shop", RemnawaveDomain.purpose == "subscription"))
    if not found:
        raise HTTPException(404)
    return PlainTextResponse("ok")


# ---------------------------------------------------------------- Cloudflare DNS records

def _cf_headers() -> dict:
    token = getattr(settings, "cloudflare_api_token", "") or ""
    if not token:
        raise HTTPException(409, "Не задан токен Cloudflare: «Настройки → Параметры → Cloudflare API»")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def _cf(method: str, path: str, **kw) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.request(method, CF_API + path, headers=_cf_headers(), **kw)
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or not data.get("success", False):
        message = "; ".join(str(e.get("message")) for e in data.get("errors") or [])[:300] or f"HTTP {r.status_code}"
        raise HTTPException(502, f"Cloudflare: {message}")
    return data


async def _zone_for(domain: str) -> dict:
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        zone = ".".join(parts[i:])
        found = (await _cf("GET", "/zones", params={"name": zone}))["result"]
        if found:
            return found[0]
    raise HTTPException(404, "Зона домена не найдена в Cloudflare (у токена нет к ней доступа)")


# ---------------------------------------------------------------- admin API

@router.get("/api/admin/rw/domains")
async def list_domains(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    rows = (await db.execute(select(RemnawaveDomain).order_by(RemnawaveDomain.domain))).scalars().all()
    from .sub_proxy import config as proxy_config
    cfg = await proxy_config(db)
    return {"domains": [domain_out(r) for r in rows], "purposes": PURPOSES, "shop_api_domain": settings.api_domain,
            "subscription_base": cfg.get("public_base") or "", "cloudflare": bool(getattr(settings, "cloudflare_api_token", ""))}


@router.post("/api/admin/rw/domains")
async def add_domain(payload: DomainIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    if await db.scalar(select(RemnawaveDomain.id).where(RemnawaveDomain.domain == payload.domain)):
        raise HTTPException(409, "Домен уже добавлен")
    shop_names = {settings.admin_domain, settings.app_domain, settings.cabinet_domain, *settings.api_domains()}
    if payload.domain in shop_names:
        raise HTTPException(409, "Это домен самого магазина: он уже обслуживается общим Caddy")
    if payload.served_by == "remnawave":
        if not payload.server_id or not await db.get(RemnawaveServer, payload.server_id):
            raise HTTPException(422, "Выберите сервер Remnawave из реестра")
    elif payload.server_id:
        raise HTTPException(422, "Сервер указывается только для доменов на серверах Remnawave")
    if payload.served_by == "shop" and payload.purpose != "subscription":
        raise HTTPException(422, "Общий Caddy магазина обслуживает только домены портала подписки")
    row = RemnawaveDomain(created_by=admin.email, **payload.model_dump())
    db.add(row)
    await db.flush()
    await _audit(db, "rw.domain.added", admin.email, row.domain, f"{row.purpose}/{row.served_by}")
    await db.commit()
    return domain_out(row)


@router.patch("/api/admin/rw/domains/{domain_id}")
async def patch_domain(domain_id: int, payload: DomainPatch, db: AsyncSession = Depends(get_db),
                       admin=Depends(require_permission("settings.runtime.write"))):
    row = await _domain(db, domain_id)
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if "expected_ip" in payload.model_fields_set:
        row.expected_ip = payload.expected_ip
    row.updated_at = datetime.utcnow()
    await _audit(db, "rw.domain.updated", admin.email, row.domain, f"enabled={row.enabled}")
    await db.commit()
    return domain_out(row)


@router.delete("/api/admin/rw/domains/{domain_id}")
async def delete_domain(domain_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    row = await _domain(db, domain_id)
    from .sub_proxy import config as proxy_config
    cfg = await proxy_config(db)
    if (cfg.get("public_base") or "").rstrip("/") == f"https://{row.domain}":
        raise HTTPException(409, "Это адрес подписки клиентов: сначала выберите другой домен подписки")
    await _audit(db, "rw.domain.deleted", admin.email, row.domain)
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


@router.post("/api/admin/rw/domains/{domain_id}/check")
async def check_domain(domain_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    return await run_check(db, await _domain(db, domain_id))


@router.post("/api/admin/rw/domains/{domain_id}/primary")
async def make_primary(domain_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    """Customers get subscription links on this domain (the proxy's public address)."""
    row = await _domain(db, domain_id)
    if row.purpose != "subscription" or row.served_by != "shop" or not row.enabled:
        raise HTTPException(409, "Адресом подписки может быть включённый домен портала на сервере магазина")
    if row.cert_status not in ("valid", "expiring"):
        raise HTTPException(409, "Сначала «Проверить»: у домена должен быть действующий сертификат")
    from . import sub_proxy
    from .node_health import _save
    cfg = await sub_proxy.load_config(db)
    cfg = {**cfg, "public_base": f"https://{row.domain}"}
    await _save(db, sub_proxy.CONFIG_KEY, cfg)
    await _audit(db, "rw.domain.primary", admin.email, row.domain)
    await db.commit()
    sub_proxy._state.update(cfg=cfg, at=0.0)
    return {"subscription_base": cfg["public_base"], "enabled": cfg.get("enabled")}


@router.post("/api/admin/rw/domains/{domain_id}/dns-record")
async def upsert_dns_record(domain_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    """Create or update the domain's A record at Cloudflare to the expected address (proxying off: Let's Encrypt and
    VPN clients must reach the server itself)."""
    row = await _domain(db, domain_id)
    Resolver, factory = _resolver()
    async with factory() as client:
        expected = await expected_addresses(db, row, Resolver(client))
    ip = next((x for x in expected if ipaddress.ip_address(x).version == 4), None)
    if not ip:
        raise HTTPException(409, "Не известен адрес IPv4, на который указывать: задайте «Ожидаемый адрес»")
    zone = await _zone_for(row.domain)
    existing = (await _cf("GET", f"/zones/{zone['id']}/dns_records", params={"type": "A", "name": row.domain}))["result"]
    body = {"type": "A", "name": row.domain, "content": ip, "ttl": 300, "proxied": False}
    if existing:
        await _cf("PUT", f"/zones/{zone['id']}/dns_records/{existing[0]['id']}", json=body)
        action = "updated"
    else:
        await _cf("POST", f"/zones/{zone['id']}/dns_records", json=body)
        action = "created"
    await _audit(db, "rw.domain.dns_record", admin.email, row.domain, f"A {ip} {action}")
    await db.commit()
    return {"action": action, "type": "A", "content": ip, "zone": zone.get("name")}


@router.get("/api/admin/rw/certificates")
async def certificates(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    rows = (await db.execute(select(RemnawaveDomain).order_by(RemnawaveDomain.cert_expires_at))).scalars().all()
    now = datetime.utcnow()
    out = [{"domain": r.domain, "served_by": r.served_by, "status": r.cert_status, "issuer": r.cert_issuer,
            "expires_at": _iso(r.cert_expires_at), "days_left": (r.cert_expires_at - now).days if r.cert_expires_at else None,
            "checked_at": _iso(r.cert_checked_at),
            "renewal": {"shop": "Caddy магазина продлевает сам за 30 дней до конца (HTTP-01 / TLS-ALPN-01)",
                        "remnawave": "Caddy сервера Remnawave продлевает сам (HTTP-01 / TLS-ALPN-01)",
                        "external": "Продлевает тот, кто обслуживает домен"}[r.served_by]} for r in rows]
    return {"certificates": out, "challenges": ["http-01", "tls-alpn-01"],
            "dns01": "Недоступно: нужен Caddy с модулем DNS-провайдера, стандартный образ его не содержит"}


@router.post("/api/admin/rw/certificates/check")
async def check_all(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    rows = (await db.execute(select(RemnawaveDomain).where(RemnawaveDomain.enabled.is_(True)))).scalars().all()
    results = [await run_check(db, r) for r in rows]
    return {"checked": len(results), "problems": [x["domain"]["domain"] for x in results if x["domain"]["last_error"]]}


@router.get("/api/admin/rw/proxy-routes")
async def proxy_routes(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    """What each Caddy serves. The shop's static sites come from .env; portal domains are added here and served
    on demand; Remnawave servers' Caddy sites come from the wizard's installations."""
    from .sub_proxy import config as proxy_config
    cfg = await proxy_config(db)
    shop = [{"domain": settings.admin_domain, "target": "admin", "source": ".env ADMIN_DOMAIN"},
            {"domain": settings.cabinet_domain, "target": "cabinet", "source": ".env CABINET_DOMAIN"},
            {"domain": settings.app_domain, "target": "miniapp", "source": ".env APP_DOMAIN"},
            *({"domain": d, "target": "backend (API)", "source": ".env API_DOMAIN / API_MIRROR_DOMAINS"} for d in settings.api_domains())]
    rows = (await db.execute(select(RemnawaveDomain).where(RemnawaveDomain.served_by == "shop"))).scalars().all()
    portal = [{"domain": r.domain, "target": "backend /sub (портал и прокси подписки)", "source": "Домены (on-demand TLS)",
               "enabled": r.enabled, "primary": (cfg.get("public_base") or "").rstrip("/") == f"https://{r.domain}"} for r in rows]
    remote = []
    installs = (await db.execute(select(RemnawaveInstallation).where(RemnawaveInstallation.action == "install",
                                                                     RemnawaveInstallation.status == "succeeded"))).scalars().all()
    for inst in installs:
        p = inst.params or {}
        if p.get("panel_server_id") and p.get("panel_domain"):
            remote.append({"domain": p["panel_domain"], "target": "127.0.0.1:3000 (панель)", "server_id": p["panel_server_id"],
                           "installation_id": inst.id, "tls": p.get("tls")})
        if p.get("subpage_server_id") and p.get("sub_domain"):
            remote.append({"domain": p["sub_domain"], "target": "127.0.0.1:3010 (страница подписки)", "server_id": p["subpage_server_id"],
                           "installation_id": inst.id, "tls": p.get("tls")})
    return {"shop": shop, "portal": portal, "remnawave": remote, "on_demand_ask": "/caddy/ask"}


# ---------------------------------------------------------------- daily re-check

async def recheck_all() -> int:
    from .db import SessionLocal
    from .main import send_alert
    async with SessionLocal() as db:
        rows = (await db.execute(select(RemnawaveDomain).where(RemnawaveDomain.enabled.is_(True)))).scalars().all()
        for row in rows:
            try:
                await run_check(db, row)
            except Exception as exc:  # noqa: BLE001 — one domain never stops the others
                logger.warning("Domain check of %s failed: %s", row.domain, exc)
                continue
            if row.cert_status in ("expiring", "expired", "invalid", "missing"):
                await send_alert(f"Домен {row.domain}: сертификат {row.cert_status}" +
                                 (f", до {row.cert_expires_at:%Y-%m-%d}" if row.cert_expires_at else ""))
        return len(rows)


async def _loop() -> None:
    await asyncio.sleep(300)
    while True:
        try:
            await recheck_all()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Daily domain re-check failed: %s", exc)
        await asyncio.sleep(86400)


async def _start() -> None:
    from . import main
    main._track_task(_loop())


router.add_event_handler("startup", _start)
