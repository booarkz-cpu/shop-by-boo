"""PKCE-bound native sessions; legacy proof is development-only.

Web sessions stay in HttpOnly cookies. Native password/MFA authentication
returns an encrypted authorization code bound to a per-login S256 verifier.
A one-use, native-only exchange returns the bearer token. PKCE binds the
exchange; it does not authenticate the application or replace user credentials.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import HTTPException

MOBILE_CLIENTS = frozenset({"android-user", "android-admin", "ios-user", "ios-admin"})
PROOF_WINDOW_SECONDS = 300


def mobile_client_name(request) -> str:
    name = (request.headers.get("x-shop-client") or "").strip().lower()
    return name if name in MOBILE_CLIENTS else ""


def proof_message(client: str, timestamp: str, method: str, path: str) -> str:
    return f"{client}\n{timestamp}\n{method.upper()}\n{path}"


def client_proof(key: str, client: str, timestamp: str, method: str, path: str) -> str:
    message = proof_message(client, timestamp, method, path).encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def require_mobile_proof(request) -> None:
    from .config import settings

    client = mobile_client_name(request)
    if client:
        require_native_transport(request)
        if request.method == "POST" and request.url.path in {"/api/auth/login", "/api/auth/register", "/api/admin/auth/login"}:
            require_pkce_challenge(request)
    if not client or not settings.mobile_require_proof:
        return
    if not settings.mobile_client_key:
        raise HTTPException(503, "Ключ подписи мобильного клиента не настроен")
    timestamp = (request.headers.get("x-shop-time") or "").strip()
    proof = (request.headers.get("x-shop-proof") or "").strip().lower()
    try:
        stamp = int(timestamp)
    except ValueError:
        raise HTTPException(401, "Подпись клиента не принята")
    if abs(int(time.time()) - stamp) > PROOF_WINDOW_SECONDS:
        raise HTTPException(401, "Подпись клиента не принята")
    path = request.url.path
    expected = client_proof(settings.mobile_client_key, client, timestamp, request.method, path)
    if not hmac.compare_digest(expected, proof):
        raise HTTPException(401, "Подпись клиента не принята")


def require_native_transport(request):
    from .config import settings
    if request.headers.get("origin") is not None or request.headers.get("sec-fetch-site") is not None:
        raise HTTPException(403, "Native token exchange is unavailable to browser origins")
    if settings.app_env.lower() == "production" and request.url.hostname not in settings.api_domains():
        raise HTTPException(403, "Use the configured API domain for native authentication")


def pkce_challenge(verifier: str) -> str:
    import base64
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


def require_pkce_challenge(request) -> str:
    import re
    challenge = request.headers.get("x-shop-code-challenge", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge):
        raise HTTPException(400, "S256 PKCE code challenge is required; update the native client")
    return challenge


def session_body(request, token: str, body: dict) -> dict:
    if not mobile_client_name(request):
        return body
    require_native_transport(request)
    import json, re, secrets
    from .security import encrypt_secret
    challenge = require_pkce_challenge(request)
    payload = {"type": "mobile_exchange", "client": mobile_client_name(request), "challenge": challenge,
               "token": token, "exp": int(time.time()) + 120, "jti": secrets.token_urlsafe(32)}
    return {**body, "authorization_code": encrypt_secret(json.dumps(payload)), "expires_in": 120}


async def exchange_mobile_code(request, code: str, verifier: str, redis):
    import json, re
    from .security import decrypt_secret
    require_native_transport(request)
    if not mobile_client_name(request) or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
        raise HTTPException(400, "Invalid native client or PKCE verifier")
    try:
        data = json.loads(decrypt_secret(code))
        valid = (data["type"] == "mobile_exchange" and data["exp"] > int(time.time())
                 and data["client"] == mobile_client_name(request)
                 and hmac.compare_digest(data["challenge"], pkce_challenge(verifier)))
    except Exception:
        valid = False
    if not valid:
        raise HTTPException(401, "Invalid or expired authorization code")
    if redis is None:
        raise HTTPException(503, "Token exchange temporarily unavailable")
    try:
        accepted = await redis.set("mobile-code-used:" + hashlib.sha256(data["jti"].encode()).hexdigest(), "1", ex=120, nx=True)
    except Exception:
        raise HTTPException(503, "Token exchange temporarily unavailable")
    if not accepted:
        raise HTTPException(401, "Authorization code already used")
    return {"access_token": data["token"], "token_type": "bearer"}
