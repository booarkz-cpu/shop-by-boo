from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULTS = {
    'timezone': 'UTC', 'workdays': [0, 1, 2, 3, 4], 'start_hour': 9, 'end_hour': 18,
    'auto_assign': True, 'warning_minutes': 30,
    'response_minutes': {'low': 240, 'normal': 120, 'high': 60, 'urgent': 15},
    'resolution_minutes': {'low': 2160, 'normal': 1080, 'high': 540, 'urgent': 120},
}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def validate(config):
    ZoneInfo(config['timezone'])
    if not config['workdays'] or any(d not in range(7) for d in config['workdays']):
        raise ValueError('Выберите рабочие дни')
    if not 0 <= config['start_hour'] < config['end_hour'] <= 24:
        raise ValueError('Рабочие часы должны быть в диапазоне 0–24')
    if not 1 <= config['warning_minutes'] <= 1440:
        raise ValueError('Предупреждение: от 1 до 1440 минут')
    for key in ('response_minutes', 'resolution_minutes'):
        if set(config[key]) != {'low', 'normal', 'high', 'urgent'}:
            raise ValueError('Нужны сроки для четырёх приоритетов')
        if any(not isinstance(v, int) or not 1 <= v <= 525600 for v in config[key].values()):
            raise ValueError('SLA: от 1 до 525600 рабочих минут')
    return config


def business_add(start, minutes, config):
    """Consume real elapsed minutes inside local work windows, including DST."""
    tz = ZoneInfo(config['timezone'])
    cursor = utc(start).astimezone(tz)
    remaining = minutes * 60
    while True:
        day = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
        opening = day + timedelta(hours=config['start_hour'])
        closing = day + timedelta(hours=config['end_hour'])
        working = config.get('exceptions',{}).get(cursor.date().isoformat(), cursor.weekday() in config['workdays'])
        if not working or cursor >= closing:
            cursor = day + timedelta(days=1)
            continue
        cursor = max(cursor, opening)
        room = (closing.astimezone(timezone.utc) - cursor.astimezone(timezone.utc)).total_seconds()
        if remaining <= room:
            return cursor.astimezone(timezone.utc) + timedelta(seconds=remaining)
        remaining -= room
        cursor = day + timedelta(days=1)


def set_deadlines(ticket, config):
    offset = (ticket.paused_seconds or 0)/60
    ticket.first_response_due = business_add(ticket.created_at, config['response_minutes'][ticket.priority]+offset, config)
    ticket.sla_deadline = business_add(ticket.created_at, config['resolution_minutes'][ticket.priority]+offset, config)


def business_seconds(start, end, config):
    """Elapsed real seconds inside working windows, including DST and exceptions."""
    tz = ZoneInfo(config['timezone'])
    cursor, end = utc(start).astimezone(tz), utc(end)
    total = 0
    while cursor.astimezone(timezone.utc) < end:
        day = cursor.replace(hour=0,minute=0,second=0,microsecond=0)
        opening = day + timedelta(hours=config['start_hour'])
        closing = day + timedelta(hours=config['end_hour'])
        working = config.get('exceptions',{}).get(day.date().isoformat(),day.weekday() in config['workdays'])
        if working:
            left=max(cursor.astimezone(timezone.utc),opening.astimezone(timezone.utc))
            right=min(end,closing.astimezone(timezone.utc))
            total+=max(0,(right-left).total_seconds())
        cursor=day+timedelta(days=1)
    return total
