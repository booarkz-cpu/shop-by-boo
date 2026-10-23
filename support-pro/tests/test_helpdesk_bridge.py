"""External helpdesk bridge: identity, history import, replay, outbound replies, failures and erasure."""
import json
import re
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app import email_channel, helpdesk_bridge as bridge, worker
from app.sla import utc
from app.models import Attachment, ChannelIdentity, Client, HelpdeskLink, HelpdeskState, Message, Ticket, now


class Zendesk:
    """In-memory Zendesk: incremental cursor export, comments with sideloaded users, replies, uploads."""

    def __init__(self):
        self.users = {7: {"id": 7, "name": "Анна", "email": "Anna@Example.org", "role": "end-user"},
                      9: {"id": 9, "name": "Агент", "email": "agent@shop.example", "role": "agent"}}
        self.tickets = {}
        self.comments = {}
        self.changes = []       # pages of ticket ids returned by the incremental export
        self.fail = None        # (status, headers) for the next request
        self.lose_reply = False
        self.requests = []
        self.next_comment = 1000

    def ticket(self, tid, subject="VPN не подключается", status="open", comments=("Здравствуйте, не работает.",)):
        self.tickets[tid] = {"id": tid, "subject": subject, "status": status, "requester_id": 7, "updated_at": "2026-10-20T10:00:00Z"}
        self.comments[tid] = [self.comment(text, 7) for text in comments]
        self.changes.append([tid])

    def comment(self, text, author, public=True, attachments=()):
        self.next_comment += 1
        return {"id": self.next_comment, "author_id": author, "plain_body": text, "public": public, "created_at": "2026-10-20T10:00:00Z",
                "attachments": [{"file_name": n, "content_url": f"https://shop.zendesk.com/attachments/{n}", "size": len(b), "content_type": "text/plain"} for n, b in attachments]}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            status, headers = self.fail
            self.fail = None
            return httpx.Response(status, headers=headers)
        path = request.url.path
        if path.endswith("/incremental/tickets/cursor.json"):
            cursor = request.url.params.get("cursor")
            index = int(cursor) if cursor else 0
            page = self.changes[index] if index < len(self.changes) else []
            return httpx.Response(200, json={"tickets": [self.tickets[t] for t in page], "users": list(self.users.values()),
                                             "after_cursor": str(index + 1 if page else index), "end_of_stream": index + 1 >= len(self.changes)})
        match = re.search(r"/tickets/(\d+)/comments.json$", path)
        if match:
            return httpx.Response(200, json={"comments": self.comments[int(match.group(1))], "users": list(self.users.values()), "next_page": None})
        if path.endswith("/uploads.json"):
            return httpx.Response(201, json={"upload": {"token": "upload-token"}})
        match = re.search(r"/tickets/(\d+).json$", path)
        if match and request.method == "PUT":
            body = json.loads(request.content)["ticket"]["comment"]
            created = self.comment(body["body"], 9, body.get("public", True))
            self.comments[int(match.group(1))].append(created)
            if self.lose_reply:
                raise httpx.ReadTimeout("lost", request=request)
            return httpx.Response(200, json={"ticket": self.tickets[int(match.group(1))], "audit": {"events": [{"type": "Comment", "id": created["id"]}]}})
        if "/attachments/" in path and request.url.host == "shop.zendesk.com":
            # Zendesk answers with a redirect to its file storage host.
            return httpx.Response(302, headers={"location": f"https://files.zdusercontent.example{path}"})
        if request.url.host == "files.zdusercontent.example":
            return httpx.Response(200, content=b"log line\n")
        return httpx.Response(404)


class Freshdesk:
    def __init__(self):
        self.tickets, self.conversations, self.replies = [], {}, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v2/tickets":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=self.tickets if page == 1 else [])
        match = re.search(r"/tickets/(\d+)/conversations$", path)
        if match:
            return httpx.Response(200, json=self.conversations.get(int(match.group(1)), []))
        match = re.search(r"/tickets/(\d+)/reply$", path)
        if match:
            self.replies.append(json.loads(request.content)["body"])
            return httpx.Response(201, json={"id": 5000 + len(self.replies)})
        return httpx.Response(404)


