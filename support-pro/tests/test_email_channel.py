"""Email channel: ingestion, replay, threading guard, loops, bounces, SMTP outcomes, erasure."""
import re
import smtplib
from datetime import timedelta
from email.message import EmailMessage

import pytest
from sqlalchemy import func, select

from app import email_channel, worker
from app.models import Attachment, ChannelIdentity, Client, EmailChannelState, EmailLink, Message, Ticket, now


def mail(sender="Анна <anna@example.org>", subject="Не работает VPN", body="Здравствуйте, не подключается.", message_id=None, headers=None, attachments=()):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "support@shop.example"
    message["Subject"] = subject
    message["Message-ID"] = message_id or f"<{abs(hash((sender, subject, body)))}@example.org>"
    for key, value in (headers or {}).items():
        message[key] = value
    message.set_content(body)
    for name, payload in attachments:
        message.add_attachment(payload, maintype="application", subtype="octet-stream", filename=name)
    return message.as_bytes()


class Mailbox:
    def __init__(self):
        self.messages, self.uidvalidity, self.fail = [], 100, None

    def add(self, raw):
        self.messages.append((len(self.messages) + 1, raw))

    def fetch(self, uidvalidity, after):
        if self.fail:
            raise self.fail
        start = after + 1 if uidvalidity == self.uidvalidity else 1
        return self.uidvalidity, [(uid, raw) for uid, raw in self.messages if uid >= start][:25]


class Outbox:
    def __init__(self):
        self.sent, self.error = [], None

    def send(self, message):
        if self.error:
            raise self.error
        self.sent.append(message)


@pytest.fixture
def channel(env, monkeypatch):
    for key, value in {"EMAIL_ADDRESS": "support@shop.example", "EMAIL_IMAP_HOST": "imap.shop.example", "EMAIL_SMTP_HOST": "smtp.shop.example", "EMAIL_FROM_NAME": "Corgi Support"}.items():
        monkeypatch.setenv(key, value)
    box, out = Mailbox(), Outbox()
    monkeypatch.setattr(email_channel, "fetcher", box.fetch)
    monkeypatch.setattr(email_channel, "sender", out.send)
    return {**env, "box": box, "out": out}


async def rows(session, model, *where):
    order = model.telegram_user_id if model is Client else model.id
    async with session() as s:
        return (await s.scalars(select(model).where(*where).order_by(order))).all()


async def poll(env):
    return await email_channel.poll(env["session"])


async def operator_reply(env, tid, text="Проверьте настройки клиента."):
    page = await env["client"].get(f"/ticket/{tid}")
    nonce = re.search(r'data-nonce="([^"]+)"', page.text).group(1)
    response = await env["client"].post(f"/ticket/{tid}/reply", data={"csrf_token": env["csrf"], "text": text, "kind": "reply", "nonce": nonce})
    assert response.status_code == 303, response.text
    mid = await worker.claim_message()
    await worker.deliver(None, mid)
    async with env["session"]() as s:
        return await s.get(Message, mid)


@pytest.mark.parametrize('env', ['sqlite', 'postgres'], indirect=True)
async def test_new_email_opens_ticket_and_replay_never_duplicates(channel):
    channel["box"].add(mail())
    assert await poll(channel) == {"created": 1}
    tickets = await rows(channel["session"], Ticket)
    assert len(tickets) == 1 and tickets[0].channel == "email" and tickets[0].subject == "Не работает VPN"
    identity = (await rows(channel["session"], ChannelIdentity))[0]
    assert identity.address == "anna@example.org" and identity.verified is False and identity.client_id < 0
    assert (await rows(channel["session"], Message))[0].text == "Здравствуйте, не подключается."
    # The mailbox rebuilt its UIDs: the same message is fetched again but stored once.
    channel["box"].uidvalidity = 200
    assert await poll(channel) == {"duplicate": 1}
    assert len(await rows(channel["session"], Message)) == 1
    async with channel["session"]() as s:
        state = await s.get(EmailChannelState, 1)
        assert (state.uidvalidity, state.last_uid, state.received, state.error) == (200, 1, 1, "")


