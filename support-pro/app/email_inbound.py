"""Signed inbound endpoint for the shop's own MX (mail_receiver).

The shop's receive-only SMTP server accepts mail for ``support@`` and posts the raw
message here. The body is authenticated with HMAC-SHA256 over the timestamp and the
SHA-256 of the message, using ``MAIL_INBOUND_SECRET`` shared by both sides; requests
older than five minutes are refused. The message then goes through the email
channel's normal parsing and ingestion, so duplicates (same Message-ID), auto-replies,
lists, loops and bounces are handled exactly as for the IMAP intake. The receiver put
its ``Authentication-Results`` header on top, which the channel already trusts.
"""
import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request

from . import main as m
from . import email_channel

app = m.app
MAX_SKEW = 300


def secret() -> str:
    return os.getenv("MAIL_INBOUND_SECRET", "").strip()


def expected(raw: bytes, timestamp: str, key: str) -> str:
    return hmac.new(key.encode(), timestamp.encode() + b"." + hashlib.sha256(raw).hexdigest().encode(), hashlib.sha256).hexdigest()


@app.post('/email/inbound')
async def email_inbound(request: Request):
    key = secret()
    if not key:
        raise HTTPException(404, 'Not found')
    timestamp = request.headers.get('x-mail-timestamp', '')
    signature = request.headers.get('x-mail-signature', '')
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > MAX_SKEW:
        raise HTTPException(401, 'Stale or missing timestamp')
    raw = await request.body()
    if len(raw) > email_channel.max_bytes() * 2 + 1024 * 1024:
        raise HTTPException(413, 'Message too large')
    if not hmac.compare_digest(signature, expected(raw, timestamp, key)):
        raise HTTPException(401, 'Bad signature')
    inbound = email_channel.parse(raw)
    async with m.Session() as s:
        result = await email_channel.ingest(s, inbound)
        await s.commit()
    return {'result': result}
