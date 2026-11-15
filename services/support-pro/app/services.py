import copy
from sqlalchemy import select, func
from .models import Operator, Ticket, Settings, Notification, Message, Holiday, AutomationRule, Team, now
from .sla import DEFAULTS, set_deadlines

STATUSES = {'new': 'Новое', 'open': 'В работе', 'pending': 'Ждём клиента', 'closed': 'Закрыто'}
PRIORITIES = {'low': 'Низкий', 'normal': 'Обычный', 'high': 'Высокий', 'urgent': 'Срочный'}
DELIVERY = {'received': 'Получено', 'internal': 'Внутренняя заметка', 'queued': 'В очереди',
            'sending': 'Отправляется', 'sent': 'Отправлено в Telegram', 'failed': 'Ошибка',
            'uncertain': 'Результат неизвестен', 'legacy': 'Старое сообщение: отправка не подтверждена'}


async def settings(s, team_id=None):
    row = await s.get(Settings, 1)
    result = copy.deepcopy(row.data if row else DEFAULTS)
    result.setdefault('holidays', [])
    if team_id:
        team = await s.get(Team,team_id)
        if team: result.update(copy.deepcopy(team.calendar))
    days = (await s.scalars(select(Holiday))).all()
    result['exceptions'] = {h.day.date().isoformat():h.is_working for h in days} | result.get('exceptions',{})
    return result



async def notify(s, ticket, text, key=None):
    if ticket.assigned_to:
        ids = [ticket.assigned_to]
    else:
        ids = list((await s.scalars(select(Operator.id).where(Operator.active.is_(True), Operator.team_id == ticket.team_id))).all())
    for oid in ids:
        dedupe = f'{key}:{oid}' if key else None
        if dedupe and await s.scalar(select(Notification.id).where(Notification.dedupe_key == dedupe)):
            continue
        s.add(Notification(operator_id=oid, ticket_id=ticket.id, text=text, dedupe_key=dedupe))


async def assign(s, ticket):
    # Lock operators in a stable order. All callers lock ticket/client before operators.
    ops = list((await s.scalars(select(Operator).where(Operator.active.is_(True), Operator.available.is_(True))
                              .order_by(Operator.id).with_for_update())).all())
    loads = dict((await s.execute(select(Ticket.assigned_to, func.count()).where(Ticket.status != 'closed')
                                 .group_by(Ticket.assigned_to))).all())
    eligible = [o for o in ops if o.role in ('admin','manager','senior_operator','operator') and o.team_id == ticket.team_id and o.capacity > 0 and loads.get(o.id,0) < o.capacity]
    if eligible:
        op = min(eligible, key=lambda o: (loads.get(o.id, 0) / o.capacity, loads.get(o.id, 0), o.id))
        ticket.assigned_to = op.id
        await notify(s, ticket, f'Вам назначено обращение #{ticket.id}')


async def create_ticket(s, client, subject, priority='normal', team_id=None, channel='telegram'):
    ticket = Ticket(team_id=team_id,channel=channel,telegram_user_id=client.telegram_user_id, username=client.username,
                    full_name=client.full_name, subject=subject[:255], priority=priority,
                    created_at=now(), updated_at=now(), status='new', waiting_since=now())
    config = await settings(s,team_id)
    set_deadlines(ticket, config)
    s.add(ticket)
    await s.flush()
    if config['auto_assign']:
        await assign(s, ticket)
    client.current_ticket_id = ticket.id
    return ticket


async def close_ticket(s, ticket):
    if ticket.status != 'closed':
        ticket.status = 'closed'
        ticket.closed_at = now()
        ticket.updated_at = now()
    if not ticket.rating_requested:
        s.add(Message(ticket_id=ticket.id, sender='system', text=f'Обращение #{ticket.id} закрыто. Оцените поддержку:',
                      delivery_state='queued', source_key=f'rating:{ticket.id}'))
        ticket.rating_requested = True
