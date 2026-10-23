"""Mail domain health: MX/SPF/DKIM/DMARC checks, DMARC report intake, abuse limits, retention and erasure."""
import gzip
import io
import json
import zipfile
from datetime import datetime, timedelta
from email.message import EmailMessage
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from starlette.datastructures import UploadFile

from app import mail_domain as mail
from app.config import settings
from app.models import AppSetting, AuditLog, DmarcIntakeState, DmarcRecord, DmarcReport
from app.security import encrypt_secret
from test_subscription_commerce import database

ADMIN = SimpleNamespace(email="admin@example.test", role="admin")
DOMAIN = "shop.example"


class Dns:
    """DNS-over-HTTPS JSON API with a fixed zone; counts queries per name."""

    def __init__(self):
        self.zone = {
            (DOMAIN, "MX"): ["10 mx.shop.example."],
            ("mx.shop.example", "A"): ["203.0.113.10"],
            (DOMAIN, "TXT"): ['"v=spf1 include:_spf.provider.example -all"', '"google-site-verification=abc"'],
            ("_spf.provider.example", "TXT"): ['"v=spf1 ip4:198.51.100.0/24 ip6:2001:db8:5::/48 ~all"'],
            ("smtp.provider.example", "A"): ["198.51.100.7"],
            (f"_dmarc.{DOMAIN}", "TXT"): [f'"v=DMARC1; p=reject; rua=mailto:dmarc@{DOMAIN}"'],
        }
        self.status = 200
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        name, rtype = request.url.params["name"], request.url.params["type"]
        self.calls.append((name, rtype))
        assert request.headers["accept"] == "application/dns-json"
        if self.status != 200:
            return httpx.Response(self.status)
        values = self.zone.get((name, rtype))
        if values is None:
            exists = any(n == name for n, _ in self.zone)
            return httpx.Response(200, json={"Status": 0 if exists else 3})
        return httpx.Response(200, json={"Status": 0, "Answer": [{"name": name, "type": mail.TYPES[rtype], "data": v} for v in values]})


