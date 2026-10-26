"""Partner portal backed by immutable commissions and reserved payouts."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import Payment, Reseller, PartnerCommission, PartnerWithdrawal, User
from .security import require_permission

router = APIRouter(tags=['partners'])


async def checkout_terms(db, slug, plan_id, user_id):
    slug = str(slug or '').strip().lower()
    if not slug:return {'reseller_id': None, 'reseller_slug_snapshot': None, 'reseller_percent_snapshot': None}
    partner = await db.scalar(select(Reseller).where(Reseller.slug == slug, Reseller.enabled.is_(True)))
    if not partner:raise HTTPException(404, 'Партнёр не найден')
    if partner.balance_currency and partner.balance_currency != settings.default_currency:
        raise HTTPException(409, "Валюта партнёрского баланса отличается от валюты магазина")
    if partner.owner_user_id == user_id:raise HTTPException(409, 'Партнёрская комиссия за собственную покупку не начисляется')
    if partner.plan_ids and plan_id not in partner.plan_ids:raise HTTPException(403, 'Тариф недоступен этому партнёру')
    return {'reseller_id': partner.id, 'reseller_slug_snapshot': slug, 'reseller_percent_snapshot': partner.commission_percent}


async def latest_partner_order(db, subscription_id):
    """The latest paid order of the subscription, if it came through a partner.

    A later direct purchase ends the attribution: renewals then pay no commission."""
    latest = await db.scalar(select(Payment).where(Payment.subscription_id == subscription_id, Payment.purpose == 'subscription',
                                                   Payment.status.in_(('paid', 'fulfilled'))).order_by(Payment.id.desc()).limit(1))
    return latest if latest is not None and latest.reseller_id is not None else None


async def renewal_terms(db, subscription_id):
    """Partner snapshot for an automatic renewal: the partner of the latest paid order of
    the same subscription keeps earning its percent while the partner stays enabled."""
    if not subscription_id:
        return {}
    previous = await latest_partner_order(db, subscription_id)
    if not previous:
        return {}
    partner = await db.get(Reseller, previous.reseller_id)
    if not partner or not partner.enabled:
        return {}
    return {'reseller_id': partner.id, 'reseller_slug_snapshot': previous.reseller_slug_snapshot,
            'reseller_percent_snapshot': previous.reseller_percent_snapshot}


async def credit_gift(db, gift, terms):
    """Commission for a gift bought from the wallet through a partner link (once per gift)."""
    if not terms or not terms.get('reseller_id') or terms.get('reseller_percent_snapshot') is None:
        return None
    if await db.scalar(select(PartnerCommission.id).where(PartnerCommission.gift_code_id == gift.id)):
        return None
    partner = await db.scalar(select(Reseller).where(Reseller.id == terms['reseller_id']).with_for_update().execution_options(populate_existing=True))
    if not partner:
        return None
    currency = settings.default_currency
    if partner.balance_currency and partner.balance_currency != currency:
        raise HTTPException(409, 'Валюта партнёрского баланса отличается от валюты магазина')
    partner.balance_currency = currency
    percent = Decimal(str(terms['reseller_percent_snapshot']))
    amount = (Decimal(str(gift.purchase_amount)) * percent / Decimal(100)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    row = PartnerCommission(payment_id=None, gift_code_id=gift.id, reseller_id=partner.id, amount=amount, percent=percent, currency=currency)
    db.add(row)
    partner.balance = Decimal(partner.balance or 0) + amount
    await db.flush()
    return row


def check_retry(payment, payload):
    if payment.reseller_slug_snapshot != (str(payload.get('reseller_slug') or '').strip().lower() or None):
        raise HTTPException(409, 'Ключ уже использован для другого партнёра')


async def credit(db, payment):
    payment = await db.scalar(select(Payment).where(Payment.id == payment.id).with_for_update().execution_options(populate_existing=True))
    if not payment or not payment.reseller_id or payment.reseller_percent_snapshot is None:
        return
    if payment.purpose != 'subscription' or payment.status not in {'paid', 'fulfilled'} or payment.fulfillment_status != 'completed':return
    if await db.scalar(select(PartnerCommission.id).where(PartnerCommission.payment_id == payment.id)):return
    partner = await db.scalar(select(Reseller).where(Reseller.id == payment.reseller_id).with_for_update().execution_options(populate_existing=True))
    if not partner:raise RuntimeError('Partner snapshot owner missing')
    if partner.balance_currency and partner.balance_currency != payment.currency:
        raise RuntimeError('Cannot mix partner balance currencies')
    partner.balance_currency = payment.currency
    amount = (payment.amount * payment.reseller_percent_snapshot / Decimal(100)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    db.add(PartnerCommission(payment_id=payment.id, reseller_id=partner.id, amount=amount,
        percent=payment.reseller_percent_snapshot, currency=payment.currency))
    partner.balance = Decimal(partner.balance or 0) + amount
    await db.flush()


async def reverse(db, payment):
    await db.scalar(select(Payment.id).where(Payment.id == payment.id).with_for_update())
    row = await db.scalar(select(PartnerCommission).where(PartnerCommission.payment_id == payment.id).with_for_update().execution_options(populate_existing=True))
    if not row or row.status == 'reversed':return
    partner = await db.scalar(select(Reseller).where(Reseller.id == row.reseller_id).with_for_update().execution_options(populate_existing=True))
    partner.balance = Decimal(partner.balance or 0)-row.amount
    row.status = 'reversed';row.reversed_at = datetime.utcnow()
    await db.flush()


async def owned_partner(db, request, lock=False):
    from .main import user_from_token
    user = await user_from_token(request, db)
    if user.restricted_at:raise HTTPException(403, 'Аккаунт ограничен')
    statement = select(Reseller).where(Reseller.owner_user_id == user.id)
    if lock:statement = statement.with_for_update().execution_options(populate_existing=True)
    partner = await db.scalar(statement)
    if not partner:raise HTTPException(404, 'Партнёрский кабинет не подключён')
    return partner


def withdrawal_view(row):
    return {'id': row.id, 'amount': str(row.amount), 'currency': row.currency,
        'status': row.status, 'created_at': row.created_at, 'updated_at': row.updated_at,
        'reference': row.reference}


@router.get('/api/me/partner')
async def portal(request: Request, db: AsyncSession = Depends(get_db)):
    partner = await owned_partner(db, request)
    rows = (await db.scalars(select(PartnerCommission).where(PartnerCommission.reseller_id == partner.id).order_by(PartnerCommission.id.desc()).limit(100))).all()
    withdrawals = (await db.scalars(select(PartnerWithdrawal).where(PartnerWithdrawal.reseller_id == partner.id).order_by(PartnerWithdrawal.id.desc()).limit(100))).all()
    query = urlencode({'partner': partner.slug})
    return {'name': partner.name, 'slug': partner.slug, 'enabled': partner.enabled,
        'commission_percent': str(partner.commission_percent), 'balance': str(partner.balance),
        'currency': partner.balance_currency or settings.default_currency, 'plan_ids': partner.plan_ids or [],
        'link': settings.cabinet_url.rstrip('/')+'/?'+query,
        'commissions': [{'id': x.id, 'amount': str(x.amount), 'percent': str(x.percent),
            'currency': x.currency, 'status': x.status, 'created_at': x.created_at} for x in rows],
        'withdrawals': [withdrawal_view(x) for x in withdrawals]}


class WithdrawalIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    amount: Decimal = Field(ge=1, le=10000000, max_digits=12, decimal_places=2)
    destination: str = Field(min_length=3, max_length=255)


@router.post('/api/me/partner/withdrawals')
async def withdraw(payload: WithdrawalIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import audit
    partner = await owned_partner(db, request, True)
    key = request.headers.get('Idempotency-Key', '')
    if not 1 <= len(key) <= 128 or any(ord(c)<32 or ord(c)>126 for c in key):raise HTTPException(422, 'Idempotency-Key обязателен')
    destination = payload.destination.strip()
    if len(destination) < 3:raise HTTPException(422, 'Укажите реквизиты')
    previous = await db.scalar(select(PartnerWithdrawal).where(PartnerWithdrawal.reseller_id == partner.id, PartnerWithdrawal.idempotency_key == key))
    if previous:
        if previous.amount != payload.amount or previous.destination != destination:raise HTTPException(409, 'Ключ использован для другой выплаты')
        return withdrawal_view(previous)
    if not partner.enabled:raise HTTPException(409, 'Партнёр отключён; обратитесь к оператору')
    if partner.balance < payload.amount:raise HTTPException(409, 'Недостаточно доступной комиссии')
    partner.balance -= payload.amount
    row = PartnerWithdrawal(reseller_id=partner.id, amount=payload.amount, currency=partner.balance_currency or settings.default_currency,
        destination=destination, idempotency_key=key)
    db.add(row);await db.flush()
    await audit(db, 'partner.withdrawal_requested', f'partner:{partner.id}', str(row.id), {'amount': str(row.amount)})
    await db.commit()
    return withdrawal_view(row)


@router.get('/api/admin/marketplace/withdrawals')
async def withdrawals(db: AsyncSession = Depends(get_db), admin=Depends(require_permission('referrals.withdrawals.read'))):
    rows = (await db.scalars(select(PartnerWithdrawal).order_by(PartnerWithdrawal.id.desc()).limit(200))).all()
    return [{**withdrawal_view(x), 'reseller_id': x.reseller_id, 'destination': x.destination} for x in rows]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: str = Field(pattern='^(approved|paid|rejected)$')
    reference: str | None = Field(default=None, max_length=255)


@router.post('/api/admin/marketplace/withdrawals/{withdrawal_id}/decision')
async def decide(withdrawal_id: int, payload: DecisionIn, db: AsyncSession = Depends(get_db),
        admin=Depends(require_permission('referrals.withdrawals.approve'))):
    from .main import audit
    seed = await db.get(PartnerWithdrawal, withdrawal_id)
    if not seed:raise HTTPException(404, 'Заявка не найдена')
    # Same lock order as request, credit and clawback: partner before withdrawal.
    partner = await db.scalar(select(Reseller).where(Reseller.id == seed.reseller_id).with_for_update().execution_options(populate_existing=True))
    row = await db.scalar(select(PartnerWithdrawal).where(PartnerWithdrawal.id == seed.id).with_for_update().execution_options(populate_existing=True))
    reference = (payload.reference or '').strip() or None
    if row.status == payload.status:
        if row.reference != reference:raise HTTPException(409, 'Решение уже сохранено с другой ссылкой операции')
        return withdrawal_view(row)
    if row.status in {'paid', 'rejected'}:raise HTTPException(409, 'Заявка уже завершена')
    if payload.status == 'paid' and (row.status != 'approved' or not reference):
        raise HTTPException(409, 'Сначала одобрите заявку и укажите номер фактической выплаты')
    if payload.status == 'rejected':partner.balance += row.amount
    row.status = payload.status;row.reference = reference;row.updated_at = datetime.utcnow()
    await audit(db, 'partner.withdrawal_' + row.status, admin.email, str(row.id), {'reference': reference})
    await db.commit()
    return withdrawal_view(row)
