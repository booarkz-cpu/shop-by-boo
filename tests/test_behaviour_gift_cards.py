"""BACKLOG A1 (C1): gift cards — the shop's currency only, one redemption — checked by calling the routes (replaces the
source check of test_critical_audit_v2002.py)."""
import asyncio
import hashlib
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from app import main as shop
from app import payment_platform_api as api
from app.models import FinancialLedger, GiftCard, User
from test_subscription_commerce import database  # noqa: F401


def req():
    return Request({"type": "http", "headers": []})


def card(code, currency, value="50"):
    return GiftCard(code_hash=hashlib.sha256(code.encode()).hexdigest(), code_prefix=code[:8], value=Decimal(value),
                    balance=Decimal(value), currency=currency)


@pytest.mark.asyncio
async def test_a_card_in_another_currency_is_refused_and_credits_nothing(database, monkeypatch):
    monkeypatch.setattr(shop.settings, "default_currency", "RUB")
    database.add(card("FOREIGNCARD00000000000000", "EUR"))
    await database.commit()
    with pytest.raises(HTTPException) as err:
        await api.redeem_gift_card(api.GiftCardRedeemIn(code="foreigncard00000000000000"), req(), database)
    assert err.value.detail == "Gift card currency does not match the shop currency"
    await database.rollback()
    assert (await database.get(User, 1)).wallet_balance == 1000
    assert (await database.execute(select(GiftCard))).scalar_one().balance == Decimal("50")


@pytest.mark.asyncio
async def test_a_card_credits_once_and_is_spent(database, monkeypatch):
    monkeypatch.setattr(shop.settings, "default_currency", "RUB")
    database.add(card("SHOPCARD0000000000000000", "RUB"))
    await database.commit()
    out = await api.redeem_gift_card(api.GiftCardRedeemIn(code=" shopcard0000000000000000 "), req(), database)
    assert out["credited"] == "50.00" and Decimal(out["wallet_balance"]) == Decimal("1050")
    with pytest.raises(HTTPException):
        await api.redeem_gift_card(api.GiftCardRedeemIn(code="SHOPCARD0000000000000000"), req(), database)
    ledger = (await database.execute(select(FinancialLedger).where(FinancialLedger.kind == "gift_card"))).scalars().all()
    assert len(ledger) == 1 and ledger[0].amount == Decimal("50")


def test_the_admin_cannot_issue_a_card_in_another_currency(monkeypatch):
    monkeypatch.setattr(shop.settings, "default_currency", "RUB")
    admin = type("A", (), {"email": "owner@example.test"})()
    with pytest.raises(HTTPException) as err:
        asyncio.run(api.create_gift_card(api.GiftCardCreateIn(value=Decimal("10"), currency="EUR"), None, admin))
    assert err.value.status_code == 400


# ---- Spending from the wallet (replaces the source check of test_v301_audit.py) ----
def keyed(key=None):
    headers = [(b"idempotency-key", key.encode())] if key is not None else []
    return Request({"type": "http", "headers": headers})


@pytest.mark.asyncio
async def test_wallet_spend_needs_a_client_key_and_debits_once(database, monkeypatch):
    async def queued(*args, **kwargs):
        raise RuntimeError("VPN temporarily unavailable")
    monkeypatch.setattr(shop, "fulfill", queued)
    for bad in (None, "", "k" * 129):
        with pytest.raises(HTTPException) as err:
            await shop.wallet_spend({"plan_id": 1}, keyed(bad), database)
        assert err.value.detail == "Idempotency-Key is required"
    first = await shop.wallet_spend({"plan_id": 1}, keyed("wallet-a"), database)
    assert (await database.get(User, 1)).wallet_balance == 900
    again = await shop.wallet_spend({"plan_id": 1}, keyed("wallet-a"), database)
    assert again["payment_id"] == first["payment_id"]
    with pytest.raises(HTTPException) as err:  # the same key for another plan
        await shop.wallet_spend({"plan_id": 2}, keyed("wallet-a"), database)
    assert err.value.status_code == 409
    with pytest.raises(HTTPException) as err:  # a new key for the same purchase within 30 seconds
        await shop.wallet_spend({"plan_id": 1}, keyed("wallet-b"), database)
    assert err.value.status_code == 409  # «Предыдущая покупка ещё обрабатывается» or «Повторное списание … заблокировано»
    assert (await database.get(User, 1)).wallet_balance == 900