@pytest.mark.parametrize('env', ['sqlite', 'postgres'], indirect=True)
async def test_reply_threads_by_message_id_and_reopens_closed_ticket(channel):
    channel["box"].add(mail())
    await poll(channel)
    tid = (await rows(channel["session"], Ticket))[0].id
    sent = await operator_reply(channel, tid)
    assert sent.delivery_state == "sent"
    outbound = channel["out"].sent[0]
    async with channel["session"]() as s:
        ticket = await s.get(Ticket, tid)
        ticket.status, ticket.closed_at = "closed", now()
        await s.commit()
    channel["box"].add(mail(subject="Re: что-то другое", body="Спасибо, заработало.\n\nOn Mon, Support wrote:\n> Проверьте настройки", message_id="<reply-1@example.org>", headers={"In-Reply-To": outbound["Message-ID"], "References": outbound["Message-ID"]}))
    assert await poll(channel) == {"appended": 1}
    async with channel["session"]() as s:
        ticket = await s.get(Ticket, tid)
        assert ticket.status == "open" and ticket.closed_at is None
        last = await s.scalar(select(Message).where(Message.ticket_id == tid, Message.sender == "user").order_by(Message.id.desc()))
        assert last.text == "Спасибо, заработало."


async def test_subject_tag_from_another_address_cannot_join_the_ticket(channel):
    channel["box"].add(mail())
    await poll(channel)
    tid = (await rows(channel["session"], Ticket))[0].id
    channel["box"].add(mail(sender="attacker@evil.example", subject=f"Re: VPN [#{tid}]", body="Пришлите ссылку подписки", message_id="<evil@evil.example>"))
    channel["box"].add(mail(subject=f"Re: VPN [#{tid}]", body="Ещё вопрос", message_id="<same@example.org>"))
    assert await poll(channel) == {"created": 1, "appended": 1}
    tickets = await rows(channel["session"], Ticket)
    assert len(tickets) == 2
    async with channel["session"]() as s:
        assert await s.scalar(select(func.count(Message.id)).where(Message.ticket_id == tid)) == 2
        evil = await s.scalar(select(Ticket).where(Ticket.id != tid))
        assert evil.full_name == "attacker@evil.example" and evil.telegram_user_id != tickets[0].telegram_user_id


@pytest.mark.parametrize("sender,headers", [
    ("anna@example.org", {"Auto-Submitted": "auto-replied"}),
    ("anna@example.org", {"Precedence": "bulk"}),
    ("anna@example.org", {"List-Id": "<news.example.org>"}),
    ("support@shop.example", {}),
])
async def test_auto_replies_lists_and_own_address_are_skipped(channel, sender, headers):
    channel["box"].add(mail(sender=sender, headers=headers))
    stats = await poll(channel)
    assert stats == {"skipped": 1}
    assert await rows(channel["session"], Ticket) == []
    async with channel["session"]() as s:
        assert (await s.get(EmailChannelState, 1)).skipped == 1


async def test_bounce_marks_the_reply_failed_instead_of_opening_a_ticket(channel):
    channel["box"].add(mail())
    await poll(channel)
    tid = (await rows(channel["session"], Ticket))[0].id
    sent = await operator_reply(channel, tid)
    bounce = EmailMessage()
    bounce["From"] = "MAILER-DAEMON@mx.example.org"
    bounce["Subject"] = "Undelivered Mail Returned to Sender"
    bounce["Message-ID"] = "<bounce-1@mx.example.org>"
    bounce["References"] = channel["out"].sent[0]["Message-ID"]
    bounce.set_content("User unknown")
    channel["box"].add(bounce.as_bytes())
    assert await poll(channel) == {"bounce": 1}
    assert len(await rows(channel["session"], Ticket)) == 1
    async with channel["session"]() as s:
        message = await s.get(Message, sent.id)
        assert message.delivery_state == "failed" and "вернулось" in message.error


