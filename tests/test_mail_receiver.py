"""Shop MX: DKIM/SPF/DMARC, relay protection, greylisting, limits, ClamAV, STARTTLS, DMARC and Support Pro delivery."""
import asyncio
import base64
import datetime as dt
import gzip
import hashlib
import json
import re
import smtplib
import ssl
import time

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import db as app_db, mail_auth, mail_domain, mail_receiver as mx
from app.config import settings
from app.models import DmarcReport
from test_subscription_commerce import database

SENDER = "sender.example"


def rsa_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return key, base64.b64encode(public).decode()


def ed_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key = ed25519.Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, base64.b64encode(raw).decode()


# An independent signer written from RFC 6376 (relaxed/relaxed), used to produce test mail.
def _relaxed_body(body: bytes) -> bytes:
    lines = body.replace(b"\r\n", b"\n").split(b"\n")
    if body.endswith((b"\n",)):
        lines = lines[:-1]
    lines = [re.sub(rb"[ \t]+", b" ", line).rstrip(b" ") for line in lines]
    while lines and not lines[-1]:
        lines.pop()
    return b"".join(line + b"\r\n" for line in lines)


def _relaxed_header(name: str, value: str) -> bytes:
    return (name.lower() + ":" + re.sub(r"[ \t]+", " ", value.replace("\r\n", "")).strip()).encode()


def sign(headers: list[tuple[str, str]], body: str, key, domain=SENDER, selector="s1", algorithm="rsa-sha256") -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    body_bytes = body.replace("\n", "\r\n").encode()
    bh = base64.b64encode(hashlib.sha256(_relaxed_body(body_bytes)).digest()).decode()
    names = [n for n, _ in headers]
    value = f" v=1; a={algorithm}; c=relaxed/relaxed; d={domain}; s={selector}; h={':'.join(n.lower() for n in names)}; bh={bh}; b="
    data = b"".join(_relaxed_header(n, v) + b"\r\n" for n, v in headers) + _relaxed_header("DKIM-Signature", value)
    if algorithm == "ed25519-sha256":
        signature = key.sign(hashlib.sha256(data).digest())
    else:
        signature = key.sign(data, padding.PKCS1v15(), hashes.SHA256())
    value += base64.b64encode(signature).decode()
    head = "".join(f"{n}:{v}\r\n" for n, v in [("DKIM-Signature", value), *headers])
    return head.encode() + b"\r\n" + body_bytes


def message(from_addr=f"anna@{SENDER}", subject="Не работает VPN", body="Здравствуйте!\nНе подключается.\n", extra=()):
    headers = [("From", f" Anna <{from_addr}>"), ("To", " support@shop.example"), ("Subject", f" {subject}"),
               ("Message-ID", f" <{time.time_ns()}@{SENDER}>"), ("Date", " Fri, 23 Oct 2026 10:00:00 +0000"), *extra]
    return headers, body


# ---------------------------------------------------------------- canonicalization (RFC 6376, 3.4.5)

def test_canonicalization_examples_from_the_rfc():
    fields, body = mail_auth.split_message(b"A: X\r\nB : Y\t\r\n\tZ  \r\n\r\n C \r\nD \t E\r\n\r\n\r\n")
    assert [mail_auth.canon_header(f, "relaxed") for f in fields] == [b"a:X", b"b:Y Z"]
    assert [mail_auth.canon_header(f, "simple") for f in fields] == [b"A: X", b"B : Y\t\r\n\tZ  "]
    assert mail_auth.canon_body(body, "relaxed") == b" C\r\nD E\r\n"
    assert mail_auth.canon_body(body, "simple") == b" C \r\nD \t E\r\n"
    assert mail_auth.canon_body(b"", "simple") == b"\r\n" and mail_auth.canon_body(b"", "relaxed") == b""


# ---------------------------------------------------------------- DNS and the server

class Dns:
    def __init__(self):
        self.zone = {}

    def handler(self, request):
        name, rtype = request.url.params["name"], request.url.params["type"]
        values = self.zone.get((name, rtype))
        if values is None:
            return httpx.Response(200, json={"Status": 3})
        return httpx.Response(200, json={"Status": 0, "Answer": [{"name": name, "type": mail_domain.TYPES[rtype], "data": v} for v in values]})


