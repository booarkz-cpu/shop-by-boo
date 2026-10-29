"""Corporate plans (v28.48): a company buys seats on one plan, the company admin invites employees, each gets their own
access with devices from the company pool, and the company pays by invoice.

* **Operator** («Корпоративный → Компании»): company requisites (name, INN, KPP, address, e-mail), the plan, seats,
  devices per seat (the pool is ``seats × devices_per_seat``), the price of a seat per month; issues an invoice for N
  months and marks it paid when the money arrives — ``paid_until`` moves on and every member's access follows.
* **Company admin** (cabinet / Mini App «Компания»): the invite link, members, devices per member within the pool,
  removing a member, the invoices (printable).
* **Employee**: joins by the link (``/api/me/company/join``) and gets a subscription of their own on the company plan
  until ``paid_until``. The oldest members keep their seats when there are more members than seats; the others wait.
* Access follows the company like a family subscription follows its owner (``sync_member``): the Remnawave user is
  created, its expiry, devices, traffic and squad kept equal to the company's; a removed member or an unpaid company
  loses access. A loop syncs every 10 minutes.
"""
from __future__ import annotations

import asyncio
import html
import logging
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import CorporateAccount, CorporateInvoice, CorporateMember, Plan, Subscription, User
from .security import require_permission

logger = logging.getLogger("vpnshop.corporate")
router = APIRouter()
SELLER_KEY = "corporate.seller"
SELLER_DEFAULT = {"name": "", "inn": "", "kpp": "", "address": "", "bank": "", "bik": "", "account": "", "corr_account": ""}
SYNC_SECONDS = 600


def _code() -> str:
    return secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")