@pytest.fixture
def dns(monkeypatch):
    fake = Dns()
    monkeypatch.setattr(mail, "client_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    monkeypatch.setattr(settings, "mail_domain", "")
    monkeypatch.setattr(settings, "smtp_from", f"VPN Shop <noreply@{DOMAIN}>")
    monkeypatch.setattr(settings, "smtp_host", "smtp.provider.example")
    monkeypatch.setattr(settings, "dmarc_imap_user", "")
    monkeypatch.setattr(settings, "dmarc_imap_host", "")
    monkeypatch.setattr(settings, "dmarc_imap_password", "")
    monkeypatch.setattr(settings, "dmarc_report_retention_days", 180)
    mail._manual.clear()
    return fake


async def dkim_key(database, selector="shop"):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    body = "".join(line for line in public.splitlines() if not line.startswith("-----"))
    database.add(AppSetting(key="dkim_private", value=json.dumps({"selector": selector, "domain": DOMAIN, "private": encrypt_secret(private)})))
    await database.commit()
    return body


def by_check(result, check):
    return [f for f in result["findings"] if f["check"] == check]


def chunks(body: str) -> str:
    # Long TXT records arrive as several quoted strings.
    return " ".join(f'"{body[i:i + 200]}"' for i in range(0, len(body), 200))


# ---------------------------------------------------------------- DNS checks

@pytest.mark.asyncio
async def test_healthy_domain_passes_every_check(database, dns):
    body = await dkim_key(database)
    dns.zone[(f"shop._domainkey.{DOMAIN}", "TXT")] = [chunks(f"v=DKIM1; k=rsa; p={body}")]
    result = await mail.run_checks(database)
    assert result["domain"] == DOMAIN and result["status"] == "ok", result["findings"]
    assert {f["check"] for f in result["findings"]} == {"mx", "spf", "dkim", "dmarc"}
    assert "198.51.100.7 разрешён" in by_check(result, "spf")[0]["detail"]
    assert "совпадает" in by_check(result, "dkim")[0]["detail"]
    await database.commit()
    view = await mail.admin_mail_domain(database, ADMIN)
    assert view["check"]["status"] == "ok" and view["domain"] == DOMAIN


@pytest.mark.asyncio
async def test_spf_failures_are_reported(database, dns):
    dns.zone[(DOMAIN, "TXT")] = ['"v=spf1 +all"']
    assert by_check(await mail.run_checks(database), "spf")[0]["status"] == "fail"
    dns.zone[(DOMAIN, "TXT")] = ['"v=spf1 -all"', '"v=spf1 include:_spf.provider.example -all"']
    assert "Несколько" in by_check(await mail.run_checks(database), "spf")[0]["title"]
    # Eleven nested includes exceed the 10-lookup limit of RFC 7208.
    dns.zone[(DOMAIN, "TXT")] = ['"v=spf1 include:l1.example -all"']
    for i in range(1, 12):
        dns.zone[(f"l{i}.example", "TXT")] = [f'"v=spf1 include:l{i + 1}.example -all"' if i < 11 else '"v=spf1 -all"']
    spf = by_check(await mail.run_checks(database), "spf")
    assert spf[0]["status"] == "fail" and "10 DNS" in spf[0]["detail"]
    dns.zone[(DOMAIN, "TXT")] = ['"v=spf1 include:missing.example -all"']
    assert "без SPF" in by_check(await mail.run_checks(database), "spf")[0]["detail"]
    dns.zone[(DOMAIN, "TXT")] = ['"v=spf1 ip4:192.0.2.1"']
    titles = [f["title"] for f in by_check(await mail.run_checks(database), "spf")]
    assert any("без завершающего all" in t for t in titles)
    assert any("198.51.100.7 не входит в SPF" in t for t in titles), "SMTP address outside the policy"
    dns.zone.pop((DOMAIN, "TXT"))
    assert by_check(await mail.run_checks(database), "spf")[0]["title"] == "Нет SPF-записи"


@pytest.mark.asyncio
async def test_spf_counts_lookups_after_a_match_and_handles_a_mx_cidr(database, dns):
    dns.zone[(DOMAIN, "TXT")] = ['"v=spf1 a:relay.shop.example/24 mx include:_spf.provider.example -all"']
    dns.zone[("relay.shop.example", "A")] = ["198.51.100.200"]
    result = await mail.run_checks(database)
    spf = by_check(result, "spf")
    assert spf[0]["status"] == "ok" and "Запросов DNS: 3" in spf[0]["detail"], spf


@pytest.mark.asyncio
async def test_dkim_mismatch_revoked_and_selector_hint(database, dns):
    assert by_check(await mail.run_checks(database), "dkim")[0]["status"] == "info"
    await dkim_key(database)
    dns.zone[(f"shop._domainkey.{DOMAIN}", "TXT")] = ['"v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAother"']
    dkim = by_check(await mail.run_checks(database), "dkim")
    assert dkim[0]["status"] == "fail" and "не совпадает" in dkim[0]["title"]
    dns.zone[(f"s1._domainkey.{DOMAIN}", "TXT")] = ['"v=DKIM1; p="']
    dkim = by_check(await mail.run_checks(database, ["s1"]), "dkim")
    assert any("отозван" in f["title"] for f in dkim)
    with pytest.raises(HTTPException) as bad:
        await mail.admin_mail_check(mail.CheckIn(dkim_selectors=["bad selector"]), database, ADMIN)
    assert bad.value.status_code == 422


@pytest.mark.asyncio
async def test_dmarc_policy_reports_and_external_authorization(database, dns):
    dns.zone[(f"_dmarc.{DOMAIN}", "TXT")] = ['"v=DMARC1; p=none"']
    titles = [f["title"] for f in by_check(await mail.run_checks(database), "dmarc")]
    assert any("p=none" in t for t in titles) and any("rua" in t for t in titles)
    dns.zone[(f"_dmarc.{DOMAIN}", "TXT")] = ['"v=DMARC1; p=quarantine; pct=50; rua=mailto:reports@dmarc-vendor.example"']
    titles = [f["title"] for f in by_check(await mail.run_checks(database), "dmarc")]
    assert any("50%" in t for t in titles)
    assert any("dmarc-vendor.example не подтвердил" in t for t in titles)
    dns.zone[(f"{DOMAIN}._report._dmarc.dmarc-vendor.example", "TXT")] = ['"v=DMARC1"']
    titles = [f["title"] for f in by_check(await mail.run_checks(database), "dmarc")]
    assert not any("не подтвердил" in t for t in titles)
    dns.zone.pop((f"_dmarc.{DOMAIN}", "TXT"))
    assert by_check(await mail.run_checks(database), "dmarc")[0]["title"] == "Нет DMARC-записи"


@pytest.mark.asyncio
async def test_mx_problems_resolver_failure_and_missing_domain(database, dns, monkeypatch):
    dns.zone[(DOMAIN, "MX")] = ["10 gone.shop.example."]
    assert by_check(await mail.run_checks(database), "mx")[0]["status"] == "fail"
    dns.zone[(DOMAIN, "MX")] = ["0 ."]
    assert "null MX" in by_check(await mail.run_checks(database), "mx")[0]["title"]
    dns.zone.pop((DOMAIN, "MX"))
    assert by_check(await mail.run_checks(database), "mx")[0]["title"] == "Нет MX-записи"
    dns.status = 503
    result = await mail.run_checks(database)
    assert result["status"] == "warn"
    assert {f["check"] for f in result["findings"] if f["title"] == "Проверка не выполнена"} == {"mx", "spf", "dmarc"}
    monkeypatch.setattr(settings, "smtp_from", "")
    monkeypatch.setattr(settings, "smtp_user", "")
    assert (await mail.run_checks(database))["findings"][0]["check"] == "domain"


@pytest.mark.asyncio
async def test_manual_check_is_audited_and_throttled(database, dns):
    await mail.admin_mail_check(mail.CheckIn(), database, ADMIN)
    assert await database.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "mail.domain.check")) == 1
    with pytest.raises(HTTPException) as again:
        await mail.admin_mail_check(mail.CheckIn(), database, ADMIN)
    assert again.value.status_code == 429


