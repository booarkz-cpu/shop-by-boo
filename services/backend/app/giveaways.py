"""Free promotional rewards; all outcomes and wallet credits are server-owned."""
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import FinancialLedger, Giveaway, GiveawayEntry, Subscription, User
from .security import require_permission

router = APIRouter()


class PrizeIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    amount: Decimal = Field(ge=0, le=10000, max_digits=12, decimal_places=2)
    weight: int = Field(default=1, ge=1, le=10000, strict=True)


class GiveawayIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default='', max_length=4000)
    kind: str = Field(pattern='^(contest|wheel)$')
    starts_at: datetime
    ends_at: datetime
    max_entries: int = Field(default=1000, ge=1, le=10000, strict=True)
    winners_count: int = Field(default=1, ge=1, le=100, strict=True)
    prizes: list[PrizeIn] = Field(min_length=1, max_length=20)
    require_subscription: bool = False

    @field_validator('title')
    @classmethod
    def clean_title(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Название не может быть пустым')
        return value

    @field_validator('starts_at', 'ends_at')
    @classmethod
    def utc(cls, value):
        if value.tzinfo is None:
            raise ValueError('Укажите часовой пояс даты')
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    @model_validator(mode='after')
    def policy(self):
        if not timedelta(0) < self.ends_at - self.starts_at <= timedelta(days=366):
            raise ValueError('Срок акции должен быть от 1 секунды до 366 дней')
        if self.kind == 'contest':
            if len(self.prizes) != 1 or self.prizes[0].amount <= 0 or self.prizes[0].weight != 1:
                raise ValueError('Конкурс использует одну положительную награду с весом 1')
            if self.winners_count > self.max_entries:
                raise ValueError('Число победителей превышает лимит участников')
        elif self.winners_count != 1:
            raise ValueError('Для колеса winners_count должен быть равен 1')
        if self.budget() > Decimal('1000000'):
            raise ValueError('Бюджет превышает 1 000 000')
        if not any(p.amount > 0 for p in self.prizes):
            raise ValueError('Добавьте хотя бы одну положительную награду')
        return self

    def budget(self):
        return (self.prizes[0].amount * self.winners_count if self.kind == 'contest'
                else max(p.amount for p in self.prizes) * self.max_entries)


def phase(row):
    if row.state != 'published':
        return row.state
    now = datetime.utcnow()
    if now >= row.ends_at:
        return 'ended'
    if now < row.starts_at:
        return 'scheduled'
    if row.entry_count >= row.max_entries:
        return 'full'
    return 'open'


def public(row, own=None, admin=False):
    result = dict(id=row.id, title=row.title, description=row.description, kind=row.kind,
                  state=row.state, phase=phase(row), prizes=row.prizes, currency=row.currency,
                  starts_at=row.starts_at.replace(tzinfo=timezone.utc),
                  ends_at=row.ends_at.replace(tzinfo=timezone.utc), max_entries=row.max_entries,
                  entry_count=row.entry_count, winners_count=row.winners_count,
                  require_verified_email=True, require_subscription=row.require_subscription,
                  drawn_at=row.drawn_at.replace(tzinfo=timezone.utc) if row.drawn_at else None,
                  my_entry=None if own is None else dict(id=own.id, outcome=own.outcome,
                      reward_amount=format(own.reward_amount, '.2f'), prize_index=own.prize_index))
    if admin:
        result.update(budget_limit=format(row.budget_limit, '.2f'), budget_credited=format(row.budget_credited, '.2f'))
    return result


async def locked(db, giveaway_id):
    row = await db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id)
                          .execution_options(populate_existing=True).with_for_update())
    if not row:
        raise HTTPException(404, 'Акция не найдена')
    return row


async def credit(db, row, entry, user, amount, prize_index):
    from .main import record_financial_event, enqueue_notification
    key = f'giveaway:{row.id}:entry:{entry.id}:reward'
    if await db.scalar(select(FinancialLedger.id).where(FinancialLedger.operation_key == key)):
        raise HTTPException(409, 'Награда уже зафиксирована; требуется сверка')
    if row.budget_credited + amount > row.budget_limit:
        raise HTTPException(409, 'Бюджет акции исчерпан')
    entry.prize_index = prize_index
    entry.reward_amount = amount
    entry.outcome = 'won' if amount > 0 else 'lost'
    if amount == 0:
        return
    user.wallet_balance = (Decimal(user.wallet_balance or 0) + amount).quantize(Decimal('.01'))
    row.budget_credited += amount
    await record_financial_event(db, operation_key=key, user_id=user.id, payment_id=None,
        kind='giveaway_reward', direction='credit', amount=amount, currency=row.currency,
        metadata={'giveaway_id': row.id, 'entry_id': entry.id, 'prize_index': prize_index})
    await enqueue_notification(db, user_id=user.id, channel='in_app', kind='giveaway_reward',
        title='Награда за участие', body=f'Начислено {amount} {row.currency} на баланс магазина.',
        dedupe_key=f'giveaway:{row.id}:entry:{entry.id}')


