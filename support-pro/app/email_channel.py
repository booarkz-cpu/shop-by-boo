"""Email support channel: IMAP ingestion, threading, SMTP replies, retention and erasure.

Guarantees:

* Exactly-once ingestion. Each message is stored with ``source_key = email:<sha256(Message-ID)>``
  and the IMAP cursor advances in the same commit, so a crash or a replayed message never
  creates a duplicate. A changed UIDVALIDITY rescans the folder; the Message-ID still dedupes.
* Threading is bound to the sender. A reply joins a ticket only through our own Message-ID in
  ``In-Reply-To``/``References`` or a ``[#id]`` subject tag, and only when the sender is the
  ticket's email identity. A forged subject from another address opens a separate ticket.
* Mail loops are refused: auto-replies, lists, bulk mail and our own address are skipped;
  delivery-status bounces mark the original reply as failed instead of opening tickets.
* The raw message is never stored. Text and attachments live in the ticket; the
  "Authentication-Results" verdict of the receiving server is kept to show spoofing risk.
* Outbound Message-IDs are committed before the SMTP call, so a lost confirmation becomes
  ``uncertain`` (like Telegram) and a bounce can still be matched.
"""
from __future__ import annotations

import asyncio
import email
import email.policy
import hashlib
import html
import imaplib
import logging
import os
import re
import secrets
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from html.parser import HTMLParser

from sqlalchemy import delete, select, update

from .models import Attachment, ChannelIdentity, Client, EmailChannelState, EmailLink, Message, Ticket, now
from .services import create_ticket, notify
from .storage import checked_path, new_path, safe_name, scan_file

log = logging.getLogger(__name__)

CHANNEL = "email"
TEXT_LIMIT = 20000
BATCH = 25
MAX_STUCK_ATTEMPTS = 3
ADDRESS_RE = re.compile(r"^[^@\s<>\"]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,63}$")
TAG_RE = re.compile(r"\[#(\d{1,12})\]")
QUOTE_RE = re.compile(r"^(>|-{2,}\s*Original Message\s*-{2,}|-{2,}\s*Исходное сообщение\s*-{2,}|On .{3,200} wrote:|.{3,200} (пишет|написал|написала):)\s*$", re.I)
ERASED = "[удалено по запросу клиента]"
EXPIRED = "[удалено по сроку хранения]"


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def enabled() -> bool:
    return bool(env("EMAIL_IMAP_HOST") and env("EMAIL_ADDRESS"))


def sending_enabled() -> bool:
    return bool(env("EMAIL_SMTP_HOST") and env("EMAIL_ADDRESS"))


def own_address() -> str:
    return normalize_address(env("EMAIL_ADDRESS")) or ""


def max_bytes() -> int:
    return int(env("EMAIL_MAX_MB", "10") or "10") * 1024 * 1024


def retention_days() -> int:
    return max(0, int(env("EMAIL_RETENTION_DAYS", "0") or "0"))


def normalize_address(value: str | None) -> str | None:
    name, address = parseaddr(value or "")
    address = address.strip().lower()
    return address if ADDRESS_RE.fullmatch(address) else None


def message_hash(message_id: str) -> str:
    return hashlib.sha256(message_id.strip().lower().encode()).hexdigest()


def _ids(value: str | None) -> list[str]:
    return re.findall(r"<[^<>\s]{1,250}>", value or "")


# ---------------------------------------------------------------- parsing

class _TextFromHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(value: str) -> str:
    parser = _TextFromHTML()
    parser.feed(value)
    return html.unescape("".join(parser.parts))


def strip_quote(text: str) -> str:
    """Drops the quoted previous conversation that mail clients append to replies."""
    lines = text.replace("\r\n", "\n").split("\n")
    for index, line in enumerate(lines):
        if index and QUOTE_RE.match(line.strip()):
            kept = "\n".join(lines[:index]).rstrip()
            if kept:
                return kept
    return text.strip()


@dataclass
class Inbound:
    message_id: str
    sender: str | None
    sender_name: str
    subject: str
    text: str
    references: list[str] = field(default_factory=list)
    attachments: list[tuple[str, str, bytes]] = field(default_factory=list)
    oversized: list[str] = field(default_factory=list)
    skip_reason: str = ""
    bounce: bool = False
    auth: str = "none"


