"""Runtime projections and checkout policy, using an isolated SQL database."""
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import sys

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_SECRET", "workspace-test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from starlette.requests import Request

from app import main as shop
from app.customer_workspace_api import purchased_gifts, wallet_history
from app.models import Base, FinancialLedger, GiftCode, GiftRedemption, PaymentProviderHealth, Plan, User
from app.payment_policy import PAYMENT_AGENTS, routing_names


@pytest_asyncio.fixture
async def database(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add_all([User(id=1, username="Owner", referral_code="OWNER"),
                    User(id=2, username="Other", referral_code="OTHER"),
                    Plan(id=1, name="Month", price=100, duration_days=30, device_limit=2)])
        await db.commit()
        async def authenticated(request, session):
            return await session.get(User, 1)
        monkeypatch.setattr(shop, "user_from_token", authenticated)
        yield db
    await engine.dispose()


def request():
    return Request({"type": "http", "headers": []})


@pytest.mark.asyncio
async def test_wallet_history_does_not_expose_other_users_or_gateway_revenue(database):
    database.add_all([
        FinancialLedger(id=1, operation_key="wallet:1", user_id=1, kind="wallet_topup", direction="credit", amount=100, currency="RUB"),
        FinancialLedger(id=2, operation_key="wallet:2", user_id=2, kind="wallet_topup", direction="credit", amount=900, currency="RUB"),
        FinancialLedger(id=3, operation_key="payment:1", user_id=1, kind="payment", direction="credit", amount=100, currency="RUB"),
    ])
    await database.commit()
    result = await wallet_history(request(), database)
    assert [x["id"] for x in result["items"]] == [1]
    assert result["items"][0]["amount"] == "100.00"
    assert "operation_key" not in result["items"][0]


@pytest.mark.asyncio
async def test_gift_history_hides_other_owners_and_used_tokens(database):
    database.add_all([
        GiftCode(id=1, code="GIFT_READY", plan_id=1, purchaser_user_id=1),
        GiftCode(id=2, code="GIFT_SECRET", plan_id=1, purchaser_user_id=2),
        GiftCode(id=3, code="GIFT_USED_SECRET", plan_id=1, purchaser_user_id=1, used_count=1),
    ])
    await database.commit()
    rows = await purchased_gifts(request(), database)
    assert {x["id"] for x in rows} == {1, 3}
    assert next(x for x in rows if x["id"] == 1)["code"] == "GIFT_READY"
    assert next(x for x in rows if x["id"] == 3)["code"] is None
    assert "GIFT_SECRET" not in str(rows) and "GIFT_USED_SECRET" not in str(rows)


@pytest.mark.asyncio
async def test_completed_gift_can_be_retried_case_insensitively_after_expiry(database):
    database.add(GiftCode(id=1, code="GIFT_oldMixedCase", plan_id=1, purchaser_user_id=2,
                          used_count=1, expires_at=datetime.utcnow()-timedelta(days=1)))
    database.add(GiftRedemption(id=1, gift_code_id=1, user_id=1, operation_key="gift:1", status="completed"))
    await database.commit()
    result = await shop.redeem_gift(shop.GiftRedeemIn(code="gift_OLDmixedCASE"), request(), database)
    assert result["ok"] and result["already_redeemed"]
    assert (await database.get(GiftCode, 1)).used_count == 1


class RoutingSession:
    """SQLite exercises SQL selection; PostgreSQL-only bootstrap lock is excluded."""
    def __init__(self, session): self.session = session
    async def execute(self, statement, *args, **kwargs):
        if "pg_advisory_xact_lock" in str(statement): return None
        return await self.session.execute(statement, *args, **kwargs)
    def add(self, value): self.session.add(value)
    async def flush(self): await self.session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize("removed", ["stripe", "paypal", "crypto", "apple_iap", "google_play", "sepa"])
async def test_removed_provider_is_rejected_even_if_health_row_is_enabled(database, monkeypatch, removed):
    database.add(PaymentProviderHealth(provider=removed, enabled=True, priority=1))
    await database.commit()
    monkeypatch.setattr(shop, "payments_sandbox_allowed", lambda: False)
    with pytest.raises(HTTPException) as error:
        await shop._payment_provider_order(RoutingSession(database), removed)
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_catalog_and_routing_respect_health_cooldown_and_credentials(database, monkeypatch):
    monkeypatch.setattr(shop, "payments_sandbox_allowed", lambda: False)
    for k,v in {"yookassa_shop_id":"id","yookassa_secret_key":"key","yookassa_webhook_ip_allowlist":"127.0.0.1", "rollypay_api_key":"key", "rollypay_signing_secret":"secret", "platega_merchant_id":"id", "platega_secret":"secret"}.items():
        monkeypatch.setattr(shop.settings,k,v)
    database.add_all([
        PaymentProviderHealth(provider="stripe", enabled=True, priority=1),
        PaymentProviderHealth(provider="yookassa", enabled=False, priority=2),
        PaymentProviderHealth(provider="rollypay", enabled=True, priority=3, circuit_open_until=datetime.utcnow()+timedelta(hours=1)),
        PaymentProviderHealth(provider="platega", enabled=True, priority=4),
    ])
    await database.commit()
    db = RoutingSession(database)
    assert await shop._payment_provider_order(db, None) == ["platega"]
    catalog = await shop.payment_providers(db)
    assert {x["name"] for x in catalog["providers"]} == set(PAYMENT_AGENTS)
    assert [x["name"] for x in catalog["providers"] if x["enabled"]] == ["platega"]
    monkeypatch.setattr(shop.settings,"platega_secret","")
    assert await shop._payment_provider_order(db,None) == []


def test_sandbox_is_an_explicit_test_mode_not_a_payment_agent():
    assert routing_names(False) == set(PAYMENT_AGENTS)
    assert routing_names(True) == set(PAYMENT_AGENTS) | {"sandbox"}


@pytest.mark.asyncio
async def test_store_purchase_endpoint_cannot_mint_new_payments(database):
    with pytest.raises(HTTPException) as error:
        await shop.verify_mobile_purchase(shop.MobilePurchaseIn(provider="apple_iap", plan_id=1), request(), database)
    assert error.value.status_code == 410

@pytest.mark.asyncio
async def test_withdrawal_retry_does_not_debit_balance_twice(database):
    from app.models import WithdrawalRequest
    from sqlalchemy import select
    owner=await database.get(User,1);owner.referral_balance=Decimal("100.00");await database.commit()
    # Existing durable operation represents a committed request whose HTTP response was lost.
    database.add(WithdrawalRequest(id=1,user_id=1,amount=Decimal("10.00"),destination="account",idempotency_key="retry-key"))
    await database.commit()
    class Session(RoutingSession):
        def __getattr__(self,name): return getattr(self.session,name)
    req=Request({"type":"http","headers":[(b"idempotency-key",b"retry-key")]})
    payload=shop.WithdrawalIn(amount=Decimal("10.00"),destination="account")
    result=await shop.request_withdrawal(payload,req,Session(database))
    assert result["id"]==1 and (await database.get(User,1)).referral_balance==Decimal("100.00")
    with pytest.raises(HTTPException) as error:
        await shop.request_withdrawal(shop.WithdrawalIn(amount=Decimal("20.00"),destination="account"),req,Session(database))
    assert error.value.status_code==409

@pytest.mark.asyncio
async def test_support_reply_notifies_customer_once_and_rejects_empty_reply(database):
    from app.models import SupportTicket,Notification
    from sqlalchemy import select,func
    from types import SimpleNamespace
    database.add(SupportTicket(id=1,user_id=1,subject="VPN",message="Help"));await database.commit()
    admin=SimpleNamespace(email="admin@example.com")
    await shop.admin_ticket_reply(1,shop.AdminTicketReplyIn(reply="Готово"),database,admin)
    await shop.admin_ticket_reply(1,shop.AdminTicketReplyIn(reply="Готово"),database,admin)
    assert await database.scalar(select(func.count()).select_from(Notification))==1
    note=await database.scalar(select(Notification));assert note.user_id==1 and note.body=="Готово"
    with pytest.raises(HTTPException) as error:
        await shop.admin_ticket_reply(1,shop.AdminTicketReplyIn(reply="   "),database,admin)
    assert error.value.status_code==400

@pytest.mark.asyncio
async def test_referral_binding_rejects_cycles_and_uses_case_insensitive_codes(database):
    from app.referrals import bind_referrer
    class Session(RoutingSession):
        def __getattr__(self,name):return getattr(self.session,name)
    db=Session(database);owner=await database.get(User,1);other=await database.get(User,2)
    assert await bind_referrer(db,owner,"other")==2
    await database.commit()
    with pytest.raises(HTTPException) as error:await bind_referrer(db,other,"owner")
    assert error.value.status_code==400 and other.referred_by_id is None


def test_openapi_resolves_all_request_models():
    schema = shop.app.openapi()
    assert "TrialIn" in schema["components"]["schemas"]
    assert "/api/me/wallet/history" in schema["paths"]


def test_miniapp_docker_copy_sources_exist_in_root_context():
    from pathlib import Path
    import shlex
    root = Path(__file__).resolve().parents[1]
    # Docker joins backslash-continued lines into one instruction.
    for line in (root / "miniapp/Dockerfile").read_text().replace("\\\n", " ").splitlines():
        words = shlex.split(line)
        if words and words[0] == "COPY" and not words[1].startswith("--from="):
            for source in words[1:-1]:
                assert list(root.glob(source)), f"Missing Docker context source: {source}"

@pytest.mark.asyncio
async def test_support_conversation_preserves_legacy_reply_and_reopens(database):
    from app.models import SupportTicket, SupportMessage, Notification
    from app.customer_workspace_api import customer_support_messages, customer_support_reply, SupportMessageIn
    from sqlalchemy import select, func
    from types import SimpleNamespace
    ticket=SupportTicket(id=1,user_id=1,subject="VPN",message="Первый вопрос",admin_reply="Старый ответ",status="resolved")
    database.add(ticket);await database.commit()
    req=Request({"type":"http","headers":[(b"idempotency-key",b"customer-retry")]})
    payload=SupportMessageIn(message="Проблема осталась")
    first=await customer_support_reply(1,payload,req,database)
    second=await customer_support_reply(1,payload,req,database)
    assert first["created"] and not second["created"] and first["id"]==second["id"]
    assert ticket.status=="open"
    with pytest.raises(HTTPException) as error:
        await customer_support_reply(1,SupportMessageIn(message="Изменённый текст"),req,database)
    assert error.value.status_code==409
    admin_req=Request({"type":"http","headers":[(b"idempotency-key",b"admin-retry")]})
    admin=SimpleNamespace(email="admin@example.com")
    await shop.admin_ticket_reply(1,shop.AdminTicketReplyIn(reply="Новый ответ"),database,admin,admin_req)
    await shop.admin_ticket_reply(1,shop.AdminTicketReplyIn(reply="Новый ответ"),database,admin,admin_req)
    thread=await customer_support_messages(1,req,0,database)
    assert [m["body"] for m in thread["messages"]]==["Первый вопрос","Старый ответ","Проблема осталась","Новый ответ"]
    assert thread["status"]=="resolved" and thread["next_cursor"] is None
    assert await database.scalar(select(func.count()).select_from(Notification))==1
    assert await database.scalar(select(func.count()).select_from(SupportMessage))==3

@pytest.mark.asyncio
async def test_support_thread_cannot_read_or_write_another_customer_ticket(database):
    from app.models import SupportTicket
    from app.customer_workspace_api import customer_support_messages, customer_support_reply, SupportMessageIn
    database.add(SupportTicket(id=2,user_id=2,subject="Чужое",message="Секрет"));await database.commit()
    req=Request({"type":"http","headers":[]})
    for operation in (customer_support_messages(2,req,0,database),customer_support_reply(2,SupportMessageIn(message="Ответ"),req,database)):
        with pytest.raises(HTTPException) as error:await operation
        assert error.value.status_code==404

@pytest.mark.asyncio
async def test_support_thread_pagination_does_not_skip_or_repeat_messages(database):
    from app.models import SupportTicket,SupportMessage
    from app.support_threads import read_thread
    ticket=SupportTicket(id=1,user_id=1,subject="VPN",message="Начало")
    database.add(ticket);await database.flush()
    database.add_all([SupportMessage(ticket_id=1,role="customer",body=str(i)) for i in range(105)])
    await database.commit()
    first=await read_thread(database,ticket)
    second=await read_thread(database,ticket,first["next_cursor"])
    assert len(first["messages"])==101 and len(second["messages"])==5
    assert first["messages"][0]["id"]==0 and second["next_cursor"] is None
    assert [m["body"] for m in first["messages"][1:]+second["messages"]]==[str(i) for i in range(105)]

@pytest.mark.asyncio
async def test_blank_support_followup_cannot_reopen_or_append(database):
    from app.models import SupportTicket,SupportMessage
    from app.customer_workspace_api import customer_support_reply,SupportMessageIn
    from sqlalchemy import select,func
    ticket=SupportTicket(id=1,user_id=1,subject="VPN",message="Вопрос",status="resolved")
    database.add(ticket);await database.commit()
    with pytest.raises(HTTPException) as error:
        await customer_support_reply(1,SupportMessageIn(message="  "),Request({"type":"http","headers":[]}),database)
    assert error.value.status_code==400 and ticket.status=="resolved"
    assert await database.scalar(select(func.count()).select_from(SupportMessage))==0
