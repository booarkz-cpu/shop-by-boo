"""Receipts to the tax service: «Мой налог», АТОЛ Онлайн and ЮKassa, run against fake providers."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import fiscal
from app.models import AppSetting, Base, FiscalReceipt, Payment, Plan, RefundRequest, User
from app.security import decrypt_secret, encrypt_secret

NOW = datetime(2026, 10, 26, 20, 0)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Plan(id=1, name="Год", price=1499, duration_days=365, traffic_limit_gb=0, device_limit=5))
        session.add(User(id=1, referral_code="U1", email="lusi@example.test", email_verified_at=NOW))
        session.add(User(id=2, referral_code="U2"))
        await session.commit()
        yield session
    await engine.dispose()


def pay(id_, provider="yookassa", status="paid", amount="1499", user=1, paid=NOW, purpose="subscription"):
    return Payment(id=id_, user_id=user, plan_id=1, provider=provider, order_id=f"o{id_}", provider_payment_id=f"pp{id_}",
                   amount=Decimal(amount), currency="RUB", status=status, purpose=purpose, duration_days_snapshot=365,
                   paid_at=paid, created_at=paid, idempotency_key=f"k{id_}")


def config(**kw):
    base = dict(mode="npd", enabled_at=NOW - timedelta(hours=1), npd_inn="123456789012", npd_password=encrypt_secret("secret"))
    base.update(kw)
    return fiscal.FiscalConfig(**base)


class Resp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data
        self.content = b"x"

    def json(self):
        return self._data


class FakeHTTP:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def _call(self, method, url, **kw):
        self.calls.append((method, url, kw.get("json"), kw.get("headers")))
        for suffix, answer in self.routes.items():
            if url.endswith(suffix):
                return answer(kw) if callable(answer) else answer
        return Resp(404, {})

    async def post(self, url, **kw):
        return await self._call("POST", url, **kw)

    async def get(self, url, **kw):
        return await self._call("GET", url, **kw)


def test_payload_builders_follow_the_providers():
    p = pay(1)
    c = config(mode="atol", inn="7700000000", taxation="usn_income", vat="vat22", company_email="shop@example.test",
               payment_address="https://shop.example.test")
    name = fiscal.service_name(c, p, Plan(name="Год", duration_days=365))
    assert name == "Подписка VPN «Год» на 365 дн."
    npd = fiscal.npd_income_payload(name, p.amount, NOW, NOW)
    assert npd["totalAmount"] == "1499.00" and npd["services"] == [{"name": name, "amount": "1499.00", "quantity": 1}]
    assert npd["operationTime"] == "2026-10-26T23:00:00+03:00", "Moscow time, like the official cabinet"
    atol = fiscal.atol_sell_payload(c, "corgi-income-1", name, p.amount, "lusi@example.test", NOW)
    item = atol["receipt"]["items"][0]
    assert (item["vat"], item["payment_object"], item["payment_method"]) == ({"type": "vat22"}, 4, "full_payment")
    assert atol["receipt"]["company"] == {"email": "shop@example.test", "sno": "usn_income", "inn": "7700000000", "payment_address": "https://shop.example.test"}
    assert atol["timestamp"] == "26.10.2026 23:00:00"
    yk = fiscal.yookassa_receipt_payload(c, "payment", p, name, "lusi@example.test")
    assert (yk["payment_id"], yk["tax_system_code"], yk["items"][0]["vat_code"]) == ("pp1", 2, 11)
    assert fiscal.service_name(c, pay(2, purpose="topup"), None) == "Пополнение баланса сервиса VPN"
    with pytest.raises(ValueError):
        fiscal.FiscalConfig(mode="npd", npd_inn="123")
    assert "wallet" not in fiscal.FiscalConfig(providers=["wallet", "yookassa", "yookassa"]).providers


@pytest.mark.asyncio
async def test_only_new_payments_of_chosen_providers_get_receipts(db):
    db.add_all([pay(1), pay(2, provider="wallet"), pay(3, paid=NOW - timedelta(days=2)), pay(4, status="pending"),
                pay(5, provider="platega"), pay(6, amount="0")])
    await db.commit()
    assert await fiscal.enqueue_due(db, config(), NOW) == 2
    assert await fiscal.enqueue_due(db, config(), NOW) == 0, "one income receipt per payment"
    rows = (await db.execute(select(FiscalReceipt.payment_id, FiscalReceipt.kind).order_by(FiscalReceipt.payment_id))).all()
    assert rows == [(1, "income"), (5, "income")]
    assert await fiscal.enqueue_due(db, config(mode="off"), NOW) == 0


@pytest.mark.asyncio
async def test_npd_receipt_and_its_cancellation_on_refund(db, monkeypatch):
    db.add(pay(1))
    await db.commit()
    fiscal._NPD_TOKENS.clear()
    http = FakeHTTP({"/auth/lkfl": Resp(200, {"token": "t1"}), "/income": Resp(200, {"approvedReceiptUuid": "200abc"}),
                     "/cancel": Resp(200, {"incomeInfo": {}})})
    monkeypatch.setattr(fiscal, "_client", lambda: http)
    c = config()
    await fiscal.enqueue_due(db, c, NOW)
    assert await fiscal.process_due(db, c, NOW) == {"done": 1}
    income = (await db.execute(select(FiscalReceipt))).scalar_one()
    assert income.receipt_url == "https://lknpd.nalog.ru/api/v1/receipt/123456789012/200abc/print"
    login = http.calls[0]
    assert login[2]["username"] == "123456789012" and login[2]["password"] == "secret"
    sent = next(c for c in http.calls if c[1].endswith("/income"))
    assert sent[3] == {"Authorization": "Bearer t1"} and sent[2]["totalAmount"] == "1499.00"
    (await db.get(Payment, 1)).status = "refunded"
    await db.commit()
    assert await fiscal.enqueue_due(db, c, NOW) == 1
    await fiscal.process_due(db, c, NOW)
    cancel = next(c for c in http.calls if c[1].endswith("/cancel"))
    assert cancel[2]["receiptUuid"] == "200abc" and cancel[2]["comment"] == "Возврат средств"
    assert sum(1 for c in http.calls if c[1].endswith("/auth/lkfl")) == 1, "the token is reused"


@pytest.mark.asyncio
async def test_failures_retry_with_backoff_and_wrong_password_stops(db, monkeypatch):
    db.add(pay(1))
    await db.commit()
    fiscal._NPD_TOKENS.clear()
    monkeypatch.setattr(fiscal, "_client", lambda: FakeHTTP({"/auth/lkfl": Resp(503, {})}))
    c = config()
    await fiscal.enqueue_due(db, c, NOW)
    await fiscal.process_due(db, c, NOW)
    row = (await db.execute(select(FiscalReceipt))).scalar_one()
    assert (row.status, row.attempts, row.next_attempt_at) == ("retry", 1, NOW + timedelta(minutes=2))
    assert await fiscal.process_due(db, c, NOW + timedelta(minutes=1)) == {}, "not before the backoff"
    monkeypatch.setattr(fiscal, "_client", lambda: FakeHTTP({"/auth/lkfl": Resp(401, {})}))
    await fiscal.process_due(db, c, NOW + timedelta(minutes=3))
    assert (row.status, row.next_attempt_at) == ("failed", None)
    assert "пароль" in row.last_error


@pytest.mark.asyncio
async def test_atol_waits_for_the_report_then_stores_fiscal_data(db, monkeypatch):
    db.add(pay(1))
    await db.commit()
    reports = iter([Resp(200, {"uuid": "u-1", "status": "wait"}),
                    Resp(200, {"uuid": "u-1", "status": "done", "payload": {"fiscal_receipt_number": 7, "ofd_receipt_url": "https://ofd.example/r/7"}})])
    http = FakeHTTP({"/getToken": Resp(200, {"token": "a"}), "/grp/sell": Resp(200, {"uuid": "u-1", "status": "wait"}),
                     "/grp/report/u-1": lambda kw: next(reports)})
    monkeypatch.setattr(fiscal, "_client", lambda: http)
    c = config(mode="atol", inn="7700000000", company_email="shop@example.test", payment_address="https://shop.example.test",
               atol_login="l", atol_password=encrypt_secret("p"), atol_group="grp")
    await fiscal.enqueue_due(db, c, NOW)
    await fiscal.process_due(db, c, NOW)
    row = (await db.execute(select(FiscalReceipt))).scalar_one()
    assert (row.status, row.external_id) == ("sent", "u-1")
    sell = next(x for x in http.calls if x[1].endswith("/grp/sell"))
    assert sell[2]["receipt"]["client"] == {"email": "lusi@example.test"} and sell[3] == {"Token": "a"}
    await fiscal.process_due(db, c, NOW + timedelta(minutes=2))
    await fiscal.process_due(db, c, NOW + timedelta(minutes=4))
    assert (row.status, row.receipt_url, row.fiscal_data) == ("done", "https://ofd.example/r/7", {"fiscal_receipt_number": 7})
    assert sum(1 for x in http.calls if x[1].endswith("/grp/sell")) == 1, "polling never sells twice"


@pytest.mark.asyncio
async def test_admin_settings_keep_secrets_encrypted_and_hidden(db, monkeypatch):
    async def audit(*a, **k):
        return None
    from app import main as shop
    monkeypatch.setattr(shop, "audit", audit)
    admin = type("A", (), {"email": "owner@example.test"})()
    payload = fiscal.FiscalIn(mode="npd", npd_inn="123456789012", npd_password="pw-1")
    saved = await fiscal.admin_fiscal_save(payload, db, admin)
    assert saved["config"]["npd_password"] == "" and saved["config"]["npd_password_set"] is True
    stored = fiscal.FiscalConfig.model_validate_json((await db.get(AppSetting, fiscal.SETTING_KEY)).value)
    assert stored.npd_password != "pw-1" and decrypt_secret(stored.npd_password) == "pw-1"
    first_on = stored.enabled_at
    await fiscal.admin_fiscal_save(fiscal.FiscalIn(mode="npd", npd_inn="123456789012"), db, admin)
    again = await fiscal.load_config(db)
    assert decrypt_secret(again.npd_password) == "pw-1", "an empty field keeps the password"
    assert again.enabled_at == first_on, "saving again does not move the start"
    await fiscal.admin_fiscal_save(fiscal.FiscalIn(mode="npd", npd_inn="123456789012", clear_secrets=["npd_password"]), db, admin)
    assert (await fiscal.load_config(db)).npd_password == ""
    with pytest.raises(HTTPException):
        await fiscal.admin_fiscal_save(fiscal.FiscalIn(mode="atol"), db, admin)
    off = await fiscal.admin_fiscal_save(fiscal.FiscalIn(mode="off"), db, admin)
    assert off["config"]["enabled_at"] is None