# ---------------------------------------------------------------- reports

def report_xml(report_id="r-1", domain=DOMAIN, org="google.com", rows=None, begin=None, extra=""):
    begin = begin or int((datetime.utcnow() - timedelta(days=1)).timestamp())
    rows = rows if rows is not None else [("198.51.100.7", 120, "pass", "pass", "none"), ("192.0.2.66", 7, "fail", "fail", "reject")]
    records = "".join(f"""<record><row><source_ip>{ip}</source_ip><count>{count}</count><policy_evaluated><disposition>{disp}</disposition>
<dkim>{dkim}</dkim><spf>{spf}</spf></policy_evaluated></row><identifiers><header_from>{domain}</header_from></identifiers>
<auth_results><dkim><domain>{domain}</domain><result>{dkim}</result></dkim><spf><domain>{domain}</domain><result>{spf}</result></spf></auth_results></record>"""
                      for ip, count, dkim, spf, disp in rows)
    return f"""<?xml version="1.0" encoding="UTF-8"?>{extra}<feedback><report_metadata><org_name>{org}</org_name><email>noreply-dmarc-support@{org}</email>
<report_id>{report_id}</report_id><date_range><begin>{begin}</begin><end>{begin + 86400}</end></date_range></report_metadata>
<policy_published><domain>{domain}</domain><adkim>r</adkim><aspf>r</aspf><p>reject</p><pct>100</pct></policy_published>{records}</feedback>""".encode()


def zipped(name, data, extra=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, data)
        if extra:
            archive.writestr(extra, data)
    return buffer.getvalue()


def upload(data, name="report.xml.gz"):
    return UploadFile(io.BytesIO(data), filename=name)


@pytest.mark.asyncio
async def test_upload_gzip_zip_and_xml_with_duplicates(database, dns):
    first = await mail.admin_dmarc_upload(upload(gzip.compress(report_xml("r-1"))), database, ADMIN)
    assert first["outcome"] == "imported"
    assert (await mail.admin_dmarc_upload(upload(zipped("r.xml", report_xml("r-2")), "r.zip"), database, ADMIN))["outcome"] == "imported"
    assert (await mail.admin_dmarc_upload(upload(report_xml("r-3"), "r.xml"), database, ADMIN))["outcome"] == "imported"
    again = await mail.admin_dmarc_upload(upload(zipped("r.xml", report_xml("r-1")), "resent.zip"), database, ADMIN)
    assert again["outcome"] == "duplicate"
    assert await database.scalar(select(func.count(DmarcReport.id))) == 3
    assert await database.scalar(select(func.count(DmarcRecord.id))) == 6
    summary = again["summary"]
    assert summary["messages"] == 381 and summary["failed"] == 21 and summary["pass_rate"] == 94.5
    assert summary["sources"][0]["ip"] == "192.0.2.66" and summary["sources"][0]["dispositions"] == {"reject": 21}
    report = again["reports"][0]
    detail = await mail.admin_dmarc_report(report["id"], database, ADMIN)
    assert {r["source_ip"] for r in detail["records"]} == {"198.51.100.7", "192.0.2.66"}
    state = await database.get(DmarcIntakeState, "imap")
    assert (state.imported, state.duplicates) == (3, 1) and state.journal[0]["outcome"] == "duplicate"


