"""v28.48 corporate plans: seats, a device pool, employees with their own access, invoices to the company."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from app import corporate as corp
from app import main as shop
from app.models import CorporateInvoice, CorporateMember, Subscription, User
from test_subscription_commerce import database  # noqa: F401


class Panel:
    def __init__(self):
        self.calls = []

    async def create_user(self, name, expire, traffic, **kw):
        self.calls.append(("create", name, expire, kw.get("device_limit")))
        return {"id": f"rw-{name}", "subscriptionUrl": f"https://sub.test/{name}"}

    async def patch_user(self, uuid, body):
        self.calls.append(("patch", uuid, body))

    async def update_entitlements(self, uuid, traffic, profile, device_limit=None):
        self.calls.append(("ent", uuid, device_limit))

    async def disable_user(self, uuid):
        self.calls.append(("disable", uuid))

    async def enable_user(self, uuid):
        self.calls.append(("enable", uuid))


ADMIN = SimpleNamespace(email="ops@corgi.test", id=1)


def req():
    return Request({"type": "http", "method": "GET", "path": "/api/me/company", "headers": [], "query_string": b"", "client": ("10.0.0.1", 1)})


@pytest.fixture
def env(database, monkeypatch):  # noqa: F811
    panel = Panel()
    monkeypatch.setattr(shop, "RemnawaveClient", lambda: panel)
    who = {"id": 1}

    async def current(request, session):
        return await session.get(User, who["id"])
    monkeypatch.setattr(shop, "user_from_token", current)

    async def lock(*a, **k):
        return None
    monkeypatch.setattr(shop, "_advisory_lock", lock)
    return SimpleNamespace(db=database, panel=panel, who=who)


async def _company(db, seats=2, devices=2):
    db.add(User(id=3, referral_code="EMP3"))
    await db.commit()
    body = corp.CompanyIn(name="ООО Ромашка", inn="7701234567", kpp="770101001", plan_id=1, seats=seats, devices_per_seat=devices,
                          seat_price=Decimal("300"), admin_user_id=1)
    out = await corp.admin_create(body, db, ADMIN)
    return out["id"], out["invite_code"]


@pytest.mark.asyncio
async def test_invoice_payment_opens_access_for_employees_within_seats(env):
    db = env.db
    cid, code = await _company(db, seats=1)
    view = await corp.my_company(req(), db)
    assert view["role"] == "admin" and view["company"]["seats"] == 1 and view["company"]["device_pool"] == 2 and "seat_price" not in view["company"]
    env.who["id"] = 2
    joined = await corp.join(corp.JoinIn(code=code), req(), db)
    member = await db.get(CorporateMember, joined["member_id"])
    sub = await db.get(Subscription, member.subscription_id)
    assert sub.lifecycle_status == "expired" or sub.remnawave_uuid is None, "no access before the company pays"
    env.who["id"] = 3
    with pytest.raises(HTTPException) as full:
        await corp.join(corp.JoinIn(code=code), req(), db)
    assert full.value.status_code == 409, "one seat only"
    inv = await corp.admin_invoice(cid, corp.InvoiceIn(months=3), db, ADMIN)
    assert inv["amount"] == "900.00"
    done = await corp.admin_invoice_paid(inv["id"], db, ADMIN)
    await db.refresh(sub)
    assert sub.lifecycle_status == "active" and sub.device_limit_snapshot == 2 and sub.remnawave_uuid.startswith("rw-")
    assert abs((sub.expires_at - datetime.fromisoformat(done["paid_until"])).total_seconds()) < 1
    assert any(c[0] == "create" and c[3] == 2 for c in env.panel.calls)
    with pytest.raises(HTTPException):
        await corp.admin_invoice_paid(inv["id"], db, ADMIN)  # twice: refused
    html = await corp.admin_invoice_html(inv["id"], db, ADMIN)
    assert "ООО Ромашка" in html.body.decode() and "900.00" in html.body.decode()


@pytest.mark.asyncio
async def test_device_pool_and_removal(env):
    db = env.db
    cid, code = await _company(db, seats=2, devices=2)
    await corp.admin_invoice_paid((await corp.admin_invoice(cid, corp.InvoiceIn(months=1), db, ADMIN))["id"], db, ADMIN)
    env.who["id"] = 2
    m2 = (await corp.join(corp.JoinIn(code=code), req(), db))["member_id"]
    env.who["id"] = 3
    m3 = (await corp.join(corp.JoinIn(code=code), req(), db))["member_id"]
    env.who["id"] = 1
    with pytest.raises(HTTPException) as over:
        await corp.set_devices(m2, corp.DevicesIn(devices=3), req(), db)
    assert over.value.status_code == 409, "the pool is 4 devices and the other member has 2"
    await corp.set_devices(m2, corp.DevicesIn(devices=2, label="Бухгалтерия"), req(), db)
    view = await corp.my_company(req(), db)
    assert view["devices_used"] == 4 and {m["name"] for m in view["members"]} >= {"Бухгалтерия"}
    await corp.remove(m3, req(), db)
    sub3 = await db.get(Subscription, (await db.get(CorporateMember, m3)).subscription_id)
    assert sub3.lifecycle_status == "expired" and ("disable", sub3.remnawave_uuid) in env.panel.calls
    env.who["id"] = 2
    with pytest.raises(HTTPException) as not_admin:
        await corp.set_devices(m2, corp.DevicesIn(devices=1), req(), db)
    assert not_admin.value.status_code == 403


@pytest.mark.asyncio
async def test_unpaid_company_suspends_access(env):
    db = env.db
    cid, code = await _company(db)
    await corp.admin_invoice_paid((await corp.admin_invoice(cid, corp.InvoiceIn(months=1), db, ADMIN))["id"], db, ADMIN)
    env.who["id"] = 2
    m2 = (await corp.join(corp.JoinIn(code=code), req(), db))["member_id"]
    company = await db.get(corp.CorporateAccount, cid)
    company.paid_until = datetime.utcnow().replace(year=2020)
    await db.commit()
    assert await corp.sync_member(db, m2) == "ended"
    invoices = (await db.execute(select(CorporateInvoice))).scalars().all()
    assert [i.status for i in invoices] == ["paid"]