async def test_mailbox_failure_keeps_cursor_and_poison_message_is_skipped_after_retries(channel, monkeypatch):
    channel["box"].fail = OSError("connection refused")
    channel["box"].add(mail())
    assert await poll(channel) == {"error": "OSError"}
    async with channel["session"]() as s:
        state = await s.get(EmailChannelState, 1)
        assert state.last_uid == 0 and "недоступен" in state.error
    channel["box"].fail = None
    channel["box"].add(mail(subject="Второе", message_id="<second@example.org>"))
    real_parse = email_channel.parse

    def broken(raw):
        if b"<second@example.org>" in raw:
            raise UnicodeError("broken charset")
        return real_parse(raw)

    monkeypatch.setattr(email_channel, "parse", broken)
    await poll(channel)
    for _ in range(email_channel.MAX_STUCK_ATTEMPTS - 1):
        await poll(channel)
    async with channel["session"]() as s:
        state = await s.get(EmailChannelState, 1)
        assert state.last_uid == 2 and "пропущено" in state.error
    assert len(await rows(channel["session"], Ticket)) == 1


@pytest.mark.parametrize('env', ['sqlite', 'postgres'], indirect=True)
async def test_outbound_reply_headers_threading_and_first_response(channel):
    channel["box"].add(mail(message_id="<first@example.org>"))
    await poll(channel)
    tid = (await rows(channel["session"], Ticket))[0].id
    sent = await operator_reply(channel, tid)
    message = channel["out"].sent[0]
    assert message["To"] == "anna@example.org"
    assert message["Subject"] == f"Re: Не работает VPN [#{tid}]"
    assert message["In-Reply-To"] == "<first@example.org>"
    assert "<first@example.org>" in message["References"]
    assert message["Auto-Submitted"] == "no"
    assert "Проверьте настройки клиента." in message.get_content() and f"#{tid}" in message.get_content()
    links = await rows(channel["session"], EmailLink, EmailLink.direction == "out")
    assert links[0].message_id == message["Message-ID"] and links[0].message_row_id == sent.id
    async with channel["session"]() as s:
        ticket = await s.get(Ticket, tid)
        assert ticket.first_response_at is not None and ticket.waiting_since is None and ticket.status == "open"


@pytest.mark.parametrize("error,state", [
    (email_channel.PermanentError("Почтовый сервер отклонил адрес клиента"), "failed"),
    (email_channel.TemporaryError("SMTP недоступен (OSError)"), "queued"),
    (email_channel.UncertainError("Соединение оборвалось во время отправки; письмо могло уйти"), "uncertain"),
])
async def test_smtp_outcomes(channel, error, state):
    channel["box"].add(mail())
    await poll(channel)
    tid = (await rows(channel["session"], Ticket))[0].id
    channel["out"].error = error
    message = await operator_reply(channel, tid)
    assert message.delivery_state == state and message.error
    if state == "queued":
        from app.sla import utc
        assert utc(message.next_attempt_at) > now()
    # The Message-ID was committed before the attempt, so a later bounce still matches it.
    assert len(await rows(channel["session"], EmailLink, EmailLink.direction == "out")) == 1


async def test_real_smtp_error_classification(monkeypatch):
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.shop.example")
    monkeypatch.setenv("EMAIL_ADDRESS", "support@shop.example")

    class Server:
        def __init__(self, *args, **kwargs):
            pass

        def starttls(self, context=None):
            pass

        def send_message(self, message):
            raise smtplib.SMTPDataError(550, b"mailbox unavailable")

        def quit(self):
            pass

    monkeypatch.setattr(smtplib, "SMTP", Server)
    with pytest.raises(email_channel.PermanentError):
        email_channel._smtp_send(EmailMessage())
    Server.send_message = lambda self, message: (_ for _ in ()).throw(smtplib.SMTPDataError(451, b"try later"))
    with pytest.raises(email_channel.TemporaryError):
        email_channel._smtp_send(EmailMessage())
    Server.send_message = lambda self, message: (_ for _ in ()).throw(smtplib.SMTPServerDisconnected("lost"))
    with pytest.raises(email_channel.UncertainError):
        email_channel._smtp_send(EmailMessage())