@pytest.mark.parametrize("payload,reason", [
    (lambda: report_xml(domain="victim.example"), "чужом домене"),
    (lambda: report_xml(extra='<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>'), "DOCTYPE"),
    (lambda: gzip.compress(b"\0" * (60 * 1024 * 1024)), "50 МБ"),
    (lambda: zipped("a.xml", report_xml(), extra="b.xml"), "один XML"),
    (lambda: b"x" * (6 * 1024 * 1024), "5 МБ"),
    (lambda: report_xml(rows=[("not-an-ip", 1, "pass", "pass", "none")]), "source_ip"),
    (lambda: report_xml(begin=int((datetime.utcnow() + timedelta(days=10)).timestamp())), "будущем"),
    (lambda: b"<html>not a report</html>", "feedback"),
    (lambda: gzip.compress(b"\x00garbage"), "XML"),
])
@pytest.mark.asyncio
async def test_hostile_or_foreign_reports_are_rejected(database, dns, payload, reason):
    with pytest.raises(HTTPException) as rejected:
        await mail.admin_dmarc_upload(upload(payload()), database, ADMIN)
    assert rejected.value.status_code == 422 and reason in rejected.value.detail
    assert await database.scalar(select(func.count(DmarcReport.id))) == 0
    state = await database.get(DmarcIntakeState, "imap")
    assert state.rejected == 1 and reason in state.journal[0]["detail"]


# ---------------------------------------------------------------- IMAP intake

def report_mail(attachment: bytes | None, sender="noreply-dmarc-support@google.com", name="google.com!shop.example!1.xml.gz", ctype=("application", "gzip")):
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, f"dmarc@{DOMAIN}", f"Report domain: {DOMAIN}"
    message.set_content("DMARC aggregate report")
    if attachment is not None:
        message.add_attachment(attachment, maintype=ctype[0], subtype=ctype[1], filename=name)
    return message.as_bytes()


