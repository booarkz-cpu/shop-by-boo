"""Domain rotation for the mobile apps: signed list of reserve API addresses.

When the main domain is blocked, the Android and iOS apps switch to a reserve address on their own:

1. While the main domain works, the app reads ``GET /api/public/mirrors`` and keeps the list and the
   shop's public key (trust on first use: the key is remembered from the first answer of the address
   the customer signed in to).
2. The document is signed with ECDSA P-256 (the private key is generated here once and stored encrypted).
   The app accepts a reserve address or a list from anywhere only when the signature matches the key.
3. Reserve lists also live outside the shop: ``bootstrap`` URLs (a GitHub Gist raw link, Firebase Hosting,
   any static file) serve the same signed document. With a Gist ID and token set in «Мобильные приложения →
   Резервные адреса» the shop republishes the Gist itself every day and on every change.

Signing keeps a hijacked Gist or DNS from steering the apps (and their session tokens) to a foreign server.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import decrypt_secret, encrypt_secret, require_permission

logger = logging.getLogger("vpnshop.mobile_mirrors")
router = APIRouter()

CONFIG_KEY = "mobile.mirrors"
KEY_KEY = "mobile.mirrors.signing_key"
TOKEN_KEY = "mobile.mirrors.gist_token"
VALID_DAYS = 30
GIST_FILE = "corgi-mirrors.json"
DEFAULT = {"mirrors": [], "bootstrap": [], "direct_domains": [], "gist_id": "", "published_at": None, "publish_error": None}


def _https(value: str) -> str:
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError(f"Нужен https-адрес без логина и параметров: {value[:80]}")
    return value


class MirrorsIn(BaseModel):
    mirrors: list[str] = Field(default_factory=list, max_length=10)
    bootstrap: list[str] = Field(default_factory=list, max_length=5)
    # Extra sites the apps send around the VPN in «Российские сайты напрямую» (banks, Госуслуги…).
    direct_domains: list[str] = Field(default_factory=list, max_length=200)
    gist_id: str = Field(default="", max_length=64, pattern=r"^[0-9a-fA-F]*$")
    gist_token: str | None = Field(default=None, max_length=255)

    @field_validator("mirrors", "bootstrap")
    @classmethod
    def _urls(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for v in values:
            if v.strip() and (url := _https(v)) not in out:
                out.append(url)
        return out

    @field_validator("direct_domains")
    @classmethod
    def _domains(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for v in values:
            v = v.strip().lower().removeprefix("https://").removeprefix("http://").strip("/.")
            if not v:
                continue
            if not re.fullmatch(r"(?:[a-z0-9-]{1,63}\.)+[a-z0-9-]{2,63}", v):
                raise ValueError(f"Не похоже на домен: {v[:80]}")
            if v not in out:
                out.append(v)
        return out


async def load(db: AsyncSession) -> dict:
    from .main import setting_value
    try:
        value = json.loads(await setting_value(db, CONFIG_KEY, "{}") or "{}")
    except ValueError:
        value = {}
    return {**DEFAULT, **value} if isinstance(value, dict) else dict(DEFAULT)


async def _private_key(db: AsyncSession) -> ec.EllipticCurvePrivateKey:
    from .main import set_setting, setting_value
    stored = await setting_value(db, KEY_KEY, "")
    if stored:
        return serialization.load_pem_private_key(decrypt_secret(stored).encode(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    await set_setting(db, KEY_KEY, encrypt_secret(pem))
    await db.commit()
    return key


def public_key_b64(key: ec.EllipticCurvePrivateKey) -> str:
    """SubjectPublicKeyInfo DER: Android X509EncodedKeySpec and iOS P256.Signing.PublicKey(derRepresentation:)."""
    return base64.b64encode(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()


async def signed_document(db: AsyncSession, now: datetime | None = None) -> dict:
    from .config import settings
    cfg = await load(db)
    now = now or datetime.now(timezone.utc)
    # The apps talk to the API domain; «localhost» means a development stand without a public address.
    primary = f"https://{settings.api_domain}" if settings.api_domain not in {"", "localhost"} else ""
    payload = json.dumps({
        "shop": primary,
        "mirrors": [u for u in [primary, *cfg["mirrors"]] if u],
        "bootstrap": cfg["bootstrap"],
        "direct": cfg.get("direct_domains", []),
        "issued_at": now.replace(microsecond=0).isoformat(),
        "expires_at": (now + timedelta(days=VALID_DAYS)).replace(microsecond=0).isoformat(),
    }, ensure_ascii=False, separators=(",", ":"))
    key = await _private_key(db)
    signature = key.sign(payload.encode(), ec.ECDSA(hashes.SHA256()))
    return {"payload": payload, "signature": base64.b64encode(signature).decode(), "key": public_key_b64(key), "alg": "ES256"}


def verify(document: dict, key_b64: str) -> dict:
    """What the apps do; used by tests and the admin preview."""
    if document.get("key") != key_b64:
        raise ValueError("key mismatch")
    public = serialization.load_der_public_key(base64.b64decode(key_b64))
    public.verify(base64.b64decode(document["signature"]), document["payload"].encode(), ec.ECDSA(hashes.SHA256()))
    payload = json.loads(document["payload"])
    if datetime.fromisoformat(payload["expires_at"]) < datetime.now(timezone.utc):
        raise ValueError("expired")
    return payload


async def publish(db: AsyncSession, client: httpx.AsyncClient | None = None) -> dict:
    """Write the signed document to the configured Gist. Returns the stored config."""
    from .main import set_setting, setting_value
    cfg = await load(db)
    token = await setting_value(db, TOKEN_KEY, "")
    if not cfg["gist_id"] or not token:
        return cfg
    document = await signed_document(db)
    body = {"files": {GIST_FILE: {"content": json.dumps(document, ensure_ascii=False, indent=1)}}}
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        r = await client.patch(f"https://api.github.com/gists/{cfg['gist_id']}", json=body,
                               headers={"Authorization": f"Bearer {decrypt_secret(token)}", "Accept": "application/vnd.github+json"})
        cfg["publish_error"] = None if r.status_code < 300 else f"GitHub ответил {r.status_code}"
        if r.status_code < 300:
            cfg["published_at"] = datetime.now(timezone.utc).isoformat()
            raw = (r.json().get("files", {}).get(GIST_FILE) or {}).get("raw_url", "")
            # The raw link without the revision always shows the latest version.
            stable = raw.split("/raw/")[0] + f"/raw/{GIST_FILE}" if "/raw/" in raw else ""
            if stable and stable not in cfg["bootstrap"]:
                cfg["bootstrap"] = [*cfg["bootstrap"], stable][:5]
    except httpx.HTTPError as exc:
        cfg["publish_error"] = f"GitHub недоступен: {str(exc)[:120]}"
    finally:
        if own:
            await client.aclose()
    await set_setting(db, CONFIG_KEY, json.dumps(cfg, ensure_ascii=False))
    await db.commit()
    return cfg


async def mirrors_scheduler():
    from . import main
    from .db import SessionLocal
    while True:
        try:
            lock = await main.redis_client.set("lock:mobile-mirrors", "1", nx=True, ex=3000) if main.redis_client else True
            if lock:
                async with SessionLocal() as db:
                    await publish(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Mirror list publication failed: %s", exc)
        # Daily: the document stays valid for 30 days, so a few missed days change nothing.
        await asyncio.sleep(24 * 3600)


@router.get("/api/public/mirrors")
async def public_mirrors(response: Response, db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "public, max-age=300"
    return await signed_document(db)


@router.get("/api/admin/mobile/mirrors")
async def get_mirrors(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.read"))):
    from .main import setting_value
    cfg = await load(db)
    return {**cfg, "gist_token_set": bool(await setting_value(db, TOKEN_KEY, "")), "public_key": public_key_b64(await _private_key(db))}


@router.put("/api/admin/mobile/mirrors")
async def put_mirrors(payload: MirrorsIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .main import audit, set_setting
    cfg = {**await load(db), **payload.model_dump(exclude={"gist_token"})}
    await set_setting(db, CONFIG_KEY, json.dumps(cfg, ensure_ascii=False))
    if payload.gist_token is not None:
        await set_setting(db, TOKEN_KEY, encrypt_secret(payload.gist_token.strip()) if payload.gist_token.strip() else "")
    await audit(db, "mobile.mirrors", admin.email, None, {"mirrors": cfg["mirrors"], "bootstrap": cfg["bootstrap"], "direct": len(cfg["direct_domains"]), "gist": bool(cfg["gist_id"])})
    await db.commit()
    cfg = await publish(db)
    return await get_mirrors(db, admin)


@router.post("/api/admin/mobile/mirrors/publish")
async def publish_now(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    cfg = await publish(db)
    if cfg["publish_error"]:
        raise HTTPException(502, cfg["publish_error"])
    if not cfg["gist_id"]:
        raise HTTPException(400, "Укажите ID Gist и токен GitHub")
    return cfg