async def test_attachments_are_stored_and_oversized_ones_reported(channel, monkeypatch):
    monkeypatch.setenv("EMAIL_MAX_MB", "1")
    channel["box"].add(mail(attachments=[("log.txt", b"connection log"), ("video.bin", b"x" * (2 * 1024 * 1024))]))
    await poll(channel)
    stored = await rows(channel["session"], Attachment)
    assert [(a.filename, a.state) for a in stored] == [("log.txt", "ready")]
    assert "video.bin" in (await rows(channel["session"], Message))[0].text


def test_html_body_and_quote_stripping():
    message = EmailMessage()
    message["From"] = "anna@example.org"
    message["Message-ID"] = "<html@example.org>"
    message.set_content("plain fallback")
    message.add_alternative("<html><head><style>p{}</style></head><body><p>Привет&nbsp;мир</p><script>x()</script></body></html>", subtype="html")
    assert email_channel.parse(message.as_bytes()).text == "plain fallback"
    html_only = EmailMessage()
    html_only["From"] = "anna@example.org"
    html_only.set_content("<p>Привет</p><p>мир</p>", subtype="html")
    parsed = email_channel.parse(html_only.as_bytes())
    assert "Привет" in parsed.text and "<p>" not in parsed.text
    assert parsed.message_id.startswith("<sha256-")
    assert email_channel.strip_quote("Ответ\n\n-----Original Message-----\nстарое") == "Ответ"
    assert email_channel.strip_quote("> только цитата") == "> только цитата"


@pytest.mark.parametrize('env', ['sqlite', 'postgres'], indirect=True)
async def test_erasure_removes_content_files_and_address(channel):
    channel["box"].add(mail(attachments=[("log.txt", b"secret log")]))
    await poll(channel)
    client = (await rows(channel["session"], Client))[0]
    path = (await rows(channel["session"], Attachment))[0].path
    response = await channel["client"].post(f"/client/{client.telegram_user_id}/email/erase", data={"csrf_token": channel["csrf"], "confirm": "erase"})
    assert response.status_code == 303
    async with channel["session"]() as s:
        assert await s.scalar(select(func.count(ChannelIdentity.id))) == 0
        assert await s.scalar(select(func.count(EmailLink.id))) == 0
        message = await s.scalar(select(Message))
        assert message.text == email_channel.ERASED
        ticket = await s.scalar(select(Ticket))
        assert ticket.status == "closed" and ticket.full_name == "Удалённый клиент"
        assert (await s.get(Client, client.telegram_user_id)).username == ""
    from pathlib import Path
    assert not Path(path).exists()
    page = await channel["client"].get(f"/client/{client.telegram_user_id}")
    assert "anna@example.org" not in page.text


async def test_erasure_requires_explicit_confirmation(channel):
    channel["box"].add(mail())
    await poll(channel)
    client = (await rows(channel["session"], Client))[0]
    response = await channel["client"].post(f"/client/{client.telegram_user_id}/email/erase", data={"csrf_token": channel["csrf"]})
    assert response.status_code == 400
    assert len(await rows(channel["session"], ChannelIdentity)) == 1


@pytest.mark.parametrize('env', ['sqlite', 'postgres'], indirect=True)
async def test_history_transfer_moves_tickets_and_identity_to_existing_client(channel):
    async with channel["session"]() as s:
        s.add(Client(telegram_user_id=5551, full_name="Анна (Telegram)", username="anna_tg"))
        await s.commit()
    channel["box"].add(mail())
    await poll(channel)
    source = next(c for c in await rows(channel["session"], Client) if c.telegram_user_id < 0)
    response = await channel["client"].post(f"/client/{source.telegram_user_id}/email/link", data={"csrf_token": channel["csrf"], "target": "5551"})
    assert response.status_code == 303
    async with channel["session"]() as s:
        assert await s.get(Client, source.telegram_user_id) is None
        ticket = await s.scalar(select(Ticket))
        assert ticket.telegram_user_id == 5551 and ticket.full_name == "Анна (Telegram)"
        assert (await s.scalar(select(ChannelIdentity))).client_id == 5551
    # Later mail from the same address lands on the linked client and thread.
    channel["box"].add(mail(subject=f"Re: VPN [#{ticket.id}]", body="Снова я", message_id="<again@example.org>"))
    assert await poll(channel) == {"appended": 1}