def paid(company: CorporateAccount | None, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    return bool(company and company.enabled and company.paid_until and company.paid_until > now)


def pool(company: CorporateAccount) -> int:
    return int(company.seats or 0) * max(1, int(company.devices_per_seat or 1))


async def members(db: AsyncSession, company: CorporateAccount) -> list[CorporateMember]:
    return (await db.execute(select(CorporateMember).where(CorporateMember.account_id == company.id, CorporateMember.status == "active")
                             .order_by(CorporateMember.joined_at, CorporateMember.id))).scalars().all()


async def users_of(db: AsyncSession, company: CorporateAccount) -> list[CorporateMember]:
    """Members who use the VPN (joined with their own access); an admin who only manages does not take a seat."""
    return [m for m in await members(db, company) if m.subscription_id]


async def seated_ids(db: AsyncSession, company: CorporateAccount) -> list[int]:
    return [m.id for m in (await users_of(db, company))[:int(company.seats or 0)]]


# ------------------------------------------------------------------ access
async def sync_member(db: AsyncSession, member_id: int, rw=None) -> str:
    """Make the member's Remnawave user follow the company (idempotent)."""
    from .main import RemnawaveClient
    rw = rw or RemnawaveClient()
    member = await db.get(CorporateMember, member_id)
    company = await db.get(CorporateAccount, member.account_id) if member else None
    sub = await db.get(Subscription, member.subscription_id) if member and member.subscription_id else None
    if not member or not company or not sub:
        return "missing"
    now = datetime.utcnow()
    try:
        plan = await db.get(Plan, company.plan_id) if company.plan_id else None
        if member.status != "active" or not paid(company, now) or not plan or member.id not in await seated_ids(db, company):
            if sub.remnawave_uuid and sub.lifecycle_status != "expired":
                await rw.disable_user(sub.remnawave_uuid)
            sub.lifecycle_status, sub.expires_at = "expired", min(sub.expires_at or now, now)
            result = "ended"
        else:
            target = company.paid_until
            devices = max(1, int(member.devices or 1))
            traffic, profile = plan.traffic_limit_gb, plan.remnawave_profile_id
            if not sub.remnawave_uuid:
                user = await db.get(User, member.user_id)
                data = await rw.create_user(f"user_{member.user_id}_sub_{sub.id}", target, int(traffic) * 1024 ** 3 if traffic else 0,
                                            active_internal_squads=[profile] if profile else None,
                                            telegram_id=user.telegram_id if user else None, device_limit=devices)
                if not data or not data.get("id"):
                    raise RuntimeError("Remnawave returned no user id")
                sub.remnawave_uuid = str(data["id"])
                sub.subscription_url = data.get("subscriptionUrl") or data.get("subscription_url")
                result = "created"
            else:
                if sub.lifecycle_status == "expired":
                    await rw.enable_user(sub.remnawave_uuid)
                if not sub.expires_at or abs((sub.expires_at - target).total_seconds()) > 60:
                    await rw.patch_user(sub.remnawave_uuid, {"expireAt": target.isoformat()})
                if (sub.traffic_limit_gb_snapshot, sub.device_limit_snapshot, sub.remnawave_profile_id_snapshot) != (traffic, devices, profile):
                    await rw.update_entitlements(sub.remnawave_uuid, traffic, profile, device_limit=devices)
                result = "updated"
            sub.expires_at, sub.lifecycle_status, sub.plan_id = target, "active", plan.id
            sub.traffic_limit_gb_snapshot, sub.device_limit_snapshot, sub.remnawave_profile_id_snapshot = traffic, devices, profile
        member.synced_at, member.sync_error = now, None
    except Exception as exc:
        member.sync_error = str(exc)[:500]
        await db.commit()
        raise
    await db.commit()
    return result


async def sync_company(db: AsyncSession, company_id: int) -> dict:
    ids = (await db.execute(select(CorporateMember.id).where(CorporateMember.account_id == company_id))).scalars().all()
    out = {"ok": 0, "failed": 0}
    for mid in ids:
        try:
            await sync_member(db, mid)
            out["ok"] += 1
        except Exception as exc:  # noqa: BLE001 — retried by the loop
            logger.warning("corporate sync %s: %s", mid, exc)
            out["failed"] += 1
    return out


# ------------------------------------------------------------------ invoices
async def seller(db: AsyncSession) -> dict:
    from .node_health import _load
    return await _load(db, SELLER_KEY, SELLER_DEFAULT)


def invoice_html(inv: CorporateInvoice, company: CorporateAccount, plan: Plan | None, sell: dict) -> str:
    e = html.escape
    rows = [("Поставщик", sell.get("name")), ("ИНН / КПП поставщика", f"{sell.get('inn') or ''} / {sell.get('kpp') or ''}"),
            ("Адрес поставщика", sell.get("address")), ("Банк", sell.get("bank")), ("БИК", sell.get("bik")),
            ("Расчётный счёт", sell.get("account")), ("Корр. счёт", sell.get("corr_account")),
            ("Покупатель", company.name), ("ИНН / КПП покупателя", f"{company.vat_id or ''} / {company.kpp or ''}"),
            ("Адрес покупателя", company.legal_address)]
    item = f"Доступ к VPN-сервису, тариф «{plan.name if plan else '—'}»: {inv.seats} мест × {inv.months} мес."
    table = "".join(f"<tr><th>{e(k)}</th><td>{e(str(v or '—'))}</td></tr>" for k, v in rows)
    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><title>Счёт № {e(inv.number)}</title>
<style>body{{font:14px/1.45 Arial,sans-serif;max-width:760px;margin:24px auto;color:#111}}table{{border-collapse:collapse;width:100%;margin:12px 0}}
th,td{{border:1px solid #999;padding:6px 8px;text-align:left;vertical-align:top}}th{{width:38%;background:#f3f3f3}}.total{{font-size:18px;font-weight:bold}}
@media print{{button{{display:none}}}}</style></head><body>
<h2>Счёт на оплату № {e(inv.number)} от {inv.issued_at:%d.%m.%Y}</h2><table>{table}</table>
<table><tr><th>Наименование</th><th>Сумма</th></tr><tr><td>{e(item)}</td><td>{inv.amount} {e(inv.currency)}</td></tr></table>
<p class="total">Итого к оплате: {inv.amount} {e(inv.currency)}</p>
<p>Назначение платежа: «Оплата по счёту № {e(inv.number)}. Без НДС», если вы не плательщик НДС; иначе укажите ставку.</p>
<p>Статус: {"оплачен " + inv.paid_at.strftime("%d.%m.%Y") if inv.status == "paid" and inv.paid_at else "отменён" if inv.status == "cancelled" else "ожидает оплаты"}</p>
<button onclick="print()">Распечатать или сохранить в PDF</button></body></html>"""


def _company_view(c: CorporateAccount, used: int, plan: Plan | None) -> dict:
    return {"id": c.id, "name": c.name, "inn": c.vat_id, "kpp": c.kpp, "legal_address": c.legal_address, "contact_email": c.contact_email,
            "country": c.country, "plan_id": c.plan_id, "plan": plan.name if plan else None, "seats": c.seats, "seats_used": used,
            "devices_per_seat": c.devices_per_seat, "device_pool": pool(c), "seat_price": str(c.seat_price), "enabled": c.enabled,
            "paid_until": c.paid_until.isoformat() if c.paid_until else None, "active": paid(c), "invite_code": c.invite_code}


# ------------------------------------------------------------------ operator
class CompanyIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    inn: str | None = Field(None, max_length=64)
    kpp: str | None = Field(None, max_length=16)
    legal_address: str | None = Field(None, max_length=1000)
    contact_email: str | None = Field(None, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    country: str = Field("RU", min_length=2, max_length=2)
    plan_id: int
    seats: int = Field(ge=1, le=10000)
    devices_per_seat: int = Field(1, ge=1, le=20)
    seat_price: Decimal = Field(ge=0)
    enabled: bool = True
    admin_user_id: int | None = None


class SellerIn(BaseModel):
    name: str = Field("", max_length=255)
    inn: str = Field("", max_length=16)
    kpp: str = Field("", max_length=16)
    address: str = Field("", max_length=500)
    bank: str = Field("", max_length=255)
    bik: str = Field("", max_length=16)
    account: str = Field("", max_length=32)
    corr_account: str = Field("", max_length=32)


class InvoiceIn(BaseModel):
    months: int = Field(1, ge=1, le=36)


async def _set_admin(db: AsyncSession, company: CorporateAccount, user_id: int) -> None:
    if not await db.get(User, user_id):
        raise HTTPException(404, "Клиент для администратора компании не найден")
    m = await db.scalar(select(CorporateMember).where(CorporateMember.account_id == company.id, CorporateMember.user_id == user_id))
    if m:
        m.role, m.status = "admin", "active"
    else:
        db.add(CorporateMember(account_id=company.id, user_id=user_id, role="admin", devices=0, label="Администратор"))


@router.get("/api/admin/corporate")
async def admin_list(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    out = []
    for c in (await db.execute(select(CorporateAccount).order_by(CorporateAccount.id.desc()))).scalars().all():
        used = len(await users_of(db, c))
        plan = await db.get(Plan, c.plan_id) if c.plan_id else None
        invoices = (await db.execute(select(CorporateInvoice).where(CorporateInvoice.account_id == c.id).order_by(CorporateInvoice.id.desc()).limit(10))).scalars().all()
        out.append({**_company_view(c, used, plan), "invoices": [{"id": i.id, "number": i.number, "months": i.months, "amount": str(i.amount),
                                                                  "status": i.status, "issued_at": i.issued_at.isoformat()} for i in invoices]})
    return {"companies": out, "seller": await seller(db)}


@router.post("/api/admin/corporate")
async def admin_create(body: CompanyIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_users"))):
    return await _save_company(db, None, body, admin)


@router.put("/api/admin/corporate/{company_id}")
async def admin_update(company_id: int, body: CompanyIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_users"))):
    return await _save_company(db, company_id, body, admin)


async def _save_company(db, company_id, body: CompanyIn, admin) -> dict:
    from . import main as shop
    if not await db.get(Plan, body.plan_id):
        raise HTTPException(404, "Тариф не найден")
    c = await db.get(CorporateAccount, company_id) if company_id else None
    if company_id and not c:
        raise HTTPException(404, "Компания не найдена")
    if not c:
        c = CorporateAccount(owner_user_id=body.admin_user_id or 0, name=body.name, invite_code=_code())
        db.add(c)
    c.name, c.vat_id, c.kpp, c.legal_address = body.name, body.inn, body.kpp, body.legal_address
    c.contact_email, c.country, c.plan_id, c.seats = body.contact_email, body.country.upper(), body.plan_id, body.seats
    c.devices_per_seat, c.seat_price, c.enabled = body.devices_per_seat, body.seat_price, body.enabled
    c.invite_code = c.invite_code or _code()
    await db.flush()
    if body.admin_user_id:
        c.owner_user_id = body.admin_user_id
        await _set_admin(db, c, body.admin_user_id)
    await shop.audit(db, "corporate.saved", admin.email, str(c.id), body.model_dump(mode="json"))
    await db.commit()
    await sync_company(db, c.id)
    return {"id": c.id, "invite_code": c.invite_code}


@router.put("/api/admin/corporate-seller")
async def admin_seller(body: SellerIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_users"))):
    from .node_health import _save
    await _save(db, SELLER_KEY, body.model_dump())
    await db.commit()
    return {"ok": True}


@router.post("/api/admin/corporate/{company_id}/invoices")
async def admin_invoice(company_id: int, body: InvoiceIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("payments.reconcile"))):
    from . import main as shop
    c = await db.get(CorporateAccount, company_id)
    if not c:
        raise HTTPException(404, "Компания не найдена")
    amount = (Decimal(str(c.seat_price)) * int(c.seats) * body.months).quantize(Decimal("0.01"))
    if amount <= 0:
        raise HTTPException(409, "Задайте места и цену места")
    count = int(await db.scalar(select(func.count()).select_from(CorporateInvoice)) or 0)
    inv = CorporateInvoice(account_id=c.id, number=f"К-{datetime.utcnow():%Y%m}-{count + 1:04d}", months=body.months, seats=c.seats,
                           amount=amount, currency=settings.default_currency, issued_at=datetime.utcnow())
    db.add(inv)
    await shop.audit(db, "corporate.invoice.issued", admin.email, str(c.id), {"months": body.months, "amount": str(amount)})
    await db.commit()
    return {"id": inv.id, "number": inv.number, "amount": str(amount)}


@router.post("/api/admin/corporate/invoices/{invoice_id}/paid")
async def admin_invoice_paid(invoice_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("payments.reconcile"))):
    """The money arrived: the company is paid ``months`` further (from today when it had lapsed); members follow."""
    from . import main as shop
    inv = (await db.execute(select(CorporateInvoice).where(CorporateInvoice.id == invoice_id).with_for_update())).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Счёт не найден")
    if inv.status != "issued":
        raise HTTPException(409, "Счёт уже оплачен или отменён")
    c = await db.get(CorporateAccount, inv.account_id)
    now = datetime.utcnow()
    start = c.paid_until if c.paid_until and c.paid_until > now else now
    c.paid_until = start + timedelta(days=30 * inv.months)
    inv.status, inv.paid_at = "paid", now
    admin_member = await db.scalar(select(CorporateMember).where(CorporateMember.account_id == c.id, CorporateMember.role == "admin"))
    await shop.record_financial_event(db, operation_key=f"corporate-invoice:{inv.id}:paid", user_id=admin_member.user_id if admin_member else None,
                                      payment_id=None, kind="corporate_invoice", direction="credit", amount=Decimal(str(inv.amount)),
                                      currency=inv.currency, metadata={"company": c.id, "invoice": inv.number, "months": inv.months})
    await shop.audit(db, "corporate.invoice.paid", admin.email, str(c.id), {"invoice": inv.number, "paid_until": c.paid_until.isoformat()})
    await db.commit()
    synced = await sync_company(db, c.id)
    return {"ok": True, "paid_until": c.paid_until.isoformat(), "synced": synced}


@router.post("/api/admin/corporate/invoices/{invoice_id}/cancel")
async def admin_invoice_cancel(invoice_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("payments.reconcile"))):
    inv = await db.get(CorporateInvoice, invoice_id)
    if not inv or inv.status != "issued":
        raise HTTPException(409, "Отменить можно только неоплаченный счёт")
    inv.status = "cancelled"
    await db.commit()
    return {"ok": True}


@router.get("/api/admin/corporate/invoices/{invoice_id}.html", response_class=HTMLResponse)
async def admin_invoice_html(invoice_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    inv = await db.get(CorporateInvoice, invoice_id)
    if not inv:
        raise HTTPException(404, "Счёт не найден")
    c = await db.get(CorporateAccount, inv.account_id)
    return HTMLResponse(invoice_html(inv, c, await db.get(Plan, c.plan_id) if c.plan_id else None, await seller(db)))


# ------------------------------------------------------------------ company admin and employees
async def _membership(db: AsyncSession, user: User) -> tuple[CorporateMember | None, CorporateAccount | None]:
    m = await db.scalar(select(CorporateMember).where(CorporateMember.user_id == user.id, CorporateMember.status == "active")
                        .order_by(CorporateMember.role.asc(), CorporateMember.id))  # «admin» sorts before «member»
    return m, (await db.get(CorporateAccount, m.account_id) if m else None)


async def _admin_of(db: AsyncSession, request: Request) -> tuple[User, CorporateAccount]:
    from . import main as shop
    user = await shop.user_from_token(request, db)
    m, c = await _membership(db, user)
    if not m or m.role != "admin" or not c:
        raise HTTPException(403, "Только администратор компании")
    return user, c


@router.get("/api/me/company")
async def my_company(request: Request, db: AsyncSession = Depends(get_db)):
    from . import main as shop
    user = await shop.user_from_token(request, db)
    m, c = await _membership(db, user)
    if not m or not c:
        return {"member": False}
    plan = await db.get(Plan, c.plan_id) if c.plan_id else None
    active = await members(db, c)
    seated = await seated_ids(db, c)
    view = {"member": True, "role": m.role, "company": {k: v for k, v in _company_view(c, len(await users_of(db, c)), plan).items() if k != "seat_price"},
            "my_devices": m.devices, "has_seat": m.id in seated, "joined": bool(m.subscription_id), "member_id": m.id}
    if m.role == "admin":
        users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_([x.user_id for x in active])))).scalars().all()} if active else {}
        view["members"] = [{"id": x.id, "user_id": x.user_id, "name": x.label or (users.get(x.user_id).username if users.get(x.user_id) else "") or f"#{x.user_id}",
                            "role": x.role, "devices": x.devices, "seated": x.id in seated, "joined_at": x.joined_at.isoformat(),
                            "sync_error": bool(x.sync_error)} for x in active]
        view["devices_used"] = sum(int(x.devices or 0) for x in active if x.subscription_id)
        base = (settings.cabinet_url or settings.mini_app_url or "").rstrip("/")
        view["invite_link"] = f"{base}/?company={c.invite_code}" if base else c.invite_code
        view["invoices"] = [{"id": i.id, "number": i.number, "months": i.months, "amount": str(i.amount), "currency": i.currency, "status": i.status}
                            for i in (await db.execute(select(CorporateInvoice).where(CorporateInvoice.account_id == c.id).order_by(CorporateInvoice.id.desc()).limit(24))).scalars().all()]
    return view


class JoinIn(BaseModel):
    code: str = Field(min_length=6, max_length=32, pattern=r"^[A-Za-z0-9]+$")


@router.post("/api/me/company/join")
async def join(payload: JoinIn, request: Request, db: AsyncSession = Depends(get_db)):
    from . import main as shop
    user = await shop.user_from_token(request, db)
    c = await db.scalar(select(CorporateAccount).where(CorporateAccount.invite_code == payload.code, CorporateAccount.enabled.is_(True)))
    if not c:
        raise HTTPException(404, "Приглашение не найдено или устарело")
    await shop._advisory_lock(db, 740000000 + int(c.id))
    existing = await db.scalar(select(CorporateMember).where(CorporateMember.account_id == c.id, CorporateMember.user_id == user.id))
    if existing and existing.status == "active" and existing.subscription_id:  # already has access
        return {"ok": True, "member_id": existing.id, "already": True}
    if len(await users_of(db, c)) >= int(c.seats or 0):
        raise HTTPException(409, "Все места компании заняты — попросите администратора добавить места")
    has_primary = await db.scalar(select(Subscription.id).where(Subscription.user_id == user.id, Subscription.is_primary.is_(True)))
    sub = Subscription(user_id=user.id, plan_id=c.plan_id, is_primary=not has_primary, lifecycle_status="pending", name=f"Компания «{c.name}»"[:120],
                       expires_at=None, unit_price_per_day=0)
    db.add(sub)
    await db.flush()
    used = sum(int(x.devices or 0) for x in await users_of(db, c))
    devices = max(1, min(int(c.devices_per_seat or 1), pool(c) - used))
    if existing:
        existing.status, existing.removed_at, existing.subscription_id, existing.joined_at = "active", None, sub.id, datetime.utcnow()
        existing.devices = existing.devices or devices  # an admin joins with devices from the pool too
        member = existing
    else:
        member = CorporateMember(account_id=c.id, user_id=user.id, subscription_id=sub.id, devices=devices)
        db.add(member)
    await db.flush()
    await shop.audit(db, "corporate.joined", f"user:{user.id}", str(c.id), {"member": member.id})
    await db.commit()
    try:
        await sync_member(db, member.id)
    except Exception as exc:  # noqa: BLE001 — the loop retries
        logger.warning("corporate member %s first sync failed: %s", member.id, exc)
    return {"ok": True, "member_id": member.id}


class DevicesIn(BaseModel):
    devices: int = Field(ge=1, le=50)
    label: str | None = Field(None, max_length=120)


@router.put("/api/me/company/members/{member_id}")
async def set_devices(member_id: int, body: DevicesIn, request: Request, db: AsyncSession = Depends(get_db)):
    _, c = await _admin_of(db, request)
    m = await db.get(CorporateMember, member_id)
    if not m or m.account_id != c.id or m.status != "active":
        raise HTTPException(404, "Сотрудник не найден")
    others = sum(int(x.devices or 0) for x in await users_of(db, c) if x.id != m.id)
    if others + body.devices > pool(c):
        raise HTTPException(409, f"В пуле компании {pool(c)} устройств, свободно {max(0, pool(c) - others)}")
    m.devices = body.devices
    if body.label is not None:
        m.label = body.label
    await db.commit()
    if m.subscription_id:
        await sync_member(db, m.id)
    return {"ok": True}


@router.delete("/api/me/company/members/{member_id}")
async def remove(member_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """The company admin removes an employee, or an employee leaves."""
    from . import main as shop
    user = await shop.user_from_token(request, db)
    m = await db.get(CorporateMember, member_id)
    if not m or m.status != "active":
        raise HTTPException(404, "Сотрудник не найден")
    me, c = await _membership(db, user)
    if m.user_id != user.id and not (me and me.role == "admin" and c and c.id == m.account_id):
        raise HTTPException(403, "Только администратор компании")
    m.status, m.removed_at = "removed", datetime.utcnow()
    await shop.audit(db, "corporate.removed", f"user:{user.id}", str(m.id), None)
    await db.commit()
    if m.subscription_id:
        await sync_member(db, m.id)
    return {"ok": True}


@router.post("/api/me/company/invite")
async def rotate_invite(request: Request, db: AsyncSession = Depends(get_db)):
    _, c = await _admin_of(db, request)
    c.invite_code = _code()
    await db.commit()
    return {"invite_code": c.invite_code}


@router.get("/api/me/company/invoices/{invoice_id}.html", response_class=HTMLResponse)
async def my_invoice(invoice_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    _, c = await _admin_of(db, request)
    inv = await db.get(CorporateInvoice, invoice_id)
    if not inv or inv.account_id != c.id:
        raise HTTPException(404, "Счёт не найден")
    return HTMLResponse(invoice_html(inv, c, await db.get(Plan, c.plan_id) if c.plan_id else None, await seller(db)))


# ------------------------------------------------------------------ background
async def _loop() -> None:
    from .db import SessionLocal
    from .main import redis_client
    while True:
        try:
            async with SessionLocal() as db:
                if redis_client is None or await redis_client.set("lock:corporate_sync", "1", nx=True, ex=SYNC_SECONDS - 30):
                    ids = (await db.execute(select(CorporateMember.id).join(Subscription, Subscription.id == CorporateMember.subscription_id)
                                            .where((CorporateMember.status == "active") | (Subscription.lifecycle_status != "expired")))).scalars().all()
                    for mid in ids[:1000]:
                        try:
                            await sync_member(db, mid)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("corporate sync %s: %s", mid, exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Corporate sync pass failed: %s", exc)
        await asyncio.sleep(SYNC_SECONDS)


def _start() -> None:
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)
