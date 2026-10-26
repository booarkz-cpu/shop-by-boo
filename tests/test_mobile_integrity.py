"""Genuine app / device checks of native sign-ins (Play Integrity, DeviceCheck)."""
import base64

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import mobile_integrity as integrity
from app.config import settings

CERT = "AB" * 32
DIGEST = base64.urlsafe_b64encode(bytes.fromhex(CERT)).decode().rstrip("=")


def payload(nonce, **over):
    data = {"requestDetails": {"requestPackageName": "shop.remnawave.user", "nonce": nonce},
            "appIntegrity": {"appRecognitionVerdict": "PLAY_RECOGNIZED", "certificateSha256Digest": [DIGEST]},
            "deviceIntegrity": {"deviceRecognitionVerdict": ["MEETS_DEVICE_INTEGRITY"]}}
    for key, value in over.items():
        data[key] = {**data[key], **value}
    return data


def test_nonce_is_signed_and_expires(monkeypatch):
    nonce = integrity.new_nonce()
    assert integrity.check_nonce(nonce) and not integrity.check_nonce(nonce[:-4] + "AAAA")
    assert len(base64.urlsafe_b64decode(nonce + "=" * (-len(nonce) % 4))) >= 16
    monkeypatch.setattr(integrity, "NONCE_SECONDS", -10)
    assert not integrity.check_nonce(integrity.new_nonce())


def test_play_verdict_checks_package_nonce_app_certificate_and_device():
    nonce = "n" * 24
    cert = ":".join(CERT[i:i + 2] for i in range(0, 64, 2))
    assert integrity.play_verdict(payload(nonce), nonce, "shop.remnawave.user", cert) == (True, "ok")
    assert integrity.play_verdict(payload(nonce), "other", "shop.remnawave.user")[1] == "nonce"
    assert integrity.play_verdict(payload(nonce), nonce, "evil.app")[1] == "package"
    assert integrity.play_verdict(payload(nonce, appIntegrity={"appRecognitionVerdict": "UNRECOGNIZED_VERSION"}), nonce, "shop.remnawave.user")[0] is False
    assert integrity.play_verdict(payload(nonce), nonce, "shop.remnawave.user", "CD" * 32)[1] == "certificate"
    assert integrity.play_verdict(payload(nonce, deviceIntegrity={"deviceRecognitionVerdict": []}), nonce, "shop.remnawave.user")[1] == "device"


def request(headers):
    return Request({"type": "http", "method": "POST", "path": "/api/auth/mobile/token", "query_string": b"",
                    "headers": [(k.encode(), v.encode()) for k, v in headers.items()]})


@pytest.mark.asyncio
async def test_modes(monkeypatch):
    monkeypatch.setattr(settings, "mobile_integrity_mode", "off")
    await integrity.require_integrity(request({"x-shop-client": "android-user"}))  # nothing asked
    monkeypatch.setattr(settings, "mobile_integrity_mode", "report")
    await integrity.require_integrity(request({"x-shop-client": "android-user"}))  # only logged
    monkeypatch.setattr(settings, "mobile_integrity_mode", "enforce")
    with pytest.raises(HTTPException) as refused:
        await integrity.require_integrity(request({"x-shop-client": "android-user"}))
    assert refused.value.status_code == 403

    async def genuine(token, nonce):
        return token == "good", "ok"
    monkeypatch.setattr(integrity, "verify_play", genuine)
    nonce = integrity.new_nonce()
    await integrity.require_integrity(request({"x-shop-client": "android-user", "x-shop-integrity": "good", "x-shop-integrity-nonce": nonce}))
    with pytest.raises(HTTPException):
        await integrity.require_integrity(request({"x-shop-client": "android-user", "x-shop-integrity": "good", "x-shop-integrity-nonce": "forged"}))

    async def apple(token):
        return token == "dc", "ok"
    monkeypatch.setattr(integrity, "verify_devicecheck", apple)
    await integrity.require_integrity(request({"x-shop-client": "ios-user", "x-shop-integrity": "dc"}))
    monkeypatch.setattr(settings, "mobile_integrity_mode", "bogus")
    assert integrity.mode() == "off"
