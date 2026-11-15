"""Immutable referral terms, bounded private network views and refund accounting."""
import hashlib
import hmac
import json
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update

from .config import settings
from .db import get_db
from .models import AppSetting, Payment, ReferralLedger, ReferralLevelReward, ReferralReward, User
from .security import require_permission

router = APIRouter(tags=['referral-program'])
CONFIG_KEY = 'referrals.level_percentages'


def validate_percentages(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 5:
        raise ValueError('Configure between one and five referral levels')
    result = []
    for value in values:
        if isinstance(value, bool):
            raise ValueError('Invalid percentage')
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > 100 or amount.as_tuple().exponent < -2:
            raise ValueError('Percentages must be finite, 0–100, with at most two decimals')
        result.append(amount)
    if sum(result) > 100:
        raise ValueError('Total referral percentage cannot exceed 100')
    return result


class ProgramIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    percentages: list[Decimal] = Field(min_length=1, max_length=5)

    @field_validator('percentages')
    @classmethod
    def valid_percentages(cls, value):
        return validate_percentages(value)


async def percentages(db):
    row = await db.get(AppSetting, CONFIG_KEY)
    try:
        return validate_percentages(json.loads(row.value) if row else [settings.referral_reward_percent])
    except (ValueError, TypeError, ArithmeticError):
        raise HTTPException(503, 'Referral program configuration is invalid')


async def snapshot(db, user):
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy import text
        # Same lock as attribution: one coherent chain while it is captured.
        await db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': 1400000005})
    rates = await percentages(db)
    seen = {user.id}
    ancestor_id = user.referred_by_id
    terms = []
    for level, rate in enumerate(rates, 1):
        if not ancestor_id:
            break
        if ancestor_id in seen:
            raise HTTPException(409, 'Invalid referral cycle')
        seen.add(ancestor_id)
        ancestor = await db.scalar(select(User).where(User.id==ancestor_id).execution_options(populate_existing=True))
        if ancestor is None:
            raise HTTPException(409, 'Invalid referral ancestor')
        # Preserve network depth through an ineligible account; do not shift a
        # distant ancestor into a higher-paying level.
        if ancestor.deleted_at is None and ancestor.restricted_at is None and rate > 0:
            terms.append({'user_id': ancestor.id, 'level': level, 'percent': str(rate)})
        ancestor_id = ancestor.referred_by_id
    return terms


async def credit(db, payment, source_user_id):
    # All callers share the Payment row lock with fulfillment/refunds. Locking
    # here also makes direct reconciliation calls safe on PostgreSQL.
    payment = (await db.scalars(select(Payment).where(Payment.id == payment.id)
        .execution_options(populate_existing=True).with_for_update())).one()
    if payment.status not in {"paid", "fulfilled"} or payment.purpose != "subscription":
        return []
    terms = payment.referral_terms_snapshot
    legacy = terms is None
    if terms is None:
        # Existing intents retain the old one-level contract; never retrofit
        # a newly configured multilevel program onto a historical purchase.
        terms = ([{'user_id': payment.referrer_id_snapshot, 'level': 1,
                   'percent': str(settings.referral_reward_percent)}]
                 if payment.referrer_id_snapshot else [])
    rewards = []
    for item in terms:
        level, uid = int(item['level']), int(item['user_id'])
        model = ReferralReward if level == 1 else ReferralLevelReward
        predicate = [model.payment_id == payment.id]
        if level != 1:
            predicate.append(model.level == level)
        if await db.scalar(select(model.id).where(*predicate)):
            continue
        amount = (Decimal(payment.amount) * Decimal(item['percent']) / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_EVEN if legacy else ROUND_HALF_UP)
        if amount <= 0:
            continue
        result = await db.execute(update(User).where(User.id == uid).values(referral_balance=User.referral_balance + amount))
        if result.rowcount != 1:
            raise RuntimeError('Referrer account not found')
        common = dict(referrer_id=uid, referred_user_id=source_user_id, payment_id=payment.id, amount=amount)
        reward = model(**common, **({'level': level} if level != 1 else {}))
        db.add(reward)
        await db.flush()
        db.add(ReferralLedger(user_id=uid, source_user_id=source_user_id,
                             payment_id=payment.id if level == 1 else None,
                             referral_level_reward_id=reward.id if level != 1 else None,
                             amount=amount, kind='reward' if level == 1 else f'reward_level_{level}'))
        rewards.append({'level': level, 'amount': str(amount)})
    await db.flush()
    return rewards


async def reverse_extra(db, payment):
    await db.scalar(select(Payment.id).where(Payment.id == payment.id).with_for_update())
    rows = (await db.scalars(select(ReferralLevelReward).where(
        ReferralLevelReward.payment_id == payment.id).order_by(ReferralLevelReward.level).execution_options(populate_existing=True).with_for_update())).all()
    total = Decimal('0')
    for row in rows:
        if row.status == 'reversed':
            continue
        result = await db.execute(update(User).where(User.id == row.referrer_id).values(referral_balance=User.referral_balance - row.amount))
        if result.rowcount != 1:
            raise RuntimeError('Referrer account not found during reversal')
        row.status = 'reversed'
        db.add(ReferralLedger(user_id=row.referrer_id, source_user_id=row.referred_user_id,
                             payment_id=None, referral_level_reward_id=row.id, amount=-row.amount, kind=f'refund_level_{row.level}'))
        total += row.amount
    await db.flush()
    return total


async def network(db, root_id, depth, limit):
    # No email/Telegram IDs, names, balances or buyer payment records are
    # exposed to a referrer. The node IDs cannot enumerate database user IDs.
    def node_id(uid):
        return hmac.new(settings.app_secret.encode(), f'referral:{root_id}:{uid}'.encode(), hashlib.sha256).hexdigest()[:24]
    nodes = [{'id': node_id(root_id), 'parent': None, 'level': 0}]
    seen = {root_id}
    frontier = [root_id]
    truncated = False
    for level in range(1, depth + 1):
        if not frontier:
            break
        remaining = limit - len(nodes)
        rows = (await db.execute(select(User.id, User.referred_by_id).where(
            User.referred_by_id.in_(frontier), User.deleted_at.is_(None)).order_by(User.id).limit(remaining + 1))).all()
        if len(rows) > remaining:
            truncated = True
        next_frontier = []
        for uid, parent in rows[:remaining]:
            if uid in seen:
                raise HTTPException(409, 'Invalid referral network cycle')
            seen.add(uid)
            nodes.append({'id': node_id(uid), 'parent': node_id(parent), 'level': level})
            next_frontier.append(uid)
        frontier = next_frontier
        if truncated:
            break
    if frontier and not truncated:
        truncated = bool(await db.scalar(select(User.id).where(User.referred_by_id.in_(frontier), User.deleted_at.is_(None)).limit(1)))
    return {'nodes': nodes, 'truncated': truncated, 'depth': depth, 'limit': limit,
            'level_counts': [{'level': n, 'count': sum(x['level'] == n for x in nodes)} for n in range(1, depth + 1)]}


@router.get('/api/admin/referrals/program')
async def get_program(db=Depends(get_db), admin=Depends(require_permission('referrals.reconcile'))):
    return {'percentages': [str(x) for x in await percentages(db)], 'max_levels': 5}


@router.put('/api/admin/referrals/program')
async def set_program(payload: ProgramIn, db=Depends(get_db), admin=Depends(require_permission('referrals.reconcile'))):
    from .main import audit, set_setting
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy import text
        await db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': 1400000054})
    values = [str(x) for x in payload.percentages]
    await set_setting(db, CONFIG_KEY, json.dumps(values))
    await audit(db, 'referral.program.updated', admin.email, None, {'percentages': values})
    await db.commit()
    return {'percentages': values, 'max_levels': 5}


@router.get('/api/me/referral/network')
async def my_network(request: Request, depth: int = Query(5, ge=1, le=5), limit: int = Query(100, ge=2, le=1000), db=Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    return await network(db, user.id, depth, limit)
