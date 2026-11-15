"""External helpdesk bridge: Zendesk and Freshdesk.

Support Pro mirrors tickets of one external helpdesk (``HELPDESK_PROVIDER``) and
answers them from its own queue:

* **Identity.** The external requester becomes a Support Pro client through a
  ``ChannelIdentity(channel=<provider>, external_id=<user id>)``. A requester whose
  email already belongs to a client (for example from the email channel) joins that
  client instead of creating a duplicate.
* **History import and inbound sync.** The worker reads changed tickets with the
  provider's cursor (Zendesk incremental export, Freshdesk ``updated_since``) starting
  at ``HELPDESK_IMPORT_SINCE``. Every external ticket and comment is recorded in
  ``helpdesk_links`` under a unique key, and a page of tickets commits together with
  the cursor, so a replayed page or a crash never creates duplicates.
* **Outbound sync.** An operator reply is posted as a public comment (Zendesk) or a
  reply (Freshdesk). The created comment id is linked to the message, so the next
  import skips it. A lost confirmation becomes ``uncertain``; when the import later
  finds the same agent text on that ticket, the message is reconciled instead of
  duplicated.
* **Failures.** HTTP 429 pauses the provider for ``Retry-After``; 5xx and network
  errors keep the cursor and retry; 401/403/404/422 fail the message with a reason.
* **Erasure.** Erasing a client clears local text, attachments and identity and keeps a
  tombstone on the external ticket, so later updates of that ticket are not
  re-imported. Data inside the external helpdesk is deleted there by its administrator.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, select, update

from .models import Attachment, ChannelIdentity, Client, HelpdeskLink, HelpdeskState, Message, Ticket, now
from .services import create_ticket, notify
from .sla import utc
from .storage import checked_path, new_path, safe_name, scan_file

log = logging.getLogger(__name__)

PROVIDERS = ("zendesk", "freshdesk")
TEXT_LIMIT = 20000
TICKETS_PER_CYCLE = 50
ERASED = "[удалено по запросу клиента]"
CLOSED_STATUSES = {"zendesk": {"solved", "closed"}, "freshdesk": {4, 5, "4", "5"}}


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def provider() -> str:
    value = env("HELPDESK_PROVIDER").lower()
    return value if value in PROVIDERS else ""


def enabled() -> bool:
    name = provider()
    if name == "zendesk":
        return bool(env("ZENDESK_SUBDOMAIN") and env("ZENDESK_EMAIL") and env("ZENDESK_API_TOKEN"))
    if name == "freshdesk":
        return bool(env("FRESHDESK_DOMAIN") and env("FRESHDESK_API_KEY"))
    return False


def max_bytes() -> int:
    try:
        return max(1, int(env("HELPDESK_MAX_MB", "10"))) * 1024 * 1024
    except ValueError:
        return 10 * 1024 * 1024


def import_since() -> datetime:
    raw = env("HELPDESK_IMPORT_SINCE")
    if raw:
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        except ValueError:
            log.warning("HELPDESK_IMPORT_SINCE is not an ISO date; importing the last 30 days")
    return now() - timedelta(days=30)


def client_factory() -> httpx.AsyncClient:
    """Replaced in tests with a mock transport."""
    return httpx.AsyncClient(timeout=20, follow_redirects=False)


class RateLimited(Exception):
    def __init__(self, seconds: int):
        super().__init__(f"HTTP 429: пауза {seconds} с")
        self.seconds = seconds


class TemporaryError(Exception):
    """Network failure or 5xx: retried with the same cursor or message."""


class PermanentError(Exception):
    """Authentication, permission or validation error: an operator must fix the cause."""


class UncertainError(Exception):
    """The request may have been applied: the response was lost."""


@dataclass
class ExternalUser:
    id: str
    email: str = ""
    name: str = ""
    customer: bool = True


@dataclass
class ExternalComment:
    id: str
    author_id: str
    text: str
    created_at: datetime | None
    from_customer: bool
    private: bool = False
    attachments: list[tuple[str, str, int, str]] = field(default_factory=list)  # name, url, size, content type


@dataclass
class ExternalTicket:
    id: str
    subject: str
    status: str
    requester: ExternalUser | None
    updated_at: datetime | None


def _time(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _clean(text: str | None) -> str:
    value = re.sub(r"\r\n?", "\n", text or "").strip()
    return value[:TEXT_LIMIT]


def _same_text(left: str, right: str) -> bool:
    norm = lambda value: re.sub(r"\s+", " ", (value or "")).strip()
    return norm(left) == norm(right)


async def _request(method: str, url: str, *, auth, **kwargs) -> httpx.Response:
    """One HTTP call with the bridge's error classification. Mutating calls report a
    lost response as ``UncertainError``; reads report it as ``TemporaryError``."""
    mutating = method in {"POST", "PUT"}
    try:
        async with client_factory() as client:
            response = await client.request(method, url, auth=auth, **kwargs)
    except (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ReadError) as exc:
        if mutating:
            raise UncertainError("Ответ внешней системы не получен; результат неизвестен") from exc
        raise TemporaryError("Внешняя система не ответила") from exc
    except httpx.HTTPError as exc:
        raise TemporaryError("Внешняя система недоступна") from exc
    if response.status_code == 429:
        try:
            seconds = int(float(response.headers.get("retry-after", "60")))
        except ValueError:
            seconds = 60
        raise RateLimited(max(5, min(seconds, 3600)))
    if response.status_code >= 500:
        raise TemporaryError(f"Внешняя система вернула HTTP {response.status_code}")
    if response.status_code in (401, 403):
        raise PermanentError(f"HTTP {response.status_code}: проверьте учётную запись и ключ API внешней системы")
    if response.status_code >= 400:
        raise PermanentError(f"HTTP {response.status_code}: внешняя система отклонила запрос")
    return response


async def _download(url: str, *, own_host: str, auth) -> bytes:
    """Fetches an attachment over HTTPS, following up to three redirects by hand.
    Credentials go only to the helpdesk's own host, never to the storage host it
    redirects to; a redirect answer is never stored as file content."""
    from urllib.parse import urljoin, urlsplit

    for _ in range(4):
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            raise PermanentError("Адрес вложения не HTTPS")
        response = await _request("GET", url, auth=auth if parts.hostname == own_host else None)
        if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
            url = urljoin(url, response.headers["location"])
            continue
        if 300 <= response.status_code < 400:
            raise PermanentError(f"HTTP {response.status_code}: вложение недоступно")
        return response.content
    raise PermanentError("Слишком много перенаправлений при загрузке вложения")


class Zendesk:
    name = "zendesk"

    def __init__(self):
        self.base = f"https://{env('ZENDESK_SUBDOMAIN')}.zendesk.com"
        self.auth = (f"{env('ZENDESK_EMAIL')}/token", env("ZENDESK_API_TOKEN"))

    def ticket_url(self, external_id: str) -> str:
        return f"{self.base}/agent/tickets/{external_id}"

    async def changed(self, cursor: str) -> tuple[list[ExternalTicket], str, bool]:
        params = {"cursor": cursor} if cursor else {"start_time": int(import_since().timestamp())}
        data = (await _request("GET", f"{self.base}/api/v2/incremental/tickets/cursor.json", auth=self.auth, params={**params, "include": "users"})).json()
        users = {str(u["id"]): u for u in data.get("users", [])}
        tickets = []
        for row in data.get("tickets", []):
            if row.get("status") == "deleted":
                continue
            user = users.get(str(row.get("requester_id")))
            requester = ExternalUser(str(row.get("requester_id")), (user or {}).get("email") or "", (user or {}).get("name") or "") if row.get("requester_id") else None
            tickets.append(ExternalTicket(str(row["id"]), row.get("subject") or "", str(row.get("status") or ""), requester, _time(row.get("updated_at"))))
        return tickets, data.get("after_cursor") or cursor, bool(data.get("end_of_stream", True))

    async def comments(self, ticket: ExternalTicket) -> tuple[list[ExternalComment], dict[str, ExternalUser]]:
        url, comments, users = f"{self.base}/api/v2/tickets/{ticket.id}/comments.json", [], {}
        params = {"include": "users", "per_page": 100}
        for _ in range(20):
            data = (await _request("GET", url, auth=self.auth, params=params)).json()
            for u in data.get("users", []):
                users[str(u["id"])] = ExternalUser(str(u["id"]), u.get("email") or "", u.get("name") or "", (u.get("role") or "end-user") == "end-user")
            for c in data.get("comments", []):
                author = users.get(str(c.get("author_id")))
                comments.append(ExternalComment(
                    str(c["id"]), str(c.get("author_id")), _clean(c.get("plain_body") or c.get("body")), _time(c.get("created_at")),
                    from_customer=author.customer if author else str(c.get("author_id")) == (ticket.requester.id if ticket.requester else ""),
                    private=not c.get("public", True),
                    attachments=[(a.get("file_name") or "file", a.get("content_url") or "", int(a.get("size") or 0), a.get("content_type") or "application/octet-stream") for a in c.get("attachments", [])]))
            if not data.get("next_page"):
                break
            url, params = data["next_page"], None
        return comments, users

    async def reply(self, external_id: str, text: str, attachment: Attachment | None) -> str | None:
        comment = {"body": text, "public": True}
        if attachment is not None:
            payload = checked_path(attachment.path).read_bytes()
            upload = (await _request("POST", f"{self.base}/api/v2/uploads.json", auth=self.auth, params={"filename": safe_name(attachment.filename)},
                                     content=payload, headers={"Content-Type": attachment.content_type or "application/octet-stream"})).json()
            comment["uploads"] = [upload["upload"]["token"]]
        data = (await _request("PUT", f"{self.base}/api/v2/tickets/{external_id}.json", auth=self.auth, json={"ticket": {"comment": comment}})).json()
        events = (data.get("audit") or {}).get("events") or []
        created = next((e for e in events if e.get("type") == "Comment"), None)
        return str(created["id"]) if created and created.get("id") else None

    async def download(self, url: str) -> bytes:
        return await _download(url, own_host=f"{env('ZENDESK_SUBDOMAIN')}.zendesk.com", auth=self.auth)


class Freshdesk:
    name = "freshdesk"
    PAGE = 100

    def __init__(self):
        domain = env("FRESHDESK_DOMAIN")
        self.base = f"https://{domain if '.' in domain else domain + '.freshdesk.com'}"
        self.auth = (env("FRESHDESK_API_KEY"), "X")

    def ticket_url(self, external_id: str) -> str:
        return f"{self.base}/a/tickets/{external_id}"

    async def changed(self, cursor: str) -> tuple[list[ExternalTicket], str, bool]:
        state = json.loads(cursor) if cursor else {"since": import_since().strftime("%Y-%m-%dT%H:%M:%SZ"), "page": 1}
        rows = (await _request("GET", f"{self.base}/api/v2/tickets", auth=self.auth, params={
            "updated_since": state["since"], "order_by": "updated_at", "order_type": "asc", "include": "requester,description",
            "per_page": self.PAGE, "page": state["page"]})).json()
        tickets = []
        for row in rows:
            r = row.get("requester") or {}
            requester = ExternalUser(str(row.get("requester_id")), r.get("email") or "", r.get("name") or "") if row.get("requester_id") else None
            ticket = ExternalTicket(str(row["id"]), row.get("subject") or "", str(row.get("status") or ""), requester, _time(row.get("updated_at")))
            ticket.description = _clean(row.get("description_text") or row.get("description"))  # type: ignore[attr-defined]
            ticket.created_at = _time(row.get("created_at"))  # type: ignore[attr-defined]
            tickets.append(ticket)
        if len(rows) >= self.PAGE and state["page"] < 300:
            return tickets, json.dumps({"since": state["since"], "page": state["page"] + 1}), False
        latest = max((t.updated_at for t in tickets if t.updated_at), default=None)
        since = latest.strftime("%Y-%m-%dT%H:%M:%SZ") if latest else state["since"]
        return tickets, json.dumps({"since": since, "page": 1}), True

    async def comments(self, ticket: ExternalTicket) -> tuple[list[ExternalComment], dict[str, ExternalUser]]:
        requester = ticket.requester.id if ticket.requester else ""
        comments = [ExternalComment(f"d{ticket.id}", requester, getattr(ticket, "description", ""), getattr(ticket, "created_at", None), True)]
        for page in range(1, 21):
            rows = (await _request("GET", f"{self.base}/api/v2/tickets/{ticket.id}/conversations", auth=self.auth, params={"per_page": self.PAGE, "page": page})).json()
            for c in rows:
                comments.append(ExternalComment(
                    str(c["id"]), str(c.get("user_id")), _clean(c.get("body_text") or c.get("body")), _time(c.get("created_at")),
                    from_customer=bool(c.get("incoming")), private=bool(c.get("private")),
                    attachments=[(a.get("name") or "file", a.get("attachment_url") or "", int(a.get("size") or 0), a.get("content_type") or "application/octet-stream") for a in c.get("attachments", [])]))
            if len(rows) < self.PAGE:
                break
        return comments, {}

    async def reply(self, external_id: str, text: str, attachment: Attachment | None) -> str | None:
        body = "<p>" + html.escape(text).replace("\n", "<br>") + "</p>"
        url = f"{self.base}/api/v2/tickets/{external_id}/reply"
        if attachment is not None:
            payload = checked_path(attachment.path).read_bytes()
            files = {"attachments[]": (safe_name(attachment.filename), payload, attachment.content_type or "application/octet-stream")}
            data = (await _request("POST", url, auth=self.auth, data={"body": body}, files=files)).json()
        else:
            data = (await _request("POST", url, auth=self.auth, json={"body": body})).json()
        return str(data["id"]) if data.get("id") else None

    async def download(self, url: str) -> bytes:
        # Freshdesk attachment URLs are pre-signed; credentials are not sent to the storage host.
        return await _download(url, own_host="", auth=None)


def adapter():
    return {"zendesk": Zendesk, "freshdesk": Freshdesk}[provider()]()


# ---------------------------------------------------------------- local model

async def _state(s, name: str) -> HelpdeskState:
    state = await s.scalar(select(HelpdeskState).where(HelpdeskState.provider == name).with_for_update())
    if state is None:
        state = HelpdeskState(provider=name)
        s.add(state)
        await s.flush()
    return state


async def _link(s, name: str, kind: str, external_id: str) -> HelpdeskLink | None:
    return await s.scalar(select(HelpdeskLink).where(HelpdeskLink.provider == name, HelpdeskLink.kind == kind, HelpdeskLink.external_id == external_id))


async def client_for(s, name: str, user: ExternalUser | None) -> Client:
    """Maps an external requester to a client, joining an existing client with the same email."""
    external_id = user.id if user else "unknown"
    identity = await s.scalar(select(ChannelIdentity).where(ChannelIdentity.channel == name, ChannelIdentity.external_id == external_id))
    if identity:
        client = await s.get(Client, identity.client_id)
        if client:
            return client
        await s.delete(identity)
        await s.flush()
    address = (user.email if user else "").strip().lower()
    client = None
    if address:
        same = await s.scalar(select(ChannelIdentity).where(ChannelIdentity.address == address).order_by(ChannelIdentity.id).limit(1))
        client = await s.get(Client, same.client_id) if same else None
    if client is None:
        uid = -int.from_bytes(hashlib.sha256(f"{name}:{external_id}".encode()).digest()[:7], "big") - 1
        client = await s.get(Client, uid) or Client(telegram_user_id=uid, full_name=(user.name if user else "") or address or "Клиент", username=address)
        s.add(client)
        await s.flush()
    s.add(ChannelIdentity(client_id=client.telegram_user_id, channel=name, external_id=external_id, address=address, verified=False))
    await s.flush()
    return client


async def _store_attachments(s, api, ticket: Ticket, message: Message, comment: ExternalComment) -> None:
    for filename, url, size, content_type in comment.attachments:
        name = safe_name(filename)
        if not url or size > max_bytes():
            s.add(Attachment(ticket_id=ticket.id, message_id=message.id, filename=name, path="", size=size, content_type=content_type,
                             state="failed", error="Файл больше лимита HELPDESK_MAX_MB или без адреса; откройте его во внешней системе"))
            continue
        try:
            payload = await api.download(url)
        except (TemporaryError, PermanentError, RateLimited) as exc:
            s.add(Attachment(ticket_id=ticket.id, message_id=message.id, filename=name, path="", size=size, content_type=content_type, state="failed", error=str(exc)[:500]))
            continue
        if len(payload) > max_bytes():
            s.add(Attachment(ticket_id=ticket.id, message_id=message.id, filename=name, path="", size=len(payload), content_type=content_type,
                             state="failed", error="Файл больше лимита HELPDESK_MAX_MB"))
            continue
        path = new_path(name)
        try:
            path.write_bytes(payload)
            await scan_file(path)
            s.add(Attachment(ticket_id=ticket.id, message_id=message.id, filename=name, path=str(path), size=len(payload), content_type=content_type, state="ready"))
        except ValueError as exc:
            path.unlink(missing_ok=True)
            s.add(Attachment(ticket_id=ticket.id, message_id=message.id, filename=name, path="", size=len(payload), content_type=content_type, state="failed", error=str(exc)[:500]))


async def _reconcile_uncertain(s, ticket: Ticket, comment: ExternalComment) -> Message | None:
    """An agent comment equal to an unconfirmed local reply is that reply, not a new message."""
    candidates = (await s.scalars(select(Message).where(Message.ticket_id == ticket.id, Message.sender.in_(("operator", "system")),
        Message.delivery_state.in_(("uncertain", "sending", "queued"))).order_by(Message.id))).all()
    for message in candidates:
        if _same_text(message.text, comment.text):
            message.delivery_state, message.sent_at, message.error, message.text_sent = "sent", now(), "", True
            return message
    return None


async def import_ticket(s, api, external: ExternalTicket) -> dict:
    """Mirrors one external ticket with its comments. The caller commits with the cursor."""
    name = api.name
    stats = {"tickets": 0, "comments": 0, "skipped": 0}
    link = await _link(s, name, "ticket", external.id)
    if link and link.erased:
        stats["skipped"] += 1
        return stats
    comments, users = await api.comments(external)
    requester = external.requester
    if requester and requester.id in users and not requester.email:
        requester = users[requester.id]
    if link:
        ticket = await s.scalar(select(Ticket).where(Ticket.id == link.ticket_id).with_for_update())
        if ticket is None:
            stats["skipped"] += 1
            return stats
    else:
        client = await client_for(s, name, requester)
        ticket = await create_ticket(s, client, external.subject or f"Обращение {name} #{external.id}", channel=name)
        s.add(HelpdeskLink(provider=name, kind="ticket", external_id=external.id, ticket_id=ticket.id))
        await s.flush()
        stats["tickets"] += 1
    known = set((await s.scalars(select(HelpdeskLink.external_id).where(HelpdeskLink.provider == name, HelpdeskLink.kind == "comment",
                                                                          HelpdeskLink.ticket_id == ticket.id))).all())
    last_customer = None
    for comment in comments:
        if comment.id in known:
            continue
        reconciled = None if comment.from_customer or comment.private else await _reconcile_uncertain(s, ticket, comment)
        if reconciled is not None:
            message = reconciled
        else:
            sender = "note" if comment.private else ("user" if comment.from_customer else "operator")
            message = Message(ticket_id=ticket.id, sender=sender, text=comment.text or "(без текста)",
                              delivery_state="received" if sender == "user" else "sent", source_key=f"{name}:{external.id}:{comment.id}",
                              created_at=comment.created_at or now(), sent_at=None if sender == "user" else (comment.created_at or now()))
            s.add(message)
            await s.flush()
            await _store_attachments(s, api, ticket, message, comment)
            if sender == "user":
                last_customer = message
        s.add(HelpdeskLink(provider=name, kind="comment", external_id=comment.id, ticket_id=ticket.id, message_row_id=message.id))
        known.add(comment.id)
        stats["comments"] += 1
    closed_outside = external.status in CLOSED_STATUSES[name]
    if last_customer is not None:
        ticket.last_customer_message_id = last_customer.id
        ticket.waiting_since = now()
        if ticket.status == "closed" and not closed_outside:
            ticket.status, ticket.closed_at = "open", None
        await notify(s, ticket, f"Новое сообщение {name} в #{ticket.id}", f"{name}-in:{last_customer.id}")
    if closed_outside and ticket.status != "closed":
        ticket.status, ticket.closed_at = "closed", now()
    ticket.updated_at = now()
    return stats


async def poll(Session) -> dict:
    """One sync cycle: pages of changed tickets until the stream ends or the cycle budget is spent."""
    if not enabled():
        return {"enabled": False}
    api = adapter()
    totals = {"tickets": 0, "comments": 0, "skipped": 0, "pages": 0}
    while totals["tickets"] + totals["skipped"] < TICKETS_PER_CYCLE:
        async with Session() as s:
            state = await _state(s, api.name)
            if state.paused_until and utc(state.paused_until) > now():
                await s.commit()
                totals["paused"] = True
                return totals
            page = {"tickets": 0, "comments": 0, "skipped": 0}
            try:
                tickets, cursor, done = await api.changed(state.cursor)
                for external in tickets:
                    result = await import_ticket(s, api, external)
                    for key in page:
                        page[key] += result[key]
            except RateLimited as exc:
                await s.rollback()
                await _record(Session, api.name, error=str(exc), pause=exc.seconds)
                return {**totals, "error": str(exc)}
            except (TemporaryError, PermanentError) as exc:
                await s.rollback()
                await _record(Session, api.name, error=str(exc))
                return {**totals, "error": str(exc)}
            # The page and its cursor commit together: a replay starts from the same page.
            state.cursor, state.last_success, state.error, state.paused_until = cursor, now(), "", None
            state.imported_tickets += page["tickets"]
            state.imported_comments += page["comments"]
            await s.commit()
        for key in page:
            totals[key] += page[key]
        totals["pages"] += 1
        if done or not tickets:
            break
    return totals


async def _record(Session, name: str, error: str, pause: int = 0) -> None:
    async with Session() as s:
        state = await _state(s, name)
        state.error, state.last_error_at = error[:500], now()
        if pause:
            state.paused_until = now() + timedelta(seconds=pause)
        await s.commit()


async def deliver(s, ticket: Ticket, m: Message, attachment: Attachment | None) -> None:
    """Posts one queued operator/system message to the external ticket. The caller commits."""
    name = ticket.channel
    link = await s.scalar(select(HelpdeskLink).where(HelpdeskLink.provider == name, HelpdeskLink.kind == "ticket", HelpdeskLink.ticket_id == ticket.id))
    if provider() != name or not enabled():
        m.delivery_state, m.error = "failed", f"Мост {name} не настроен: проверьте HELPDESK_PROVIDER и ключ API."
        return
    if not link or link.erased:
        m.delivery_state, m.error = "failed", "Внешнее обращение не связано (данные клиента удалены)."
        return
    state = await s.scalar(select(HelpdeskState).where(HelpdeskState.provider == name))
    if state and state.paused_until and utc(state.paused_until) > now():
        m.delivery_state, m.next_attempt_at = "queued", state.paused_until
        m.error = "Внешняя система ограничила частоту запросов; отправка отложена"
        return
    text = m.text if m.sender != "system" else (m.text or f"Обращение #{ticket.id} закрыто.")
    try:
        comment_id = await adapter().reply(link.external_id, text, attachment if attachment and attachment.state == "ready" else None)
    except RateLimited as exc:
        m.delivery_state, m.next_attempt_at, m.error = "queued", now() + timedelta(seconds=exc.seconds), str(exc)
        await _record_in(s, name, str(exc), exc.seconds)
    except TemporaryError as exc:
        m.delivery_state = "queued" if m.attempts < 5 else "failed"
        m.next_attempt_at = now() + timedelta(seconds=min(3600, 30 * 2 ** m.attempts))
        m.error = str(exc) + ("; повтор запланирован" if m.delivery_state == "queued" else "")
    except PermanentError as exc:
        m.delivery_state, m.error = "failed", str(exc)
    except UncertainError as exc:
        m.delivery_state, m.error = "uncertain", str(exc) + ". Следующая синхронизация сверит ответ с внешней системой."
    else:
        m.delivery_state, m.sent_at, m.error, m.text_sent = "sent", now(), "", True
        m.attachment_sent = bool(attachment)
        if comment_id:
            s.add(HelpdeskLink(provider=name, kind="comment", external_id=comment_id, ticket_id=ticket.id, message_row_id=m.id))


async def _record_in(s, name: str, error: str, pause: int) -> None:
    state = await s.scalar(select(HelpdeskState).where(HelpdeskState.provider == name).with_for_update())
    if state is None:
        state = HelpdeskState(provider=name)
        s.add(state)
    state.error, state.last_error_at, state.paused_until = error[:500], now(), now() + timedelta(seconds=pause)


# ---------------------------------------------------------------- erasure and status

async def erase_client(s, client: Client) -> int:
    """Clears local content of the client's helpdesk tickets and keeps tombstones against re-import."""
    from .email_channel import erase_ticket_content

    tickets = (await s.scalars(select(Ticket).where(Ticket.telegram_user_id == client.telegram_user_id, Ticket.channel.in_(PROVIDERS)).with_for_update())).all()
    for ticket in tickets:
        await erase_ticket_content(s, ticket, ERASED)
        ticket.full_name, ticket.username = "Удалённый клиент", ""
        if ticket.status != "closed":
            ticket.status, ticket.closed_at = "closed", now()
        await s.execute(update(Message).where(Message.ticket_id == ticket.id, Message.delivery_state.in_(("queued", "sending"))).values(
            delivery_state="failed", error="Данные клиента удалены"))
        await s.execute(update(HelpdeskLink).where(HelpdeskLink.ticket_id == ticket.id, HelpdeskLink.kind == "ticket").values(erased=True))
        await s.execute(delete(HelpdeskLink).where(HelpdeskLink.ticket_id == ticket.id, HelpdeskLink.kind == "comment"))
    await s.execute(delete(ChannelIdentity).where(ChannelIdentity.client_id == client.telegram_user_id, ChannelIdentity.channel.in_(PROVIDERS)))
    if not await s.scalar(select(ChannelIdentity.id).where(ChannelIdentity.client_id == client.telegram_user_id).limit(1)):
        client.full_name, client.username, client.notes, client.tags = "Удалённый клиент", "", "", ""
    return len(tickets)


async def status(s) -> dict:
    name = provider()
    state = await s.scalar(select(HelpdeskState).where(HelpdeskState.provider == name)) if name else None
    host = ""
    if name == "zendesk" and env("ZENDESK_SUBDOMAIN"):
        host = f"{env('ZENDESK_SUBDOMAIN')}.zendesk.com"
    elif name == "freshdesk" and env("FRESHDESK_DOMAIN"):
        domain = env("FRESHDESK_DOMAIN")
        host = domain if "." in domain else domain + ".freshdesk.com"
    linked = (await s.scalars(select(HelpdeskLink.id).where(HelpdeskLink.provider == name, HelpdeskLink.kind == "ticket"))).all() if name else []
    return {"provider": name, "enabled": enabled(), "host": host, "since": import_since(), "state": state, "tickets": len(linked),
            "paused": bool(state and state.paused_until and utc(state.paused_until) > now())}


def external_url(name: str, external_id: str) -> str:
    if name != provider() or not enabled():
        return ""
    return adapter().ticket_url(external_id)