@pytest.fixture
def zendesk(env, monkeypatch):
    for key, value in {"HELPDESK_PROVIDER": "zendesk", "ZENDESK_SUBDOMAIN": "shop", "ZENDESK_EMAIL": "api@shop.example",
                       "ZENDESK_API_TOKEN": "secret-token", "HELPDESK_IMPORT_SINCE": "2026-10-01T00:00:00Z"}.items():
        monkeypatch.setenv(key, value)
    fake = Zendesk()
    monkeypatch.setattr(bridge, "client_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    return {**env, "zd": fake}


async def rows(session, model, *where):
    order = model.telegram_user_id if model is Client else model.id
    async with session() as s:
        return (await s.scalars(select(model).where(*where).order_by(order))).all()


async def operator_reply(env, tid, text="Переустановите профиль."):
    page = await env["client"].get(f"/ticket/{tid}")
    nonce = re.search(r'data-nonce="([^"]+)"', page.text).group(1)
    response = await env["client"].post(f"/ticket/{tid}/reply", data={"csrf_token": env["csrf"], "text": text, "kind": "reply", "nonce": nonce})
    assert response.status_code == 303, response.text
    mid = await worker.claim_message()
    await worker.deliver(None, mid)
    async with env["session"]() as s:
        return await s.get(Message, mid)


@pytest.mark.parametrize('env', ['sqlite', 'postgres'], indirect=True)
async def test_history_import_maps_identity_and_replay_never_duplicates(zendesk):
    zd = zendesk["zd"]
    zd.ticket(101, comments=("Здравствуйте, не работает.",))
    zd.comments[101].append(zd.comment("Проверьте, пожалуйста, приложение.", 9))
    zd.comments[101].append(zd.comment("Внутренняя заметка агента", 9, public=False))
    zd.ticket(102, subject="Вопрос по оплате", status="solved", comments=("Где чек?",))
    result = await bridge.poll(zendesk["session"])
    assert (result["tickets"], result["comments"]) == (2, 4)
    tickets = await rows(zendesk["session"], Ticket)
    assert [t.channel for t in tickets] == ["zendesk", "zendesk"] and tickets[1].status == "closed"
    assert tickets[0].telegram_user_id == tickets[1].telegram_user_id, "one requester, one client"
    identity = (await rows(zendesk["session"], ChannelIdentity))[0]
    assert (identity.channel, identity.external_id, identity.address) == ("zendesk", "7", "anna@example.org")
    messages = await rows(zendesk["session"], Message, Message.ticket_id == tickets[0].id)
    assert [m.sender for m in messages] == ["user", "operator", "note"] and messages[1].delivery_state == "sent"
    # Replaying the whole export (cursor reset) and a repeated page store nothing new.
    async with zendesk["session"]() as s:
        (await s.scalar(select(HelpdeskState))).cursor = ""
        await s.commit()
    await bridge.poll(zendesk["session"])
    await bridge.poll(zendesk["session"])
    async with zendesk["session"]() as s:
        assert await s.scalar(select(func.count(Message.id))) == 4
        assert await s.scalar(select(func.count(Ticket.id))) == 2
        state = await s.scalar(select(HelpdeskState))
        assert state.imported_tickets == 2 and state.error == ""


async def test_requester_with_known_email_joins_the_existing_client(zendesk, monkeypatch):
    async with zendesk["session"]() as s:
        client = Client(telegram_user_id=-42, full_name="Анна", username="anna@example.org")
        s.add(client)
        s.add(ChannelIdentity(client_id=-42, channel="email", external_id="anna@example.org", address="anna@example.org"))
        await s.commit()
    zendesk["zd"].ticket(201)
    await bridge.poll(zendesk["session"])
    ticket = (await rows(zendesk["session"], Ticket))[0]
    assert ticket.telegram_user_id == -42
    assert {i.channel for i in await rows(zendesk["session"], ChannelIdentity)} == {"email", "zendesk"}


@pytest.mark.parametrize('env', ['sqlite', 'postgres'], indirect=True)
async def test_new_customer_comment_appends_and_reopens(zendesk):
    zd = zendesk["zd"]
    zd.ticket(301, status="solved")
    await bridge.poll(zendesk["session"])
    tid = (await rows(zendesk["session"], Ticket))[0].id
    zd.tickets[301]["status"] = "open"
    zd.comments[301].append(zd.comment("Снова не работает", 7, attachments=[("log.txt", b"log line\n")]))
    zd.changes.append([301])
    await bridge.poll(zendesk["session"])
    async with zendesk["session"]() as s:
        ticket = await s.get(Ticket, tid)
        assert ticket.status == "open" and ticket.waiting_since is not None
        last = await s.scalar(select(Message).where(Message.ticket_id == tid).order_by(Message.id.desc()))
        assert last.text == "Снова не работает" and ticket.last_customer_message_id == last.id
        attachment = await s.scalar(select(Attachment).where(Attachment.message_id == last.id))
        assert attachment.state == "ready" and attachment.filename == "log.txt"
        assert open(attachment.path, "rb").read() == b"log line\n"
    storage = [r for r in zd.requests if r.url.host == "files.zdusercontent.example"]
    assert storage and all("authorization" not in r.headers for r in storage)
    assert all("authorization" in r.headers for r in zd.requests if r.url.host == "shop.zendesk.com")


async def test_operator_reply_is_posted_once_and_not_reimported(zendesk):
    zd = zendesk["zd"]
    zd.ticket(401)
    await bridge.poll(zendesk["session"])
    tid = (await rows(zendesk["session"], Ticket))[0].id
    sent = await operator_reply(zendesk, tid)
    assert sent.delivery_state == "sent"
    put = [r for r in zd.requests if r.method == "PUT"][0]
    assert json.loads(put.content) == {"ticket": {"comment": {"body": "Переустановите профиль.", "public": True}}}
    assert put.headers["authorization"].startswith("Basic ")
    zd.changes.append([401])
    await bridge.poll(zendesk["session"])
    async with zendesk["session"]() as s:
        assert await s.scalar(select(func.count(Message.id)).where(Message.ticket_id == tid)) == 2
        assert await s.scalar(select(func.count(HelpdeskLink.id)).where(HelpdeskLink.kind == "comment")) == 2


async def test_lost_reply_is_uncertain_then_reconciled_by_import(zendesk):
    zd = zendesk["zd"]
    zd.ticket(501)
    await bridge.poll(zendesk["session"])
    tid = (await rows(zendesk["session"], Ticket))[0].id
    zd.lose_reply = True
    sent = await operator_reply(zendesk, tid, "Ответ, ответ на который потерян")
    assert sent.delivery_state == "uncertain"
    zd.lose_reply = False
    zd.changes.append([501])
    await bridge.poll(zendesk["session"])
    async with zendesk["session"]() as s:
        message = await s.get(Message, sent.id)
        assert message.delivery_state == "sent" and message.error == ""
        assert await s.scalar(select(func.count(Message.id)).where(Message.ticket_id == tid)) == 2, "matched, not duplicated"


@pytest.mark.parametrize("status,headers,expected", [
    (503, {}, "queued"), (401, {}, "failed"), (429, {"Retry-After": "120"}, "queued"),
])
async def test_reply_failures_are_classified(zendesk, status, headers, expected):
    zd = zendesk["zd"]
    zd.ticket(601)
    await bridge.poll(zendesk["session"])
    tid = (await rows(zendesk["session"], Ticket))[0].id
    zd.fail = (status, headers)
    sent = await operator_reply(zendesk, tid)
    assert sent.delivery_state == expected and sent.error
    if status == 429:
        assert utc(sent.next_attempt_at) > now() + timedelta(seconds=100)
        async with zendesk["session"]() as s:
            assert utc((await s.scalar(select(HelpdeskState))).paused_until) > now()


async def test_import_failure_keeps_the_cursor_and_rate_limit_pauses(zendesk):
    zd = zendesk["zd"]
    zd.ticket(701)
    zd.fail = (500, {})
    result = await bridge.poll(zendesk["session"])
    assert "HTTP 500" in result["error"]
    async with zendesk["session"]() as s:
        state = await s.scalar(select(HelpdeskState))
        assert state.cursor == "" and "HTTP 500" in state.error
        assert await s.scalar(select(func.count(Ticket.id))) == 0
    zd.fail = (429, {"Retry-After": "300"})
    await bridge.poll(zendesk["session"])
    assert (await bridge.poll(zendesk["session"])).get("paused") is True, "paused source is not called"
    async with zendesk["session"]() as s:
        (await s.scalar(select(HelpdeskState))).paused_until = now() - timedelta(seconds=1)
        await s.commit()
    assert (await bridge.poll(zendesk["session"]))["tickets"] == 1


@pytest.mark.parametrize('env', ['sqlite', 'postgres'], indirect=True)
async def test_erasure_clears_content_and_blocks_reimport(zendesk):
    zd = zendesk["zd"]
    zd.ticket(801, comments=("Мой номер карты в описании",))
    await bridge.poll(zendesk["session"])
    client = (await rows(zendesk["session"], Client))[0]
    page = await zendesk["client"].get(f"/client/{client.telegram_user_id}")
    assert "Удалить данные внешнего helpdesk" in page.text
    response = await zendesk["client"].post(f"/client/{client.telegram_user_id}/helpdesk/erase", data={"csrf_token": zendesk["csrf"], "confirm": "erase"})
    assert response.status_code == 303, response.text
    zd.comments[801].append(zd.comment("Новое сообщение после удаления", 7))
    zd.changes.append([801])
    await bridge.poll(zendesk["session"])
    async with zendesk["session"]() as s:
        texts = (await s.scalars(select(Message.text))).all()
        assert texts == [bridge.ERASED]
        assert await s.scalar(select(func.count(ChannelIdentity.id))) == 0
        link = await s.scalar(select(HelpdeskLink).where(HelpdeskLink.kind == "ticket"))
        assert link.erased is True
        assert await s.scalar(select(func.count(Ticket.id))) == 1


async def test_freshdesk_import_and_reply(env, monkeypatch):
    for key, value in {"HELPDESK_PROVIDER": "freshdesk", "FRESHDESK_DOMAIN": "shop", "FRESHDESK_API_KEY": "fd-key"}.items():
        monkeypatch.setenv(key, value)
    fake = Freshdesk()
    fake.tickets = [{"id": 11, "subject": "Нет доступа", "status": 2, "requester_id": 5, "requester": {"id": 5, "name": "Олег", "email": "oleg@example.org"},
                     "description_text": "Не открывается сайт", "created_at": "2026-10-20T10:00:00Z", "updated_at": "2026-10-20T11:00:00Z"}]
    fake.conversations[11] = [{"id": 31, "body_text": "Уточните устройство", "incoming": False, "private": False, "user_id": 2, "created_at": "2026-10-20T10:30:00Z"},
                              {"id": 32, "body_text": "Android 14", "incoming": True, "private": False, "user_id": 5, "created_at": "2026-10-20T10:40:00Z"}]
    monkeypatch.setattr(bridge, "client_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    result = await bridge.poll(env["session"])
    assert (result["tickets"], result["comments"]) == (1, 3)
    ticket = (await rows(env["session"], Ticket))[0]
    messages = await rows(env["session"], Message)
    assert ticket.channel == "freshdesk" and [m.sender for m in messages] == ["user", "operator", "user"]
    async with env["session"]() as s:
        state = await s.scalar(select(HelpdeskState))
        assert json.loads(state.cursor) == {"since": "2026-10-20T11:00:00Z", "page": 1}
    sent = await operator_reply(env, ticket.id, "Обновите приложение <до 2.15>")
    assert sent.delivery_state == "sent" and fake.replies == ["<p>Обновите приложение &lt;до 2.15&gt;</p>"]
    await bridge.poll(env["session"])
    assert len(await rows(env["session"], Message)) == 4


async def test_status_page_and_unconfigured_bridge(env, monkeypatch):
    monkeypatch.delenv("HELPDESK_PROVIDER", raising=False)
    assert await bridge.poll(env["session"]) == {"enabled": False}
    page = await env["client"].get("/helpdesk")
    assert page.status_code == 200 and "Не настроено" in page.text and "Внешний helpdesk" in page.text
    monkeypatch.setenv("HELPDESK_PROVIDER", "zendesk")
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "shop")
    monkeypatch.setenv("ZENDESK_EMAIL", "api@shop.example")
    monkeypatch.setenv("ZENDESK_API_TOKEN", "secret-token")
    page = await env["client"].get("/helpdesk")
    assert "shop.zendesk.com" in page.text and "secret-token" not in page.text and "Синхронизировать сейчас" in page.text