def _auth_verdict(message) -> str:
    # Only the topmost header was added by our receiving server; deeper ones can be forged.
    header = str(message.get("Authentication-Results") or "").lower()
    if not header:
        return "none"
    if re.search(r"\bdmarc=pass\b", header):
        return "pass"
    if re.search(r"\bdmarc=(fail|reject|quarantine)\b", header):
        return "fail"
    if re.search(r"\b(dkim|spf)=pass\b", header):
        return "partial"
    return "none"


def parse(raw: bytes) -> Inbound:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    message_id = (_ids(str(message.get("Message-ID") or "")) or [f"<sha256-{hashlib.sha256(raw).hexdigest()}@missing-message-id>"])[0]
    name, _ = parseaddr(str(message.get("From") or ""))
    sender = normalize_address(str(message.get("From") or ""))
    subject = " ".join(str(message.get("Subject") or "").split())[:255]
    references = _ids(str(message.get("In-Reply-To") or "")) + _ids(str(message.get("References") or ""))
    inbound = Inbound(message_id=message_id, sender=sender, sender_name=" ".join(name.split())[:120], subject=subject, text="", references=references[-20:], auth=_auth_verdict(message))

    auto = str(message.get("Auto-Submitted") or "no").strip().lower()
    precedence = str(message.get("Precedence") or "").strip().lower()
    content_type = message.get_content_type()
    if content_type == "multipart/report" and "delivery-status" in str(message.get("Content-Type") or "").lower():
        inbound.bounce = True
    elif sender and sender.split("@")[0] in ("mailer-daemon", "postmaster"):
        inbound.bounce = True
    if auto not in ("", "no") and not inbound.bounce:
        inbound.skip_reason = "auto-submitted"
    elif precedence in ("bulk", "junk", "list") or message.get("List-Id") or message.get("X-Autoreply") or message.get("X-Autorespond"):
        inbound.skip_reason = "bulk"
    elif not sender and not inbound.bounce:
        inbound.skip_reason = "no-sender"
    elif sender and sender == own_address():
        inbound.skip_reason = "loop"

    body = message.get_body(preferencelist=("plain", "html"))
    if body is not None:
        try:
            content = body.get_content()
        except (LookupError, UnicodeError):
            content = body.get_payload(decode=True).decode("utf-8", "replace") if body.get_payload(decode=True) else ""
        text = html_to_text(content) if body.get_content_type() == "text/html" else content
        inbound.text = strip_quote(text)[:TEXT_LIMIT]
    limit = max_bytes()
    total = 0
    for part in message.iter_attachments():
        filename = safe_name(part.get_filename() or "attachment")
        payload = part.get_payload(decode=True) or b""
        if not payload:
            continue
        total += len(payload)
        if len(payload) > limit or total > limit:
            inbound.oversized.append(filename)
            continue
        inbound.attachments.append((filename, part.get_content_type() or "application/octet-stream", payload))
    if not inbound.text and not inbound.attachments:
        inbound.text = "(пустое письмо)"
    return inbound


# ---------------------------------------------------------------- ingestion

async def _client_for(s, address: str, name: str) -> Client:
    identity = await s.scalar(select(ChannelIdentity).where(ChannelIdentity.channel == CHANNEL, ChannelIdentity.external_id == address))
    if identity:
        client = await s.get(Client, identity.client_id)
        if client:
            return client
        await s.delete(identity)
        await s.flush()
    uid = -secrets.randbelow(2**62) - 1
    client = Client(telegram_user_id=uid, full_name=name or address, username=address)
    s.add(client)
    s.add(ChannelIdentity(client_id=uid, channel=CHANNEL, external_id=address, address=address, verified=False))
    await s.flush()
    return client


async def _thread(s, inbound: Inbound, client: Client) -> Ticket | None:
    hashes = [message_hash(value) for value in inbound.references]
    if hashes:
        link = await s.scalar(select(EmailLink).where(EmailLink.message_id_hash.in_(hashes)).order_by(EmailLink.id.desc()).limit(1))
        if link:
            ticket = await s.scalar(select(Ticket).where(Ticket.id == link.ticket_id).with_for_update())
            if ticket and ticket.telegram_user_id == client.telegram_user_id:
                return ticket
    tag = TAG_RE.search(inbound.subject)
    if tag:
        ticket = await s.scalar(select(Ticket).where(Ticket.id == int(tag.group(1))).with_for_update())
        if ticket and ticket.channel == CHANNEL and ticket.telegram_user_id == client.telegram_user_id:
            return ticket
    return None


