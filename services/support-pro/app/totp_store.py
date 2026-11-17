"""Support Pro TOTP seeds at rest.

Legacy rows are base32 plaintext and stay readable. New writes are AES-GCM under
SESSION_SECRET. SESSION_SECRET_PREVIOUS still opens a seed sealed before a rotation.
A failed open never becomes an empty secret.
"""
import base64
import hashlib
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "sp1:"
_AAD = b"support-pro-totp"
_BASE32 = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


class TotpUnavailable(Exception):
    """The seed cannot be sealed or opened. Callers must keep the stored bytes."""


def is_sealed(stored: str | None) -> bool:
    return bool(stored and stored.startswith(PREFIX))


def _material(value: str) -> bytes | None:
    if len(value) < 32 or value.lower().startswith(("change-me", "changeme", "replace-me")):
        return None
    return hashlib.sha256(value.encode()).digest()


def _keys() -> list[bytes]:
    found = []
    for name in ("SESSION_SECRET", "SESSION_SECRET_PREVIOUS"):
        key = _material(os.getenv(name, ""))
        if key and key not in found:
            found.append(key)
    return found


def seal(plain: str) -> str:
    keys = _keys()
    if not keys:
        raise TotpUnavailable("session secret unavailable")
    nonce = secrets.token_bytes(12)
    blob = AESGCM(keys[0]).encrypt(nonce, plain.encode(), _AAD)
    stored = PREFIX + base64.urlsafe_b64encode(nonce + blob).decode()
    if not is_sealed(stored) or plain in stored:
        raise TotpUnavailable("seal refused to return plaintext")
    return stored


def open_secret(stored: str | None) -> str:
    if not stored:
        raise TotpUnavailable("missing totp seed")
    if not is_sealed(stored):
        if 16 <= len(stored) <= 64 and set(stored) <= _BASE32:
            return stored
        raise TotpUnavailable("unreadable totp seed")
    try:
        raw = base64.urlsafe_b64decode(stored[len(PREFIX):].encode())
    except Exception as exc:
        raise TotpUnavailable("unreadable totp seed") from exc
    if len(raw) <= 12:
        raise TotpUnavailable("truncated totp seed")
    for key in _keys():
        try:
            return AESGCM(key).decrypt(raw[:12], raw[12:], _AAD).decode()
        except Exception:
            continue
    raise TotpUnavailable("totp seed cannot be opened")


def sealed_for_current(stored: str | None) -> bool:
    """True when `stored` already opens with the current SESSION_SECRET."""
    keys = _keys()
    if not keys or not is_sealed(stored or ""):
        return False
    try:
        raw = base64.urlsafe_b64decode(stored[len(PREFIX):].encode())
        AESGCM(keys[0]).decrypt(raw[:12], raw[12:], _AAD)
        return True
    except Exception:
        return False