async def test_retention_purges_old_closed_email_tickets(channel, monkeypatch):
    channel["box"].add(mail())
    await poll(channel)
    async with channel["session"]() as s:
        ticket = await s.scalar(select(Ticket))
        ticket.status, ticket.closed_at = "closed", now() - timedelta(days=40)
        await s.commit()
    monkeypatch.setenv("EMAIL_RETENTION_DAYS", "30")
    assert await email_channel.purge_expired(channel["session"]) == 1
    assert await email_channel.purge_expired(channel["session"]) == 0
    assert (await rows(channel["session"], Message))[0].text == email_channel.EXPIRED


async def test_email_status_page_and_ticket_notice(channel):
    channel["box"].add(mail(headers={"Authentication-Results": "mx.shop.example; dmarc=fail header.from=example.org"}))
    await poll(channel)
    page = await channel["client"].get("/email")
    assert page.status_code == 200 and "support@shop.example" in page.text and "Email-канал" in page.text
    assert "EMAIL_IMAP_PASSWORD" not in page.text
    tid = (await rows(channel["session"], Ticket))[0].id
    ticket_page = await channel["client"].get(f"/ticket/{tid}")
    assert "Переписка по email" in ticket_page.text and "возможна подделка" in ticket_page.text


async def test_without_smtp_reply_fails_with_clear_reason(channel, monkeypatch):
    channel["box"].add(mail())
    await poll(channel)
    monkeypatch.delenv("EMAIL_SMTP_HOST")
    tid = (await rows(channel["session"], Ticket))[0].id
    message = await operator_reply(channel, tid)
    assert message.delivery_state == "failed" and "EMAIL_SMTP_HOST" in message.error


def test_imap_fetch_reads_readonly_peeks_and_truncates_oversized(monkeypatch):
    import imaplib
    small = mail(message_id="<small@example.org>")
    calls = {"select": None, "fetch": []}

    class FakeIMAP:
        def __init__(self, host, port, ssl_context=None, timeout=None):
            assert host == "imap.shop.example" and port == 993

        def login(self, user, password):
            assert user == "support@shop.example" and password == "secret"

        def select(self, folder, readonly=False):
            calls["select"] = (folder, readonly)
            return "OK", [b"2"]

        def response(self, name):
            return name, [b"777"]

        def uid(self, command, *args):
            if command == "search":
                assert args[1] == "UID 6:*"
                return "OK", [b"5 6 7"]
            uid, what = args
            calls["fetch"].append((uid, what))
            if what == "(RFC822.SIZE)":
                return "OK", [f"{uid} (UID {uid} RFC822.SIZE {99_000_000 if uid == '7' else 900})".encode()]
            if what == "(BODY.PEEK[HEADER])":
                return "OK", [(b"7 (BODY[HEADER] {40}", b"From: anna@example.org\r\nMessage-ID: <big@example.org>\r\n\r\n"), b")"]
            return "OK", [(b"6 (BODY[] {10}", small), b")"]

        def logout(self):
            return "BYE", []

    for key, value in {"EMAIL_IMAP_HOST": "imap.shop.example", "EMAIL_ADDRESS": "support@shop.example", "EMAIL_IMAP_PASSWORD": "secret"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP)
    uidvalidity, messages = email_channel._imap_fetch(777, 5)
    assert uidvalidity == 777 and calls["select"] == ("INBOX", True)
    assert [uid for uid, _ in messages] == [6, 7]
    assert ("6", "(BODY.PEEK[])") in calls["fetch"] and ("7", "(BODY.PEEK[HEADER])") in calls["fetch"]
    big = email_channel.parse(messages[1][1])
    assert "не загружено" in big.text and big.message_id == "<big@example.org>"
