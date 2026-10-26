"""Proof that a sign-in comes from the genuine app on a genuine device (optional, owner keys).

* Android — Play Integrity (classic request with a nonce): the app asks Google Play for an
  integrity token bound to a server nonce; the shop decodes it with its Google service account
  (``GOOGLE_SERVICE_ACCOUNT_JSON``, role «Play Integrity API») and checks the package, the nonce,
  that Google Play recognises the app (and its signing certificate, ``ANDROID_USER_CERT_SHA256``) and
  that the device meets basic integrity.
* iOS — DeviceCheck: the app sends a DCDevice token; the shop asks Apple
  (``DEVICECHECK_KEY_ID``/``DEVICECHECK_PRIVATE_KEY``, team ``APNS_TEAM_ID``) whether it is valid.

``MOBILE_INTEGRITY_MODE``: ``off`` (default) — nothing is asked; ``report`` — verdicts are only
written to the audit log; ``enforce`` — the native token exchange (every native sign-in:
password, passkey, link, OAuth) is refused without a passing verdict.
"""
from __future__ import annotations

import base64
import json
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response

from .config import settings

router = APIRouter()
NONCE_SECONDS = 300

__all__ = ["router", "mode", "new_nonce", "check_nonce", "verify_play", "verify_devicecheck", "require_integrity"]


def mode() -> str:
    value = (getattr(settings, "mobile_integrity_mode", "") or "off").strip().lower()
    return value if value in {"off", "report", "enforce"} else "off"


def new_nonce() -> str:
    import jwt

    payload = {"typ": "integrity", "n": secrets.token_urlsafe(24), "exp": int(time.time()) + NONCE_SECONDS}
    token = jwt.encode(payload, settings.app_secret, algorithm="HS256")
    # Play Integrity takes a URL-safe base64 nonce of 16..500 bytes.
    return base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")


def check_nonce(nonce: str) -> bool:
    import jwt

    try:
        raw = base64.urlsafe_b64decode(nonce + "=" * (-len(nonce) % 4)).decode()
        return jwt.decode(raw, settings.app_secret, algorithms=["HS256"]).get("typ") == "integrity"
    except Exception:
        return False


@router.post("/api/mobile/integrity/challenge")
async def integrity_challenge(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"mode": mode(), "nonce": new_nonce() if mode() != "off" else ""}


async def _google_token() -> str:
    import httpx
    import jwt

    info = json.loads(settings.google_service_account_json)
    now = int(time.time())
    assertion = jwt.encode({"iss": info["client_email"], "scope": "https://www.googleapis.com/auth/playintegrity",
                            "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600},
                           info["private_key"].replace("\\n", "\n"), algorithm="RS256")
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        r = await client.post("https://oauth2.googleapis.com/token",
                              data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
        r.raise_for_status()
        return r.json()["access_token"]


def play_verdict(payload: dict, nonce: str, package: str, cert_sha256: str = "") -> tuple[bool, str]:
    """Pass/fail and the reason for a decoded Play Integrity payload."""
    request = payload.get("requestDetails") or {}
    app = payload.get("appIntegrity") or {}
    device = payload.get("deviceIntegrity") or {}
    if request.get("requestPackageName") != package:
        return False, "package"
    if request.get("nonce", "").rstrip("=") != nonce.rstrip("="):
        return False, "nonce"
    if app.get("appRecognitionVerdict") != "PLAY_RECOGNIZED":
        return False, "app " + str(app.get("appRecognitionVerdict"))
    if cert_sha256:
        wanted = cert_sha256.replace(":", "").lower()
        digests = [base64.urlsafe_b64decode(d + "=" * (-len(d) % 4)).hex() for d in app.get("certificateSha256Digest") or []]
        if wanted not in digests:
            return False, "certificate"
    verdicts = device.get("deviceRecognitionVerdict") or []
    if not ({"MEETS_DEVICE_INTEGRITY", "MEETS_STRONG_INTEGRITY", "MEETS_BASIC_INTEGRITY"} & set(verdicts)):
        return False, "device"
    return True, "ok"


async def verify_play(token: str, nonce: str) -> tuple[bool, str]:
    import httpx

    package = getattr(settings, "android_user_package", "") or settings.google_play_package or "shop.remnawave.user"
    if not settings.google_service_account_json:
        return False, "Google service account is not configured"
    access = await _google_token()
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        r = await client.post(f"https://playintegrity.googleapis.com/v1/{package}:decodeIntegrityToken",
                              json={"integrity_token": token}, headers={"Authorization": f"Bearer {access}"})
    if r.status_code != 200:
        return False, f"Play Integrity HTTP {r.status_code}"
    return play_verdict(r.json().get("tokenPayloadExternal") or {}, nonce, package, getattr(settings, "android_user_cert_sha256", ""))


async def verify_devicecheck(token: str) -> tuple[bool, str]:
    import httpx
    import jwt
    import uuid

    key_id = getattr(settings, "devicecheck_key_id", "")
    key = (getattr(settings, "devicecheck_private_key", "") or "").replace("\\n", "\n")
    team = getattr(settings, "apns_team_id", "")
    if not key_id or not key or not team:
        return False, "DeviceCheck key is not configured"
    bearer = jwt.encode({"iss": team.strip(), "iat": int(time.time())}, key, algorithm="ES256", headers={"kid": key_id.strip()})
    host = "api.development.devicecheck.apple.com" if settings.apns_environment.strip().lower() == "sandbox" else "api.devicecheck.apple.com"
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        r = await client.post(f"https://{host}/v1/validate_device_token", headers={"Authorization": f"Bearer {bearer}"},
                              json={"device_token": token, "transaction_id": str(uuid.uuid4()), "timestamp": int(time.time() * 1000)})
    return (True, "ok") if r.status_code == 200 else (False, f"DeviceCheck HTTP {r.status_code}")


async def require_integrity(request: Request) -> None:
    """Called by the native token exchange. Raises 403 in enforce mode without a passing verdict."""
    current = mode()
    if current == "off":
        return
    from .mobile_auth import mobile_client_name

    client = mobile_client_name(request)
    if client not in {"android-user", "ios-user"}:
        return  # the administrator apps sign in with a password and MFA; integrity is for the customer apps
    token = (request.headers.get("x-shop-integrity") or "").strip()
    nonce = (request.headers.get("x-shop-integrity-nonce") or "").strip()
    ok, reason = False, "missing token"
    try:
        if token and client.startswith("android"):
            ok, reason = (await verify_play(token, nonce)) if check_nonce(nonce) else (False, "nonce")
        elif token and client.startswith("ios"):
            ok, reason = await verify_devicecheck(token)
    except Exception as exc:
        ok, reason = False, f"verification unavailable: {type(exc).__name__}"
    if not ok:
        import logging
        logging.getLogger(__name__).warning("mobile integrity %s for %s: %s", "refused" if current == "enforce" else "failed (report)",
                                            client or "unknown", reason)
        if current == "enforce":
            raise HTTPException(403, "Приложение не прошло проверку подлинности. Установите его из Google Play или App Store.")