async def _bounce(s, inbound: Inbound) -> str:
    hashes = [message_hash(value) for value in inbound.references]
    link = await s.scalar(select(EmailLink).where(EmailLink.message_id_hash.in_(hashes), EmailLink.direction == "out").limit(1)) if hashes else None
    if not link or not link.message_row_id:
        return "bounce-unmatched"
    original = await s.get(Message, link.message_row_id)
    ticket = await s.get(Ticket, link.ticket_id)
    if original and original.delivery_state != "failed":
        original.delivery_state = "failed"
        original.error = "Письмо вернулось: почтовый сервер получателя отказал в доставке. Проверьте адрес клиента."
        await notify(s, ticket, f"Письмо в обращении #{ticket.id} не доставлено", f"email-bounce:{original.id}")
    return "bounce"


async def ingest(s, inbound: Inbound) -> str:
    """Stores one parsed email. The caller commits (together with the IMAP cursor)."""
    source_key = "email:" + message_hash(inbound.message_id)
    if await s.scalar(select(Message.id).where(Message.source_key == source_key)) or await s.scalar(
        select(EmailLink.id).where(EmailLink.message_id_hash == message_hash(inbound.message_id))
    ):
        return "duplicate"
    if inbound.bounce:
        return await _bounce(s, inbound)
    if inbound.skip_reason:
        return "skipped:" + inbound.skip_reason
    client = await _client_for(s, inbound.sender, inbound.sender_name)
    ticket = await _thread(s, inbound, client)
    if ticket is None:
        subject = TAG_RE.sub("", re.sub(r"^\s*((re|fwd?|ответ|отв)\s*:\s*)+", "", inbound.subject, flags=re.I)).strip() or "Письмо без темы"
        ticket = await create_ticket(s, client, subject, channel=CHANNEL)
        created = True
    else:
        created = False
    text = inbound.text
    if inbound.oversized:
        text += "\n\n[Не приняты вложения больше лимита: " + ", ".join(inbound.oversized) + "]"
    message = Message(ticket_id=ticket.id, sender="user", text=text, delivery_state="received", source_key=source_key)
    s.add(message)
    await s.flush()
    for filename, content_type, payload in inbound.attachments:
        path = new_path(filename)
        try:
            path.write_bytes(payload)
            await scan_file(path)
            s.add(Attachment(ticket_id=ticket.id, message_id=message.id, filename=filename, path=str(path), size=len(payload), content_type=content_type, state="ready"))
        except ValueError as exc:
            path.unlink(missing_ok=True)
            s.add(Attachment(ticket_id=ticket.id, message_id=message.id, filename=filename, path="", size=len(payload), content_type=content_type, state="failed", error=str(exc)[:500]))
    s.add(EmailLink(message_id_hash=message_hash(inbound.message_id), message_id=inbound.message_id[:255], direction="in", ticket_id=ticket.id, message_row_id=message.id, auth=inbound.auth))
    ticket.status = "open" if not created else ticket.status
    ticket.closed_at = None
    ticket.updated_at = now()
    ticket.waiting_since = now()
    ticket.last_customer_message_id = message.id
    await notify(s, ticket, f"{'Новое письмо' if created else 'Ответ по email'} в #{ticket.id}", f"email-in:{message.id}")
    return "created" if created else "appended"


# ---------------------------------------------------------------- IMAP

