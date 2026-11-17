import re

import httpx
import pyotp
import pytest

from app import main
from app.models import Operator
from app.totp_store import TotpUnavailable, is_sealed, open_secret, seal, sealed_for_current


def test_seal_hides_the_seed_and_legacy_plaintext_still_opens(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "current-session-secret-0123456789abcdef")
    monkeypatch.delenv("SESSION_SECRET_PREVIOUS", raising=False)
    plain = "JBSWY3DPEHPK3PXP"
    stored = seal(plain)
    assert is_sealed(stored) and plain not in stored
    assert open_secret(stored) == plain
    assert open_secret(plain) == plain
    assert sealed_for_current(stored)
    assert not sealed_for_current(plain)


def test_previous_key_opens_and_current_key_reseals(monkeypatch):
    previous = "previous-session-secret-0123456789abcd"
    current = "current-session-secret-0123456789abcdef"
    monkeypatch.setenv("SESSION_SECRET", previous)
    monkeypatch.delenv("SESSION_SECRET_PREVIOUS", raising=False)
    stored = seal("JBSWY3DPEHPK3PXP")
    monkeypatch.setenv("SESSION_SECRET", current)
    monkeypatch.setenv("SESSION_SECRET_PREVIOUS", previous)
    assert open_secret(stored) == "JBSWY3DPEHPK3PXP"
    assert not sealed_for_current(stored)
    moved = seal(open_secret(stored))
    assert sealed_for_current(moved) and "JBSWY3DPEHPK3PXP" not in moved
    monkeypatch.delenv("SESSION_SECRET_PREVIOUS")
    assert open_secret(moved) == "JBSWY3DPEHPK3PXP"


def test_broken_ciphertext_is_not_empty_plaintext():
    with pytest.raises(TotpUnavailable):
        open_secret("sp1:AAAA")
    with pytest.raises(TotpUnavailable):
        open_secret("not-a-seed")
    with pytest.raises(TotpUnavailable):
        open_secret(None)


def test_seal_refuses_without_a_session_secret(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "change-me")
    monkeypatch.delenv("SESSION_SECRET_PREVIOUS", raising=False)
    with pytest.raises(TotpUnavailable):
        seal("JBSWY3DPEHPK3PXP")


@pytest.mark.asyncio
async def test_login_seals_a_legacy_seed_and_keeps_bytes_when_open_fails(env):
    async with env["session"]() as s:
        op = await s.get(Operator, env["oid"])
        assert is_sealed(op.totp_secret)
        assert env["secret"] not in op.totp_secret
        op.totp_secret = "sp1:not-a-valid-seed"
        await s.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                  base_url="https://testserver", follow_redirects=False) as client:
        page = await client.get("/login")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        code = pyotp.TOTP(env["secret"]).now()
        response = await client.post("/login", data={"csrf_token": csrf, "login": "admin",
                                                      "password": "correct-password-123", "code": code})
        assert response.status_code == 401
    async with env["session"]() as s:
        op = await s.get(Operator, env["oid"])
        assert op.totp_secret == "sp1:not-a-valid-seed"
        assert env["secret"] not in (op.totp_secret or "")