@router.get('/api/admin/giveaways')
async def admin_list(before: int = Query(default=0, ge=0), db: AsyncSession = Depends(get_db),
                     admin=Depends(require_permission('marketing.read'))):
    rows = (await db.scalars(select(Giveaway).where(Giveaway.id < before if before else Giveaway.id > 0)
                            .order_by(Giveaway.id.desc()).limit(200))).all()
    return [public(row, admin=True) for row in rows]


@router.post('/api/admin/giveaways')
async def create(payload: GiveawayIn, db: AsyncSession = Depends(get_db),
                 admin=Depends(require_permission('manage_marketing'))):
    from .main import audit
    data = payload.model_dump(exclude={'prizes'})
    data['prizes'] = [{'amount': str(p.amount), 'weight': p.weight} for p in payload.prizes]
    row = Giveaway(**data, currency=settings.default_currency, budget_limit=payload.budget())
    db.add(row)
    await db.flush()
    await audit(db, 'giveaway.created', admin.email, str(row.id))
    await db.commit()
    return public(row, admin=True)


@router.post('/api/admin/giveaways/{giveaway_id}/publish')
async def publish(giveaway_id: int, db: AsyncSession = Depends(get_db),
                  admin=Depends(require_permission('manage_marketing'))):
    from .main import audit
    row = await locked(db, giveaway_id)
    if row.state == 'published':
        return public(row, admin=True)
    if row.state != 'draft' or row.ends_at <= datetime.utcnow():
        raise HTTPException(409, 'Эту акцию нельзя опубликовать')
    if row.currency != settings.default_currency:
        raise HTTPException(409, 'Валюта магазина изменилась; создайте новую акцию')
    row.state = 'published'
    await audit(db, 'giveaway.published', admin.email, str(row.id),
                {'budget_limit': str(row.budget_limit), 'currency': row.currency, 'kind': row.kind})
    await db.commit()
    return public(row, admin=True)


@router.post('/api/admin/giveaways/{giveaway_id}/close')
async def close(giveaway_id: int, db: AsyncSession = Depends(get_db),
                admin=Depends(require_permission('manage_marketing'))):
    from .main import audit
    row = await locked(db, giveaway_id)
    if row.state in {'closed', 'drawn'}:
        return public(row, admin=True)
    row.state = 'closed'
    await audit(db, 'giveaway.closed', admin.email, str(row.id))
    await db.commit()
    return public(row, admin=True)


@router.delete('/api/admin/giveaways/{giveaway_id}')
async def delete_draft(giveaway_id: int, db: AsyncSession = Depends(get_db),
                       admin=Depends(require_permission('manage_marketing'))):
    from .main import audit
    row = await locked(db, giveaway_id)
    if row.state != 'draft' or row.entry_count:
        raise HTTPException(409, 'Удаляется только черновик без участников')
    await db.delete(row)
    await audit(db, 'giveaway.deleted', admin.email, str(giveaway_id))
    await db.commit()
    return {'ok': True}


@router.post('/api/admin/giveaways/{giveaway_id}/draw')
async def draw(giveaway_id: int, db: AsyncSession = Depends(get_db),
               admin=Depends(require_permission('manage_marketing'))):
    from .main import audit, maintenance_enabled
    row = await locked(db, giveaway_id)
    if row.kind != 'contest':
        raise HTTPException(409, 'Колесо определяет награду при участии')
    if row.state == 'drawn':
        return public(row, admin=True)
    # A manual early close cancels a contest; it cannot accelerate a promised draw.
    if row.state != 'published' or datetime.utcnow() < row.ends_at:
        raise HTTPException(409, 'Розыгрыш возможен только после объявленного окончания конкурса')
    if await maintenance_enabled(db):
        raise HTTPException(503, 'Магазин на обслуживании')
    if row.currency != settings.default_currency:
        raise HTTPException(409, 'Валюта награды недоступна')
    # Lock order is giveaway -> users (ascending). Entries are changed only after
    # user locks, so account deletion can anonymize participation without a cycle.
    users = (await db.scalars(select(User).join(GiveawayEntry, GiveawayEntry.user_id == User.id)
        .where(GiveawayEntry.giveaway_id == row.id).order_by(User.id)
        .execution_options(populate_existing=True).with_for_update(of=User))).all()
    eligible = {u.id: u for u in users if not u.deleted_at and not u.restricted_at}
    entries = (await db.scalars(select(GiveawayEntry).where(GiveawayEntry.giveaway_id == row.id)
                               .execution_options(populate_existing=True).order_by(GiveawayEntry.id))).all()
    candidates = [e for e in entries if e.user_id in eligible]
    winners = secrets.SystemRandom().sample(candidates, min(row.winners_count, len(candidates)))
    winner_ids = {e.id for e in winners}
    for entry in entries:
        if entry.id in winner_ids:
            await credit(db, row, entry, eligible[entry.user_id], Decimal(row.prizes[0]['amount']), 0)
        else:
            entry.outcome = 'lost' if entry.user_id in eligible else 'ineligible'
    row.state = 'drawn'
    row.drawn_at = datetime.utcnow()
    await audit(db, 'giveaway.drawn', admin.email, str(row.id),
                {'winner_entries': sorted(winner_ids), 'eligible_count': len(candidates),
                 'budget_credited': str(row.budget_credited)})
    await db.commit()
    return public(row, admin=True)