@pytest.fixture
def world(monkeypatch, database):
    dns = Dns()
    rsa, rsa_public = rsa_key()
    ed, ed_public = ed_key()
    dns.zone.update({
        (SENDER, "TXT"): ['"v=spf1 ip4:127.0.0.1 -all"'],
        (f"s1._domainkey.{SENDER}", "TXT"): [f'"v=DKIM1; k=rsa; p={rsa_public}"'],
        (f"e1._domainkey.{SENDER}", "TXT"): [f'"v=DKIM1; k=ed25519; p={ed_public}"'],
        (f"_dmarc.{SENDER}", "TXT"): ['"v=DMARC1; p=reject"'],
        ("strict.example", "TXT"): ['"v=spf1 ip4:192.0.2.1 -all"'],
        ("relay.example", "TXT"): ['"v=spf1 ip4:127.0.0.1 -all"'],
        ("google.com", "TXT"): ['"v=spf1 ip4:127.0.0.1 -all"'],
    })
    monkeypatch.setattr(mail_domain, "client_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(dns.handler)))
    for key, value in {"mail_receiver_routes": "support@shop.example=support,dmarc@shop.example=dmarc", "mail_receiver_hostname": "mx.shop.example",
                       "mail_receiver_greylist": False, "mail_receiver_clamav": "", "mail_receiver_max_mb": 1, "mail_domain": "shop.example",
                       "mail_support_inbound_url": "http://support_pro:8000/email/inbound", "mail_inbound_secret": "inbound-secret-0123456789abcdef"}.items():
        monkeypatch.setattr(settings, key, value)
    posted = []

    def support(request):
        posted.append(request)
        return httpx.Response(200, json={"result": "created"})

    monkeypatch.setattr(mx, "http_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(support)))
    monkeypatch.setattr(app_db, "SessionLocal", async_sessionmaker(database.bind, expire_on_commit=False))
    return {"dns": dns, "rsa": rsa, "ed": ed, "posted": posted, "db": database}


@pytest_asyncio.fixture
async def server(world):
    receiver = mx.Receiver(mx.MemoryState())
    srv = await asyncio.start_server(receiver.handle, "127.0.0.1", 0, limit=mx.MAX_LINE)
    port = srv.sockets[0].getsockname()[1]
    yield {"port": port, "receiver": receiver, **world}
    srv.close()
    await srv.wait_closed()


def smtp(port, fn):
    def run():
        with smtplib.SMTP("127.0.0.1", port, timeout=10) as client:
            client.ehlo("client.example")
            return fn(client)
    return asyncio.to_thread(run)


def code_of(fn):
    def wrapped(client):
        try:
            return fn(client)
        except smtplib.SMTPResponseException as exc:
            return exc.smtp_code
        except smtplib.SMTPRecipientsRefused as exc:
            return list(exc.recipients.values())[0][0]
        except smtplib.SMTPSenderRefused as exc:
            return exc.smtp_code
    return wrapped


# ---------------------------------------------------------------- dialog

@pytest.mark.asyncio
async def test_relay_is_refused_and_signed_mail_reaches_support_pro(server):
    refused = await smtp(server["port"], code_of(lambda c: c.sendmail(f"anna@{SENDER}", ["victim@other.example"], b"Subject: x\r\n\r\nhi")))
    assert refused == 550
    headers, body = message()
    raw = sign(headers, body, server["rsa"])
    result = await smtp(server["port"], code_of(lambda c: c.sendmail(f"anna@{SENDER}", ["support@shop.example"], raw) or 250))
    assert result == 250
    request = server["posted"][0]
    content = request.content
    timestamp = request.headers["x-mail-timestamp"]
    assert request.headers["x-mail-signature"] == mx.support_signature(content, timestamp, settings.mail_inbound_secret)
    top = content.split(b"\r\n", 1)[0].decode()
    assert top.startswith("Authentication-Results: mx.shop.example;") and "spf=pass" in top and "dkim=pass header.d=sender.example" in top and "dmarc=pass" in top
    assert b"Received: from client.example ([127.0.0.1])" in content
    journal = await server["receiver"].state.recent()
    assert journal[0]["outcome"] == "accepted" and "support: created" in journal[0]["detail"]


@pytest.mark.asyncio
async def test_ed25519_signature_and_forged_results_are_handled(server):
    headers, body = message()
    forged = b"Authentication-Results: mx.shop.example; dmarc=pass header.from=bank.example\r\n"
    raw = forged + sign(headers, body, server["ed"], selector="e1", algorithm="ed25519-sha256")
    assert await smtp(server["port"], code_of(lambda c: c.sendmail(f"anna@{SENDER}", ["support@shop.example"], raw) or 250)) == 250
    content = server["posted"][0].content
    assert content.count(b"Authentication-Results: mx.shop.example") == 1, "a forged header with our name is removed"
    assert b"dkim=pass header.d=sender.example" in content and b"bank.example" not in content


@pytest.mark.asyncio
async def test_spf_fail_and_dmarc_reject_are_refused(server):
    plain = b"From: x@strict.example\r\nSubject: hi\r\n\r\nhello\r\n"
    assert await smtp(server["port"], code_of(lambda c: c.sendmail("x@strict.example", ["support@shop.example"], plain) or 250)) == 550
    # Envelope from an SPF-passing relay, From: a p=reject domain without a valid signature.
    headers, body = message()
    tampered = sign(headers, body, server["rsa"]).replace(b"\xd0\x9d\xd0\xb5 \xd0\xbf", b"\xd0\x92\xd1\x81\xd1\x91 \xd0\xbf")
    assert tampered != sign(headers, body, server["rsa"])
    result = await smtp(server["port"], code_of(lambda c: c.sendmail("bounce@relay.example", ["support@shop.example"], tampered) or 250))
    assert result == 550
    journal = await server["receiver"].state.recent()
    assert "DMARC reject" in journal[0]["detail"] and "SPF fail" in journal[1]["detail"]
    assert server["posted"] == []


@pytest.mark.asyncio
async def test_dkim_failure_reasons(world):
    headers, body = message()
    raw = sign(headers, body, world["rsa"])
    async with mail_domain.client_factory() as client:
        dns = mail_domain.Resolver(client)
        assert [r.result for r in await mail_auth.dkim(dns, raw)] == ["pass"]
        assert (await mail_auth.dkim(dns, raw.replace(b"Subject: \xd0\x9d", b"Subject: \xd0\x9f")))[0].reason == "signature"
        assert (await mail_auth.dkim(dns, raw + b"extra line\r\n"))[0].reason == "body hash"
        world["dns"].zone[(f"s1._domainkey.{SENDER}", "TXT")] = ['"v=DKIM1; k=rsa; p="']
        assert (await mail_auth.dkim(mail_domain.Resolver(client), raw))[0].reason == "key revoked", "a fresh lookup sees the revoked key"
        assert await mail_auth.dkim(dns, b"From: a@b.example\r\n\r\nbody") == []
        assert mail_auth.header_from(b"From: a@one.example\r\nFrom: b@two.example\r\n\r\n") == "", "two From fields"


@pytest.mark.asyncio
async def test_size_limits_too_long_lines_and_order(server):
    big = b"From: a@" + SENDER.encode() + b"\r\nSubject: big\r\n\r\n" + (b"x" * 998 + b"\r\n") * 1100
    assert await smtp(server["port"], code_of(lambda c: c.sendmail(f"a@{SENDER}", ["support@shop.example"], big) or 250)) == 552
    assert await smtp(server["port"], code_of(lambda c: c.mail(f"a@{SENDER}", ["SIZE=99999999"])[0])) == 552
    assert await smtp(server["port"], code_of(lambda c: c.rcpt("support@shop.example")[0])) == 503

    async def long_line():
        reader, writer = await asyncio.open_connection("127.0.0.1", server["port"])
        await reader.readline()
        writer.write(b"EHLO " + b"a" * 5000 + b"\r\n")
        await writer.drain()
        reply = await reader.readline()
        writer.close()
        return reply

    assert (await long_line()).startswith(b"500")


@pytest.mark.asyncio
async def test_greylisting_rate_limit_and_connection_limit(server, monkeypatch):
    monkeypatch.setattr(settings, "mail_receiver_greylist", True)
    headers, body = message()
    raw = sign(headers, body, server["rsa"])
    send = code_of(lambda c: c.sendmail(f"anna@{SENDER}", ["support@shop.example"], raw) or 250)
    assert await smtp(server["port"], send) == 451
    assert await smtp(server["port"], send) == 451, "retried too early"
    clock = time.time() + 120
    monkeypatch.setattr(mx.time, "time", lambda: clock)
    assert await smtp(server["port"], send) == 250
    assert await smtp(server["port"], code_of(lambda c: c.sendmail(f"other@{SENDER}", ["support@shop.example"], raw) or 250)) == 250, "the sender domain is whitelisted"
    monkeypatch.setattr(mx, "RATE_MESSAGES", 4)
    assert await smtp(server["port"], code_of(lambda c: c.mail(f"anna@{SENDER}")[0])) == 450
    server["receiver"].connections["127.0.0.1"] = mx.PER_IP_CONNECTIONS
    with pytest.raises(smtplib.SMTPConnectError) as busy:
        await smtp(server["port"], lambda c: c.noop())
    assert busy.value.smtp_code == 421


async def clamd(reply: bytes):
    async def handle(reader, writer):
        await reader.readuntil(b"\0")
        while True:
            size = int.from_bytes(await reader.readexactly(4), "big")
            if size == 0:
                break
            await reader.readexactly(size)
        writer.write(reply)
        await writer.drain()
        writer.close()

    srv = await asyncio.start_server(handle, "127.0.0.1", 0)
    return srv, srv.sockets[0].getsockname()[1]


@pytest.mark.asyncio
async def test_clamav_rejects_malware_and_defers_when_down(server, monkeypatch):
    headers, body = message()
    raw = sign(headers, body, server["rsa"])
    send = code_of(lambda c: c.sendmail(f"anna@{SENDER}", ["support@shop.example"], raw) or 250)
    srv, port = await clamd(b"stream: Eicar-Test-Signature FOUND\0")
    monkeypatch.setattr(settings, "mail_receiver_clamav", f"127.0.0.1:{port}")
    assert await smtp(server["port"], send) == 554
    srv.close()
    srv, port = await clamd(b"stream: OK\0")
    monkeypatch.setattr(settings, "mail_receiver_clamav", f"127.0.0.1:{port}")
    assert await smtp(server["port"], send) == 250
    srv.close()
    monkeypatch.setattr(settings, "mail_receiver_clamav", "127.0.0.1:1")
    assert await smtp(server["port"], send) == 451


@pytest.mark.asyncio
async def test_support_pro_outage_is_a_temporary_failure(server, monkeypatch):
    monkeypatch.setattr(mx, "http_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    headers, body = message()
    raw = sign(headers, body, server["rsa"])
    assert await smtp(server["port"], code_of(lambda c: c.sendmail(f"anna@{SENDER}", ["support@shop.example"], raw) or 250)) == 451


@pytest.mark.asyncio
async def test_dmarc_reports_arrive_by_smtp(server):
    begin = int(time.time()) - 86400
    xml = (f"<?xml version='1.0'?><feedback><report_metadata><org_name>google.com</org_name><email>noreply-dmarc-support@google.com</email>"
           f"<report_id>mx-1</report_id><date_range><begin>{begin}</begin><end>{begin + 3600}</end></date_range></report_metadata>"
           "<policy_published><domain>shop.example</domain><p>reject</p></policy_published><record><row><source_ip>198.51.100.7</source_ip>"
           "<count>5</count><policy_evaluated><disposition>none</disposition><dkim>pass</dkim><spf>pass</spf></policy_evaluated></row>"
           "<identifiers><header_from>shop.example</header_from></identifiers></record></feedback>").encode()
    from email.message import EmailMessage

    mail = EmailMessage()
    mail["From"], mail["To"], mail["Subject"] = "noreply-dmarc-support@google.com", "dmarc@shop.example", "Report domain: shop.example"
    mail.set_content("report")
    mail.add_attachment(gzip.compress(xml), maintype="application", subtype="gzip", filename="google.com!shop.example.xml.gz")
    result = await smtp(server["port"], code_of(lambda c: c.sendmail("noreply-dmarc-support@google.com", ["dmarc@shop.example"], mail.as_bytes()) or 250))
    assert result == 250
    report = await server["db"].scalar(select(DmarcReport).where(DmarcReport.report_id == "mx-1"))
    assert report and report.source == "smtp" and report.messages == 5


@pytest.mark.asyncio
async def test_starttls(world, tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mx.shop.example")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(now).not_valid_after(now + dt.timedelta(days=1)).sign(key, hashes.SHA256())
    (tmp_path / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(str(tmp_path / "cert.pem"), str(tmp_path / "key.pem"))
    receiver = mx.Receiver(mx.MemoryState(), context)
    srv = await asyncio.start_server(receiver.handle, "127.0.0.1", 0, limit=mx.MAX_LINE)
    port = srv.sockets[0].getsockname()[1]
    headers, body = message()
    raw = sign(headers, body, world["rsa"])

    def run():
        with smtplib.SMTP("127.0.0.1", port, timeout=10) as client:
            client.ehlo("client.example")
            assert client.has_extn("starttls")
            client.starttls(context=ssl._create_unverified_context())
            client.ehlo("client.example")
            assert not client.has_extn("starttls")
            client.sendmail(f"anna@{SENDER}", ["support@shop.example"], raw)

    await asyncio.to_thread(run)
    srv.close()
    assert b"with ESMTPS" in world["posted"][0].content


def test_routes_and_settings_registry():
    settings.mail_receiver_routes, before = "support@shop.example=support, broken, dmarc@shop.example=dmarc, x@shop.example=ftp", settings.mail_receiver_routes
    try:
        assert mx.routes() == {"support@shop.example": "support", "dmarc@shop.example": "dmarc"}
    finally:
        settings.mail_receiver_routes = before
    from app.runtime_settings import RESTART_REQUIRED

    keys = {item["key"] for item in RESTART_REQUIRED}
    assert {"mail_receiver_enabled", "mail_receiver_routes", "mail_inbound_secret"} <= keys
