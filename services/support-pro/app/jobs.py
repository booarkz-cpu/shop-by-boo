"""Durable at-least-once webhooks and transactional rule execution."""
import hashlib, hmac, json, os, ipaddress
from urllib.parse import urlsplit
from datetime import timedelta
import httpx
from sqlalchemy import select
from .models import WorkItem, WebhookEndpoint, AutomationRule, Ticket, Operator, Notification, AuditLog, now
from .sla import set_deadlines

EVENTS = {'ticket.created','ticket.updated','message.created','message.sent','sla.overdue','sla.warning','call.created'}

def validate_rule(event, conditions, actions):
    if event not in EVENTS or not isinstance(conditions,dict) or not isinstance(actions,dict):
        raise ValueError('Неизвестное событие или неверный JSON')
    if set(conditions) - {'status','priority','channel','team_id'} or set(actions) - {'status','priority','assign_to','notify'}:
        raise ValueError('Неизвестное условие или действие')
    for key, allowed in [('status',{'new','open','pending','closed'}),('priority',{'low','normal','high','urgent'})]:
        for obj in (conditions, actions):
            if key in obj and obj[key] not in allowed: raise ValueError('Некорректное значение '+key)
    if 'assign_to' in actions and (type(actions['assign_to']) is not int or actions['assign_to'] < 1): raise ValueError('Некорректный оператор')
    if 'notify' in actions and (not isinstance(actions['notify'],str) or len(actions['notify']) > 500): raise ValueError('Уведомление: до 500 символов')


def validate_url(url):
    u = urlsplit(url)
    # Host allowlist is combined with connect-time public-IP pinning.
    allowed = set(os.getenv('WEBHOOK_ALLOWED_HOSTS','').split(','))
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.fragment or u.hostname not in allowed:
        raise ValueError('Нужен HTTPS URL с хостом из WEBHOOK_ALLOWED_HOSTS')

async def tick(session_factory):
    async with session_factory() as s:
        job = await s.scalar(select(WorkItem).where(WorkItem.state.in_(['queued','sending']), WorkItem.kind!='shop_status', WorkItem.due_at <= now())
                             .order_by(WorkItem.id).with_for_update(skip_locked=True).limit(1))
        if not job: return False
        if job.kind == 'event':
            hooks = (await s.scalars(select(WebhookEndpoint).where(WebhookEndpoint.enabled.is_(True)))).all()
            rules = (await s.scalars(select(AutomationRule).where(AutomationRule.enabled.is_(True), AutomationRule.event == job.event))).all()
            for kind, targets in [('webhook',hooks),('rule',rules)]:
                for target in targets:
                    if kind == 'webhook' and job.event not in target.events: continue
                    s.add(WorkItem(key=f'{job.id}:{kind}:{target.id}', kind=kind, event=job.event, ticket_id=job.ticket_id,
                                   target_id=target.id, payload=job.payload))
            job.state = 'done'
            await s.commit()
            return True
        if job.kind == 'rule':
            try:
                async with s.begin_nested():
                    rule = await s.get(AutomationRule, job.target_id)
                    ticket = await s.scalar(select(Ticket).where(Ticket.id == job.ticket_id).with_for_update())
                    if rule and rule.enabled and ticket:
                        validate_rule(rule.event, rule.conditions, rule.actions)
                        if all(getattr(ticket,k) == v for k,v in rule.conditions.items()):
                            s.info['automation'] = True
                            from .services import close_ticket, settings, notify
                            a = rule.actions
                            if 'assign_to' in a:
                                op = await s.get(Operator,a['assign_to'])
                                if not op or not op.active or op.team_id != ticket.team_id: raise ValueError('Оператор другой команды или недоступен')
                                ticket.assigned_to = op.id
                            if 'priority' in a and a['priority'] != ticket.priority:
                                ticket.priority = a['priority']; set_deadlines(ticket,await settings(s,ticket.team_id))
                            if 'status' in a:
                                if a['status'] == 'closed': await close_ticket(s,ticket)
                                else: ticket.status = a['status']; ticket.closed_at = None
                            if a.get('notify'): await notify(s,ticket,a['notify'],f'job:{job.id}')
                            s.add(AuditLog(action=f'Rule {rule.id} executed for event {job.key}'))
                            await s.flush()
                    job.state, job.error = 'done', ''
            except Exception as exc:
                job.attempts += 1; job.state = 'dead'; job.error = str(exc)[:500]
            finally: s.info.pop('automation',None)
            await s.commit()
            return True
        endpoint = await s.get(WebhookEndpoint,job.target_id)
        if not endpoint or not endpoint.enabled:
            job.state = 'cancelled'; await s.commit(); return True
        job.state, job.attempts, job.due_at = 'sending', job.attempts+1, now()+timedelta(minutes=2)
        await s.commit() # Lease survives worker crash; same event id is used on retry.
        status = None
        try:
            validate_url(endpoint.url)
            body = json.dumps({'id':job.key,'event':job.event,'data':job.payload},sort_keys=True,separators=(',',':')).encode()
            signature = hmac.new(endpoint.secret.encode(),body,hashlib.sha256).hexdigest()
            from .outbound import _pinned_public_http_client
            async with _pinned_public_http_client(10) as client:
                response = await client.post(endpoint.url,content=body,headers={'Content-Type':'application/json','X-Support-Signature':'sha256='+signature,'Idempotency-Key':job.key})
            status = response.status_code
            response.raise_for_status()
            job.state, job.error = 'done', ''
        except Exception as exc:
            job.state = 'dead' if job.attempts >= 8 else 'queued'
            job.error = type(exc).__name__ + ': ' + str(exc)[:300]
            job.due_at = now()+timedelta(seconds=min(3600,2**job.attempts*10))
        endpoint.last_status, endpoint.last_error, endpoint.last_sent_at = status,job.error,now()
        await s.commit()
    return True