@router.get('/api/admin/giveaways/{giveaway_id}/entries')
async def entries(giveaway_id: int, after: int = Query(default=0, ge=0),
                  db: AsyncSession = Depends(get_db), admin=Depends(require_permission('manage_marketing'))):
    if not await db.get(Giveaway, giveaway_id):
        raise HTTPException(404, 'Акция не найдена')
    rows = (await db.scalars(select(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway_id,
        GiveawayEntry.id > after).order_by(GiveawayEntry.id).limit(101))).all()
    return {'items': [{'id': e.id, 'user_id': e.user_id, 'outcome': e.outcome,
                      'reward_amount': str(e.reward_amount), 'created_at': e.created_at} for e in rows[:100]],
            'next_after': rows[99].id if len(rows) > 100 else None}


@router.get('/api/me/giveaways')
async def customer_list(request: Request, response: Response, after: int = Query(default=0, ge=0),
                        db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    rows = (await db.scalars(select(Giveaway).where(Giveaway.state != 'draft', Giveaway.id > after)
                            .order_by(Giveaway.id).limit(51))).all()
    own = (await db.scalars(select(GiveawayEntry).where(GiveawayEntry.user_id == user.id,
                           GiveawayEntry.giveaway_id.in_([r.id for r in rows])))).all()
    by_id = {e.giveaway_id: e for e in own}
    response.headers['Cache-Control'] = 'private, no-store'
    return {'items': [public(row, by_id.get(row.id)) for row in rows[:50]],
            'next_after': rows[49].id if len(rows) > 50 else None}


@router.post('/api/me/giveaways/{giveaway_id}/enter')
async def enter(giveaway_id: int, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token, audit, maintenance_enabled
    from .platform_api import reject_restricted
    user = await user_from_token(request, db)
    row = await locked(db, giveaway_id)
    if row.state == 'draft':
        raise HTTPException(404, 'Акция не найдена')
    user = await db.scalar(select(User).where(User.id == user.id)
                           .execution_options(populate_existing=True).with_for_update())
    if not user or user.deleted_at:
        raise HTTPException(401, 'Аккаунт недоступен')
    reject_restricted(user)
    response.headers['Cache-Control'] = 'private, no-store'
    own = await db.scalar(select(GiveawayEntry).where(GiveawayEntry.giveaway_id == row.id,
                                                    GiveawayEntry.user_id == user.id))
    if own:
        return public(row, own)
    if await maintenance_enabled(db):
        raise HTTPException(503, 'Магазин на обслуживании')
    if phase(row) != 'open':
        raise HTTPException(409, 'Акция ещё не началась, завершена или достигла лимита')
    if not user.email or not user.email_verified_at:
        raise HTTPException(403, 'Сначала подтвердите email')
    if row.require_subscription and not await db.scalar(select(Subscription.id).where(
        Subscription.user_id == user.id, Subscription.lifecycle_status.in_(('active', 'cancel_scheduled')),
        Subscription.expires_at > datetime.utcnow()).limit(1)):
        raise HTTPException(403, 'Для участия нужна действующая подписка')
    if row.currency != settings.default_currency:
        raise HTTPException(409, 'Валюта награды недоступна')
    own = GiveawayEntry(giveaway_id=row.id, user_id=user.id)
    db.add(own)
    await db.flush()
    row.entry_count += 1
    if row.kind == 'wheel':
        # Integer tickets avoid float bias and client-controlled outcomes.
        ticket = secrets.randbelow(sum(p['weight'] for p in row.prizes))
        for index, prize in enumerate(row.prizes):
            ticket -= prize['weight']
            if ticket < 0:
                await credit(db, row, own, user, Decimal(prize['amount']), index)
                break
    await audit(db, 'giveaway.entered', f'user:{user.id}', str(row.id),
                {'entry_id': own.id, 'outcome': own.outcome, 'reward': str(own.reward_amount)})
    await db.commit()
    return public(row, own)


async def anonymize(db, user_id):
    await db.execute(update(GiveawayEntry).where(GiveawayEntry.user_id == user_id).values(user_id=None))
