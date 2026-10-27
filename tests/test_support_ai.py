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