def _imap_fetch(uidvalidity: int, after_uid: int) -> tuple[int, list[tuple[int, bytes]]]:
    host, port = env("EMAIL_IMAP_HOST"), int(env("EMAIL_IMAP_PORT", "993") or "993")
    context = ssl.create_default_context()
    client = imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=30) if env("EMAIL_IMAP_SECURITY", "ssl") != "starttls" else imaplib.IMAP4(host, port, timeout=30)
    try:
        if env("EMAIL_IMAP_SECURITY", "ssl") == "starttls":
            client.starttls(ssl_context=context)
        client.login(env("EMAIL_IMAP_USER") or env("EMAIL_ADDRESS"), env("EMAIL_IMAP_PASSWORD"))
        status, _ = client.select(env("EMAIL_IMAP_FOLDER", "INBOX") or "INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("IMAP folder is not available")
        current = int(re.search(rb"\d+", client.response("UIDVALIDITY")[1][0] or b"0").group())
        start = after_uid + 1 if current == uidvalidity else 1
        status, data = client.uid("search", None, f"UID {start}:*")
        if status != "OK":
            raise RuntimeError("IMAP search failed")
        uids = sorted(int(x) for x in (data[0] or b"").split() if int(x) >= start)[:BATCH]
        messages = []
        for uid in uids:
            status, parts = client.uid("fetch", str(uid), "(BODY.PEEK[])")
            raw = next((part[1] for part in parts if isinstance(part, tuple)), None)
            if status == "OK" and raw is not None:
                messages.append((uid, bytes(raw)))
        return current, messages
    finally:
        try:
            client.logout()
        except Exception:
            pass


fetcher = _imap_fetch  # tests replace this with an in-memory mailbox


async def poll(Session) -> dict:
    """One IMAP cycle. Returns counters; failures are recorded in EmailChannelState."""
    async with Session() as s:
        state = await s.get(EmailChannelState, 1)
        if state is None:
            state = EmailChannelState(id=1)
            s.add(state)
            await s.commit()
        uidvalidity, after = state.uidvalidity, state.last_uid
    try:
        current, messages = await asyncio.to_thread(fetcher, uidvalidity, after)
    except Exception as exc:
        async with Session() as s:
            state = await s.get(EmailChannelState, 1)
            state.error = f"Почтовый ящик недоступен ({type(exc).__name__}); курсор не сдвинут, следующий цикл повторит чтение."
            state.last_error_at = now()
            await s.commit()
        log.warning("Email IMAP cycle failed: %s", type(exc).__name__)
        return {"error": type(exc).__name__}
    stats: dict[str, int] = {}
    if current != uidvalidity:
        async with Session() as s:
            state = await s.get(EmailChannelState, 1)
            state.uidvalidity, state.last_uid, state.stuck_uid, state.stuck_attempts = current, 0, 0, 0
            await s.commit()
    for uid, raw in messages:
        try:
            async with Session() as s:
                state = await s.scalar(select(EmailChannelState).where(EmailChannelState.id == 1).with_for_update())
                if uid <= state.last_uid:
                    continue
                outcome = await ingest(s, parse(raw))
                state.last_uid = uid
                state.stuck_uid, state.stuck_attempts, state.error = 0, 0, ""
                state.last_success = now()
                if outcome in ("created", "appended"):
                    state.received += 1
                else:
                    state.skipped += 1
                await s.commit()
            stats[outcome.split(":")[0]] = stats.get(outcome.split(":")[0], 0) + 1
        except Exception as exc:
            log.warning("Email message UID %s could not be stored: %s", uid, type(exc).__name__)
            async with Session() as s:
                state = await s.get(EmailChannelState, 1)
                attempts = state.stuck_attempts + 1 if state.stuck_uid == uid else 1
                state.stuck_uid, state.stuck_attempts, state.last_error_at = uid, attempts, now()
                if attempts >= MAX_STUCK_ATTEMPTS:
                    # A message that always fails must not block the mailbox forever.
                    state.last_uid = uid
                    state.skipped += 1
                    state.error = f"Письмо UID {uid} пропущено после {attempts} неудачных попыток ({type(exc).__name__}); оно осталось в ящике."
                else:
                    state.error = f"Письмо UID {uid} не обработано ({type(exc).__name__}); повтор в следующем цикле."
                await s.commit()
            stats["error"] = stats.get("error", 0) + 1
            break
    else:
        async with Session() as s:
            state = await s.get(EmailChannelState, 1)
            state.last_success = now()
            if not messages:
                state.error = ""
            await s.commit()
    return stats


# ---------------------------------------------------------------- SMTP

class PermanentError(Exception):
    pass


class TemporaryError(Exception):
    pass


class UncertainError(Exception):
    pass


def _smtp_send(message: EmailMessage) -> None:
    host, port = env("EMAIL_SMTP_HOST"), int(env("EMAIL_SMTP_PORT", "587") or "587")
    security = env("EMAIL_SMTP_SECURITY", "starttls")
    context = ssl.create_default_context()
    try:
        client = smtplib.SMTP_SSL(host, port, context=context, timeout=30) if security == "ssl" else smtplib.SMTP(host, port, timeout=30)
    except (OSError, smtplib.SMTPException) as exc:
        raise TemporaryError(f"SMTP недоступен ({type(exc).__name__})") from exc
    try:
        try:
            if security == "starttls":
                client.starttls(context=context)
            if env("EMAIL_SMTP_USER") or env("EMAIL_SMTP_PASSWORD"):
                client.login(env("EMAIL_SMTP_USER") or env("EMAIL_ADDRESS"), env("EMAIL_SMTP_PASSWORD"))
        except smtplib.SMTPAuthenticationError as exc:
            raise TemporaryError("SMTP отклонил вход: проверьте EMAIL_SMTP_USER и EMAIL_SMTP_PASSWORD") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise TemporaryError(f"SMTP недоступен ({type(exc).__name__})") from exc
        try:
            refused = client.send_message(message)
        except smtplib.SMTPRecipientsRefused as exc:
            raise PermanentError("Почтовый сервер отклонил адрес клиента") from exc
        except smtplib.SMTPResponseException as exc:
            if exc.smtp_code >= 500:
                raise PermanentError(f"Почтовый сервер отказал: {exc.smtp_code}") from exc
            raise TemporaryError(f"Почтовый сервер временно отказал: {exc.smtp_code}") from exc
        except (OSError, smtplib.SMTPServerDisconnected) as exc:
            raise UncertainError("Соединение оборвалось во время отправки; письмо могло уйти") from exc
        if refused:
            raise PermanentError("Почтовый сервер отклонил адрес клиента")
    finally:
        try:
            client.quit()
        except Exception:
            pass


sender = _smtp_send  # tests replace this with an in-memory transport


async def deliver(s, ticket: Ticket, m: Message, attachment: Attachment | None) -> None:
    """Sends one queued operator/system message of an email ticket. The caller commits."""
    identity = await s.scalar(select(ChannelIdentity).where(ChannelIdentity.client_id == ticket.telegram_user_id, ChannelIdentity.channel == CHANNEL))
    if not sending_enabled():
        m.delivery_state, m.error = "failed", "Отправка email не настроена: задайте EMAIL_SMTP_HOST и EMAIL_ADDRESS."
        return
    if not identity:
        m.delivery_state, m.error = "failed", "У клиента нет email-адреса (данные удалены или канал отвязан)."
        return
    links = (await s.scalars(select(EmailLink).where(EmailLink.ticket_id == ticket.id).order_by(EmailLink.id))).all()
    outbound = next((link for link in links if link.message_row_id == m.id and link.direction == "out"), None)
    if outbound is None:
        domain = own_address().split("@")[1]
        outbound = EmailLink(message_id_hash="", message_id=make_msgid(idstring=f"t{ticket.id}m{m.id}", domain=domain), direction="out", ticket_id=ticket.id, message_row_id=m.id)
        outbound.message_id_hash = message_hash(outbound.message_id)
        s.add(outbound)
        await s.commit()  # Persist the Message-ID before the network call: bounces and replies can match it.
    rating = m.sender == "system" and (m.source_key or "").startswith("rating:")
    body = (
        f"Обращение #{ticket.id} закрыто. Если вопрос остался, просто ответьте на это письмо — обращение откроется снова."
        if rating
        else m.text
    )
    footer = f"\n\n—\n{env('EMAIL_FROM_NAME', 'Служба поддержки')}. Ответьте на это письмо, чтобы продолжить обращение #{ticket.id}."
    notice = env("EMAIL_PRIVACY_NOTICE")
    message = EmailMessage()
    message["From"] = formataddr((env("EMAIL_FROM_NAME", "Служба поддержки"), own_address()))
    message["To"] = identity.address
    subject = ticket.subject or "Обращение"
    message["Subject"] = (subject if TAG_RE.search(subject) else f"Re: {subject} [#{ticket.id}]")[:300]
    message["Message-ID"] = outbound.message_id
    inbound_ids = [link.message_id for link in links if link.direction == "in"]
    if inbound_ids:
        message["In-Reply-To"] = inbound_ids[-1]
    references = [link.message_id for link in links if link.id != outbound.id][-10:]
    if references:
        message["References"] = " ".join(references)
    message["Auto-Submitted"] = "auto-replied" if rating else "no"
    message.set_content((body or "") + footer + (f"\n\n{notice}" if notice else ""))
    if attachment and attachment.state == "ready":
        path = checked_path(attachment.path)
        maintype, _, subtype = (attachment.content_type or "application/octet-stream").partition("/")
        message.add_attachment(path.read_bytes(), maintype=maintype or "application", subtype=subtype or "octet-stream", filename=attachment.filename)
    try:
        await asyncio.to_thread(sender, message)
    except PermanentError as exc:
        m.delivery_state, m.error = "failed", str(exc)
    except TemporaryError as exc:
        m.delivery_state = "queued" if m.attempts < 5 else "failed"
        m.next_attempt_at = now() + timedelta(seconds=min(3600, 30 * 2 ** m.attempts))
        m.error = str(exc) + ("; повтор запланирован" if m.delivery_state == "queued" else "")
    except UncertainError as exc:
        m.delivery_state, m.error = "uncertain", str(exc) + ". Проверьте почту перед повтором."
    else:
        m.delivery_state, m.sent_at, m.error = "sent", now(), ""
        m.text_sent = True
        m.attachment_sent = bool(attachment)


# ---------------------------------------------------------------- erasure, retention, history transfer

async def erase_ticket_content(s, ticket: Ticket, marker: str) -> int:
    """Removes message text, attachment files and Message-ID links of one email ticket."""
    removed = 0
    for attachment in (await s.scalars(select(Attachment).where(Attachment.ticket_id == ticket.id))).all():
        if attachment.path:
            try:
                checked_path(attachment.path).unlink(missing_ok=True)
            except ValueError:
                pass
        attachment.path, attachment.state, attachment.filename, attachment.error = "", "deleted", "удалено", marker
        removed += 1
    await s.execute(update(Message).where(Message.ticket_id == ticket.id, Message.sender != "note").values(text=marker))
    await s.execute(delete(EmailLink).where(EmailLink.ticket_id == ticket.id))
    ticket.subject = marker[:255]
    return removed


async def erase_client(s, client: Client) -> int:
    """Data-subject erasure for an email client: content, links, identity and contact details."""
    tickets = (await s.scalars(select(Ticket).where(Ticket.telegram_user_id == client.telegram_user_id, Ticket.channel == CHANNEL).with_for_update())).all()
    for ticket in tickets:
        await erase_ticket_content(s, ticket, ERASED)
        ticket.full_name, ticket.username = "Удалённый клиент", ""
        if ticket.status != "closed":
            ticket.status, ticket.closed_at = "closed", now()
        await s.execute(update(Message).where(Message.ticket_id == ticket.id, Message.delivery_state.in_(("queued", "sending"))).values(delivery_state="failed", error="Данные клиента удалены"))
    await s.execute(delete(ChannelIdentity).where(ChannelIdentity.client_id == client.telegram_user_id, ChannelIdentity.channel == CHANNEL))
    client.full_name, client.username, client.notes, client.tags = "Удалённый клиент", "", "", ""
    return len(tickets)


async def purge_expired(Session) -> int:
    """Retention: clears content of email tickets closed longer than EMAIL_RETENTION_DAYS ago."""
    days = retention_days()
    if not days:
        return 0
    cutoff = now() - timedelta(days=days)
    count = 0
    async with Session() as s:
        tickets = (await s.scalars(select(Ticket).where(Ticket.channel == CHANNEL, Ticket.status == "closed", Ticket.closed_at < cutoff, Ticket.subject != EXPIRED).limit(100).with_for_update(skip_locked=True))).all()
        for ticket in tickets:
            await erase_ticket_content(s, ticket, EXPIRED)
            count += 1
        await s.commit()
    return count


async def link_client(s, source: Client, target: Client) -> int:
    """Moves an email client's identity and ticket history onto an existing client."""
    if source.telegram_user_id == target.telegram_user_id:
        raise ValueError("Это тот же клиент")
    identities = (await s.scalars(select(ChannelIdentity).where(ChannelIdentity.client_id == source.telegram_user_id))).all()
    if not identities:
        raise ValueError("У исходного клиента нет email-адреса")
    for identity in identities:
        identity.client_id = target.telegram_user_id
    tickets = (await s.scalars(select(Ticket).where(Ticket.telegram_user_id == source.telegram_user_id).with_for_update())).all()
    for ticket in tickets:
        ticket.telegram_user_id = target.telegram_user_id
        ticket.full_name, ticket.username = target.full_name, target.username
    if source.notes:
        target.notes = (target.notes + "\n" + source.notes).strip()[:10000]
    await s.delete(source)
    return len(tickets)


async def status(s) -> dict:
    state = await s.get(EmailChannelState, 1)
    identities = (await s.scalars(select(ChannelIdentity.id).where(ChannelIdentity.channel == CHANNEL))).all()
    return {
        "inbound": enabled(),
        "outbound": sending_enabled(),
        "address": own_address(),
        "imap_host": env("EMAIL_IMAP_HOST"),
        "smtp_host": env("EMAIL_SMTP_HOST"),
        "retention_days": retention_days(),
        "max_mb": max_bytes() // 1024 // 1024,
        "state": state,
        "clients": len(identities),
    }