class Imap:
    """Read-only IMAP double: records every command so tests can prove the mailbox is never changed."""

    def __init__(self, messages, validity=7):
        self.messages, self.validity, self.commands, self.fail_login = dict(messages), validity, [], False

    def __call__(self):
        return self

    def login(self, user, password):
        self.commands.append("LOGIN")
        if self.fail_login:
            import imaplib
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, folder, readonly=False):
        self.commands.append(f"SELECT {folder} readonly={readonly}")
        return "OK", [b"1"]

    def response(self, code):
        return code, [str(self.validity).encode()]

    def uid(self, command, *args):
        self.commands.append(f"UID {command}")
        if command == "SEARCH":
            low = int(args[1].split()[1].split(":")[0])
            return "OK", [" ".join(str(u) for u in sorted(self.messages) if u >= low).encode()]
        uid, what = int(args[0]), args[1]
        raw = self.messages[uid]
        if what == "(RFC822.SIZE)":
            size = 20 * 1024 * 1024 if raw == b"HUGE" else len(raw)
            return "OK", [f"{uid} (UID {uid} RFC822.SIZE {size})".encode()]
        return "OK", [(f"{uid} (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw), b")"]

    def logout(self):
        self.commands.append("LOGOUT")


@pytest.fixture
def mailbox(dns, monkeypatch):
    monkeypatch.setattr(settings, "dmarc_imap_host", "imap.shop.example")
    monkeypatch.setattr(settings, "dmarc_imap_user", f"dmarc@{DOMAIN}")
    monkeypatch.setattr(settings, "dmarc_imap_password", "mailbox-secret")
    imap = Imap({
        1: report_mail(gzip.compress(report_xml("g-1"))),
        2: report_mail(gzip.compress(report_xml("g-1"))),                          # the same report resent
        3: report_mail(zipped("x.xml", report_xml("y-1", org="yahoo.com")), sender="spoof@attacker.example", name="r.zip", ctype=("application", "zip")),
        4: report_mail(gzip.compress(report_xml("v-1", domain="victim.example"))),  # foreign domain
        5: report_mail(None),                                                       # no report attached
        6: b"HUGE",                                                                 # above the size limit
    })
    monkeypatch.setattr(mail, "imap_factory", imap)
    return imap


@pytest.mark.asyncio
async def test_mailbox_intake_is_read_only_deduplicated_and_resumable(database, mailbox):
    stats = await mail.intake(database)
    assert stats == {"configured": True, "messages": 6, "imported": 2, "duplicate": 1, "rejected": 3}
    assert "SELECT INBOX readonly=True" in mailbox.commands
    assert not [c for c in mailbox.commands if any(word in c for word in ("STORE", "EXPUNGE", "COPY", "MOVE", "APPEND"))]
    state = await database.get(DmarcIntakeState, "imap")
    assert (state.uidvalidity, state.last_uid, state.last_error) == (7, 6, None)
    reports = {r.org_name: r for r in (await database.scalars(select(DmarcReport))).all()}
    assert reports["google.com"].sender_matches is True and reports["yahoo.com"].sender_matches is False
    assert reports["google.com"].source == "imap"
    details = " | ".join(j["detail"] for j in state.journal)
    assert "чужом домене" in details and "без вложения" in details and "больше 10 МБ" in details
    # Nothing new: the cursor makes the next cycle a no-op.
    assert (await mail.intake(database))["messages"] == 0
    # A new mailbox generation (UIDVALIDITY) restarts the scan; stored reports stay single.
    mailbox.validity = 8
    again = await mail.intake(database)
    assert again["imported"] == 0 and again["duplicate"] == 3
    assert await database.scalar(select(func.count(DmarcReport.id))) == 2


@pytest.mark.asyncio
async def test_mailbox_errors_keep_the_cursor(database, mailbox):
    mailbox.fail_login = True
    result = await mail.intake(database)
    assert "отклонил вход" in result["error"]
    state = await database.get(DmarcIntakeState, "imap")
    assert state.last_uid == 0 and "отклонил вход" in state.last_error
    assert "mailbox-secret" not in (state.last_error or "")
    with pytest.raises(HTTPException) as throttled:
        await mail.admin_dmarc_sync(database, ADMIN)
        await mail.admin_dmarc_sync(database, ADMIN)
    assert throttled.value.status_code == 429


@pytest.mark.asyncio
async def test_sync_requires_a_configured_mailbox(database, dns):
    with pytest.raises(HTTPException) as missing:
        await mail.admin_dmarc_sync(database, ADMIN)
    assert missing.value.status_code == 409
    assert (await mail.intake(database)) == {"configured": False}


# ---------------------------------------------------------------- retention and erasure

@pytest.mark.asyncio
async def test_retention_and_erasure(database, dns):
    old = int((datetime.utcnow() - timedelta(days=200)).timestamp())
    await mail.admin_dmarc_upload(upload(report_xml("old", begin=old)), database, ADMIN)
    await mail.admin_dmarc_upload(upload(report_xml("new")), database, ADMIN)
    assert await mail.enforce_retention(database) == 1
    await database.commit()
    assert [r.report_id for r in (await database.scalars(select(DmarcReport))).all()] == ["new"]
    assert await database.scalar(select(func.count(DmarcRecord.id))) == 2
    with pytest.raises(HTTPException) as unconfirmed:
        await mail.admin_dmarc_erase(mail.EraseIn(confirm="да"), database, ADMIN)
    assert unconfirmed.value.status_code == 422
    erased = await mail.admin_dmarc_erase(mail.EraseIn(confirm="УДАЛИТЬ"), database, ADMIN)
    assert erased["erased"] == 1 and erased["reports"] == [] and erased["intake"]["journal"] == []
    assert await database.scalar(select(func.count(DmarcRecord.id))) == 0
    assert await database.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "mail.dmarc.erase")) == 1


def test_erase_needs_security_permission_and_routes_are_private():
    from app.main import app
    from app.security import PERMISSIONS

    names = {"admin_mail_domain": "/api/admin/mail/domain", "admin_mail_check": "/api/admin/mail/domain/check",
             "admin_dmarc_upload": "/api/admin/mail/dmarc/upload", "admin_dmarc_sync": "/api/admin/mail/dmarc/sync",
             "admin_dmarc_erase": "/api/admin/mail/dmarc/erase"}
    for name, path in names.items():
        assert app.url_path_for(name) == path
    assert app.url_path_for("admin_dmarc_report", report_id=3) == "/api/admin/mail/dmarc/reports/3"
    assert any(dep.dependency is mail.private for dep in mail.router.dependencies)
    assert "security.manage" not in PERMISSIONS["operator"] and "ops.diagnostics" in PERMISSIONS["operator"]
