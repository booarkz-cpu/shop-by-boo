"""AI support drafts: from the model when configured, from the FAQ otherwise; never sent by themselves."""
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app import support_ai
from app.models import SupportMessage, SupportTicket
from app_contract import permissions
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="a@b.c")
FAQ = support_ai.FaqIn(items=[
    support_ai.FaqItem(question="Как подключить VPN на iPhone?", answer="Установите Happ из App Store и откройте ссылку подписки из кабинета."),
    support_ai.FaqItem(question="Как вернуть деньги?", answer="Напишите номер заказа, оператор проверит оплату."),
])


async def ticket(db, text="Не получается подключить VPN на iPhone, что делать?"):
    row = SupportTicket(user_id=1, subject="Подключение", message=text)
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
async def test_without_a_model_the_closest_faq_answer_is_drafted(database, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "support_ai_url", "")
    await support_ai.save_support_ai(FAQ, database, ADMIN)
    t = await ticket(database)
    out = await support_ai.support_draft(t.id, database, ADMIN)
    assert out["source"] == "faq" and "Happ" in out["draft"] and out["matched"][0].startswith("Как подключить")
    assert await database.scalar(select(func.count(SupportMessage.id))) == 0, "a draft is never sent"


class Model:
    def __init__(self):
        self.request = None

    async def post(self, url, headers=None, json=None):
        self.request = (url, headers, json)
        body = {"choices": [{"message": {"content": "Здравствуйте! Установите Happ и откройте ссылку подписки."}}]}
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: body})()


@pytest.mark.asyncio
async def test_the_model_gets_the_faq_status_and_conversation_but_no_personal_ids(database, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "support_ai_url", "https://llm.example/v1/chat/completions")
    monkeypatch.setattr(settings, "support_ai_key", "sk-test")
    await support_ai.save_support_ai(FAQ, database, ADMIN)
    t = await ticket(database)
    model = Model()
    out = await support_ai.draft(database, t.id, client=model)
    url, headers, body = model.request
    system = body["messages"][0]["content"]
    assert out["source"] == "llm" and headers["Authorization"] == "Bearer sk-test"
    assert "Happ" in system and "Подписка: статус active" in system and "лимит устройств 2" in system
    assert body["messages"][-1]["content"].startswith("Не получается"), "the customer's words go last"


@pytest.mark.asyncio
async def test_a_model_failure_falls_back_to_the_faq(database, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "support_ai_url", "https://llm.example/v1/chat/completions")
    monkeypatch.setattr(settings, "support_ai_key", "sk-test")
    await support_ai.save_support_ai(FAQ, database, ADMIN)
    t = await ticket(database, "Хочу вернуть деньги за заказ")

    class Down:
        async def post(self, *a, **k):
            raise TimeoutError("model timeout")
    out = await support_ai.draft(database, t.id, client=Down())
    assert out["source"] == "faq" and "номер заказа" in out["draft"]


def test_drafts_need_support_rights():
    assert permissions("POST", "/api/admin/support/tickets/{ticket_id}/draft") == {"support.write"}


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["openai", "anthropic"])
async def test_model_transport_masks_every_text_field_and_response(api):
    """Inspect the final HTTP JSON for both APIs; authentication stays in headers."""
    import httpx
    import json

    from app.log_redact import remember, restore, snapshot

    known = snapshot()
    secret = "registered-model-context-secret"
    try:
        remember(secret)
        system = f"FAQ: {secret}; почта helpdesk@example.test; password=faq-private-value"
        convo = [{"role": "user", "content": "Не подключается VPN vless://uuid@host:443 и user@example.test"}]
        original = [dict(m) for m in convo]
        seen = []

        def handle(request):
            seen.append(request)
            text = "Ответ: result@example.test password=reply-private-value"
            body = {"content": [{"type": "text", "text": text}]} if api == "anthropic" else {
                "choices": [{"message": {"content": text}}]}
            return httpx.Response(200, json=body)

        cfg = {"url": "https://api.anthropic.example/messages" if api == "anthropic" else "https://model.example/chat",
               "key": "transport-auth-value", "model": "test-model"}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            result = await support_ai.call_llm(cfg, system, convo, client)
        body = json.loads(seen[0].content)
        sent = json.dumps(body, ensure_ascii=False)
        for value in (secret, "helpdesk@example.test", "faq-private-value", "user@example.test", "uuid@host:443"):
            assert value not in sent
        assert "Не подключается VPN" in sent and "[email]" in sent
        assert convo == original and secret in system
        header = "x-api-key" if api == "anthropic" else "authorization"
        assert "transport-auth-value" in seen[0].headers[header]
        assert result == "Ответ: [email] password=***"
    finally:
        restore(known)


@pytest.mark.asyncio
async def test_draft_filters_subject_faq_and_stored_messages_without_changing_them(database, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "support_ai_url", "https://llm.example/v1/chat/completions")
    monkeypatch.setattr(settings, "support_ai_key", "sk-test")
    await support_ai.save_support_ai(support_ai.FaqIn(items=[
        support_ai.FaqItem(question="VPN настройка", answer="Почта faq@example.test password=faq-context-secret"),
    ]), database, ADMIN)
    t = await ticket(database, "Начальный текст root@example.test")
    t.subject = "VPN subject@example.test"
    message = SupportMessage(ticket_id=t.id, role="operator", body="VPN message@example.test password=message-context-secret")
    database.add(message)
    await database.commit()
    model = Model()
    out = await support_ai.draft(database, t.id, client=model)
    body = model.request[2]
    text = str(body)
    assert out["source"] == "llm"
    for value in ("faq@example.test", "faq-context-secret", "subject@example.test",
                  "message@example.test", "message-context-secret"):
        assert value not in text
    assert body["messages"][1] == {"role": "user", "content": "VPN [email]"}
    assert "Подписка: статус active" in body["messages"][0]["content"]
    await database.refresh(t)
    await database.refresh(message)
    assert t.subject == "VPN subject@example.test"
    assert t.message == "Начальный текст root@example.test"
    assert message.body == "VPN message@example.test password=message-context-secret"
    assert await database.scalar(select(func.count(SupportMessage.id))) == 1


@pytest.mark.asyncio
async def test_model_error_note_does_not_echo_credentials_or_email(database, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "support_ai_url", "https://llm.example/v1/chat/completions")
    monkeypatch.setattr(settings, "support_ai_key", "sk-test")
    t = await ticket(database)

    class Down:
        async def post(self, *args, **kwargs):
            raise RuntimeError("password=provider-error-secret contact=operator@example.test")

    out = await support_ai.draft(database, t.id, client=Down())
    assert out["source"] == "faq"
    assert "provider-error-secret" not in out["note"] and "operator@example.test" not in out["note"]
    assert "password=***" in out["note"] and "[email]" in out["note"]
