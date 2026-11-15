"""Signed inbound endpoint used by the shop's own MX: signature, freshness, size, duplicates."""
import time

import pytest
from sqlalchemy import func, select

from app import email_inbound
from app.models import EmailLink, Message, Ticket
from test_email_channel import mail

SECRET = "inbound-secret-0123456789abcdef"


def headers(raw, timestamp=None, secret=SECRET):
    timestamp = str(int(timestamp if timestamp is not None else time.time()))
    return {"Content-Type": "message/rfc822", "X-Mail-Timestamp": timestamp, "X-Mail-Signature": email_inbound.expected(raw, timestamp, secret)}


@pytest.mark.parametrize("env", ["sqlite", "postgres"], indirect=True)
async def test_signed_mail_becomes_a_ticket_once(env, monkeypatch):
    monkeypatch.setenv("MAIL_INBOUND_SECRET", SECRET)
    raw = b"Authentication-Results: mx.shop.example; spf=pass smtp.mailfrom=example.org; dkim=pass header.d=example.org; dmarc=pass (p=reject) header.from=example.org\r\n" + mail()
    first = await env["client"].post("/email/inbound", content=raw, headers=headers(raw))
    assert first.status_code == 200 and first.json() == {"result": "created"}
    again = await env["client"].post("/email/inbound", content=raw, headers=headers(raw))
    assert again.json() == {"result": "duplicate"}
    async with env["session"]() as s:
        assert await s.scalar(select(func.count()).select_from(Ticket).where(Ticket.channel == "email")) == 1
        link = await s.scalar(select(EmailLink))
        assert link.auth == "pass", "the MX verdict on top is trusted"
        assert await s.scalar(select(func.count()).select_from(Message)) == 1


@pytest.mark.parametrize("env", ["sqlite"], indirect=True)
async def test_bad_signature_stale_request_and_disabled_endpoint(env, monkeypatch):
    raw = mail(subject="forged")
    monkeypatch.delenv("MAIL_INBOUND_SECRET", raising=False)
    assert (await env["client"].post("/email/inbound", content=raw, headers=headers(raw))).status_code == 404
    monkeypatch.setenv("MAIL_INBOUND_SECRET", SECRET)
    assert (await env["client"].post("/email/inbound", content=raw, headers=headers(raw, secret="other-secret"))).status_code == 401
    assert (await env["client"].post("/email/inbound", content=raw, headers=headers(raw, timestamp=time.time() - 600))).status_code == 401
    tampered = headers(raw)
    assert (await env["client"].post("/email/inbound", content=raw + b"x", headers=tampered)).status_code == 401
    monkeypatch.setenv("EMAIL_MAX_MB", "1")
    big = mail(body="x" * (4 * 1024 * 1024))
    assert (await env["client"].post("/email/inbound", content=big, headers=headers(big))).status_code == 413
    async with env["session"]() as s:
        assert await s.scalar(select(func.count()).select_from(Ticket)) == 0
