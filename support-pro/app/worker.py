"""Durable outbound queue, inbound attachments, SLA warnings and assignment."""
import asyncio
import logging
import os
import time
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramServerError
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, or_, update

from .db import Session, engine
from .models import Message, Ticket, Attachment, Operator, Notification, WorkItem, now
from .services import settings, notify, assign
from .jobs import tick
from .sla import utc
from .storage import new_path, checked_path, BoundedWriter, MAX_BYTES
from .realtime import publish, r

log = logging.getLogger(__name__)


def rating_keyboard(tid):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=str(n) + ' ★', callback_data=f'rate:{tid}:{n}') for n in range(1, 6)]])


async def claim_message():
    async with Session() as s:
        m = await s.scalar(select(Message).join(Ticket,Ticket.id==Message.ticket_id).where(Ticket.shop_merged_into_id.is_(None),or_(Ticket.shop_import_until_id.is_(None),Ticket.shop_import_complete.is_(True)),Message.delivery_state == 'queued',
            or_(Message.next_attempt_at.is_(None), Message.next_attempt_at <= now()))
            .order_by(Message.id).with_for_update(skip_locked=True).limit(1))
        if not m:
            return None
        m.delivery_state, m.claimed_at = 'sending', now()
        m.attempts += 1
        await s.commit()
        return m.id


async def deliver(bot, mid):
    async with Session() as s:
        m = await s.get(Message, mid)
        if not m or m.delivery_state != 'sending':
            return
        ticket = await s.get(Ticket, m.ticket_id)
        a = await s.scalar(select(Attachment).where(Attachment.message_id == mid))
        if ticket.shop_ticket_id:
            from .shop_bridge import deliver as deliver_shop, BridgeError
            try:
                await deliver_shop(s,ticket,m)
            except Exception as exc:
                m.delivery_state='failed' if m.attempts>=8 or isinstance(exc,BridgeError) else 'queued'
                m.next_attempt_at=now()+timedelta(seconds=min(3600,10*2**m.attempts))
                m.error=str(exc) if isinstance(exc,BridgeError) else 'Магазин недоступен; повтор использует прежний ключ'
                await notify(s,ticket,f'Ответ магазину в #{ticket.id}: {m.error}',f'shop-delivery:{mid}:{m.attempts}')
                await s.commit()
            await publish(ticket.id,{'type':'changed'})
            return
        if ticket.channel == 'email':
            from . import email_channel
            try:
                await email_channel.deliver(s, ticket, m, a)
            except Exception:
                log.exception('Email delivery interrupted for message %s', mid)
                m.delivery_state = 'uncertain'
                m.error = 'Отправка письма прервана; результат неизвестен. Проверьте почту перед повтором.'
            if m.delivery_state == 'sent':
                ticket = await s.scalar(select(Ticket).where(Ticket.id == m.ticket_id).with_for_update().execution_options(populate_existing=True))
                if m.sender == 'operator':
                    ticket.first_response_at = ticket.first_response_at or m.sent_at
                    latest_user = await s.scalar(select(Message).where(Message.ticket_id == ticket.id, Message.sender == 'user').order_by(Message.id.desc()).limit(1))
                    if not latest_user or utc(latest_user.created_at) <= utc(m.created_at):
                        ticket.waiting_since = None
                    if ticket.status == 'new':
                        ticket.status = 'open'
                    ticket.updated_at = now()
            elif m.delivery_state in ('failed', 'uncertain'):
                await notify(s, ticket, f'Письмо в обращении #{ticket.id}: {m.error}', f'delivery:{mid}:{m.attempts}')
            await s.commit()
            await publish(ticket.id, {'type': 'changed'})
            return
        if ticket.channel == 'web':
            ticket=await s.scalar(select(Ticket).where(Ticket.id==m.ticket_id).with_for_update().execution_options(populate_existing=True))
            m.delivery_state, m.sent_at = 'sent', now()
            if m.sender == 'operator':
                ticket.first_response_at = ticket.first_response_at or now()
                latest=await s.scalar(select(Message).where(Message.ticket_id==ticket.id,Message.sender=='user').order_by(Message.id.desc()).limit(1))
                if not latest or utc(latest.created_at)<=utc(m.created_at):ticket.waiting_since=None
                if ticket.status=='new':ticket.status='open'
                ticket.updated_at=now()
            await s.commit()
            return
        try:
            if m.text and not m.text_sent:
                body = f'Ответ поддержки по обращению #{ticket.id}:\n\n{m.text}' if m.sender == 'operator' else m.text
                sent = await bot.send_message(ticket.telegram_user_id, body,
                    reply_markup=rating_keyboard(ticket.id) if m.sender == 'system' and m.source_key == f'rating:{ticket.id}' else None)
                m.text_sent, m.telegram_message_id = True, sent.message_id
                await s.commit()  # Persist each confirmed piece before the next network call.
            if a and not m.attachment_sent:
                path = checked_path(a.path)
                file = FSInputFile(path, filename=a.filename)
                if a.content_type in ('image/jpeg', 'image/png'):
                    sent = await bot.send_photo(ticket.telegram_user_id, file, caption=f'Вложение к обращению #{ticket.id}')
                elif a.content_type == 'video/mp4':
                    sent = await bot.send_video(ticket.telegram_user_id, file, caption=f'Вложение к обращению #{ticket.id}')
                else:
                    sent = await bot.send_document(ticket.telegram_user_id, file, caption=f'Вложение к обращению #{ticket.id}')
                m.attachment_sent, m.telegram_message_id = True, sent.message_id
                await s.commit()
            m.delivery_state, m.sent_at, m.error = 'sent', now(), ''
            # Refresh under a row lock so incoming messages cannot lose their waiting flag.
            ticket = await s.scalar(select(Ticket).where(Ticket.id == m.ticket_id).with_for_update().execution_options(populate_existing=True))
            if m.sender == 'operator':
                if ticket.first_response_at is None:
                    ticket.first_response_at = m.sent_at
                # A newer incoming message still needs a response.
                latest_user = await s.scalar(select(Message).where(Message.ticket_id == ticket.id, Message.sender == 'user')
                                              .order_by(Message.id.desc()).limit(1))
                if not latest_user or utc(latest_user.created_at) <= utc(m.created_at):
                    ticket.waiting_since = None
                if ticket.status == 'new':
                    ticket.status = 'open'
                ticket.updated_at = now()
        except TelegramRetryAfter as exc:
            m.delivery_state = 'queued' if m.attempts < 5 else 'failed'
            m.next_attempt_at = now() + timedelta(seconds=exc.retry_after + 1)
            m.error = 'Telegram ограничил частоту запросов; повтор запланирован.'
        except (TelegramForbiddenError, TelegramBadRequest, ValueError) as exc:
            m.delivery_state = 'failed'
            if isinstance(exc, TelegramForbiddenError):
                m.error = 'Бот заблокирован клиентом или не имеет доступа к чату.'
            elif isinstance(exc, ValueError):
                m.error = 'Файл отсутствует или недоступен.'
            else:
                m.error = 'Telegram отклонил запрос: ' + exc.message[:300]
        except (TelegramNetworkError, TelegramServerError, asyncio.TimeoutError):
            m.delivery_state = 'uncertain'
            m.error = 'Нет подтверждения от Telegram. Сообщение могло уйти; проверьте перед повтором.'
        except Exception:
            log.exception('Delivery interrupted for message %s', mid)
            m.delivery_state = 'uncertain'
            m.error = 'Отправка прервана; результат неизвестен. Проверьте перед повтором.'
        if m.delivery_state in ('failed', 'uncertain'):
            await notify(s, ticket, f'Ответ в обращении #{ticket.id}: {m.error}', f'delivery:{mid}:{m.attempts}')
        await s.commit()
    await publish(ticket.id, {'type': 'changed'})


async def download_one(bot):
    async with Session() as s:
        a = await s.scalar(select(Attachment).where(Attachment.state == 'pending', Attachment.telegram_file_id.is_not(None))
                          .order_by(Attachment.id).with_for_update(skip_locked=True).limit(1))
        if not a:
            return False
        path = new_path(a.filename)
        try:
            file = await bot.get_file(a.telegram_file_id)
            if (file.file_size or 0) > MAX_BYTES or not file.file_path:
                raise ValueError('Превышен допустимый размер файла')
            with path.open('wb') as out:
                bounded = BoundedWriter(out)
                await bot.download_file(file.file_path, destination=bounded, timeout=60, seek=False)
            from .storage import scan_file
            await scan_file(path)
            a.path, a.size, a.state, a.error = str(path), bounded.size, 'ready', ''
        except Exception as exc:
            path.unlink(missing_ok=True)
            a.state = 'failed'
            a.error = (str(exc) if isinstance(exc, ValueError) else
                       'Telegram не отдал файл. Возможно, превышен лимит скачивания Bot API. Можно повторить загрузку.')[:500]
            ticket = await s.get(Ticket, a.ticket_id)
            await notify(s, ticket, f'Не удалось загрузить вложение в обращении #{ticket.id}')
        await s.commit()
    await publish(a.ticket_id, {'type': 'changed'})
    return True


async def maintenance():
    async with Session() as s:
        stale = (await s.scalars(select(Message).where(Message.delivery_state == 'sending', Message.claimed_at < now() - timedelta(minutes=5))
                                .with_for_update(skip_locked=True))).all()
        for m in stale:
            t = await s.get(Ticket, m.ticket_id)
            if t.shop_merged_into_id:
                m.delivery_state='uncertain';m.error='Обращение объединено; проверьте итоговую историю';continue
            m.delivery_state, m.error = ('queued', 'Повтор через API магазина с прежним ключом') if t.shop_ticket_id else ('uncertain', 'Обработчик прервался. Отправка могла состояться; проверьте перед повтором.')
            await notify(s, t, f'Неизвестен результат отправки в обращении #{t.id}', f'stale:{m.id}:{m.attempts}')
        await s.commit()
    # Page by primary key, releasing locks after each ticket.
    last_id = 0
    while True:
        async with Session() as s:
            ids = list((await s.scalars(select(Ticket.id).where(Ticket.status != 'closed', Ticket.id > last_id)
                                       .order_by(Ticket.id).limit(100))).all())
        if not ids:
            break
        for tid in ids:
            async with Session() as s:
                t = await s.scalar(select(Ticket).where(Ticket.id == tid, Ticket.status != 'closed').with_for_update())
                if not t:
                    continue
                if t.status == 'pending':
                    continue
                config = await settings(s,t.team_id)
                if t.assigned_to is None and config['auto_assign']:
                    await assign(s, t)
                deadlines = [('первый ответ', t.first_response_due if not t.first_response_at else None), ('решение', t.sla_deadline)]
                for kind, due in deadlines:
                    if not due or utc(due) > now() + timedelta(minutes=config['warning_minutes']):
                        continue
                    overdue = utc(due) < now()
                    key = f'sla:{t.id}:{kind}:{utc(due).isoformat()}:{"late" if overdue else "soon"}'
                    text = f'#{t.id}: {"просрочен" if overdue else "скоро истечёт"} срок на {kind}'
                    await notify(s, t, text, key)
                    if overdue:
                        admins = (await s.scalars(select(Operator.id).where(Operator.active.is_(True), Operator.role == 'admin'))).all()
                        for oid in admins:
                            dedupe = f'{key}:escalation:{oid}'
                            if not await s.scalar(select(Notification.id).where(Notification.dedupe_key == dedupe)):
                                s.add(Notification(operator_id=oid, ticket_id=t.id, text='Эскалация: ' + text, dedupe_key=dedupe))
                    if not await s.scalar(select(WorkItem.id).where(WorkItem.key == key)):
                        s.add(WorkItem(key=key,kind='event',event='sla.overdue' if overdue else 'sla.warning',ticket_id=t.id,payload={'ticket_id':t.id,'kind':kind}))
                await s.commit()
        last_id = ids[-1]


async def main():
    bot = Bot(os.environ['BOT_TOKEN'])
    last_maintenance = 0
    last_shop_poll = 0
    last_email_poll = 0
    last_email_purge = 0
    try:
        while True:
            try:
                await r.set('worker:heartbeat', str(time.time()), ex=180)
                if time.monotonic() - last_maintenance > 30:
                    await maintenance()
                    last_maintenance = time.monotonic()
                from . import shop_bridge
                if shop_bridge.enabled() and time.monotonic()-last_shop_poll>10:
                    try:
                        await shop_bridge.poll(Session)
                        for _ in range(10):
                            if not await shop_bridge.status_one(Session):break
                    except Exception as exc:
                        log.warning('Shop bridge cycle failed: %s',type(exc).__name__)
                        try:
                            from .models import ShopSyncState
                            async with Session() as s:
                                state=await s.get(ShopSyncState,1)
                                if state:
                                    state.error=str(exc) if isinstance(exc,shop_bridge.BridgeError) else 'Синхронизация недоступна; следующий цикл повторит прежний курсор'
                                    await s.commit()
                        except Exception:log.warning('Cannot persist shop bridge status')
                    last_shop_poll=time.monotonic()
                from . import email_channel
                if email_channel.enabled() and time.monotonic() - last_email_poll > int(os.getenv('EMAIL_POLL_SECONDS', '30')):
                    await email_channel.poll(Session)
                    last_email_poll = time.monotonic()
                if time.monotonic() - last_email_purge > 3600:
                    await email_channel.purge_expired(Session)
                    last_email_purge = time.monotonic()
                # Limit a batch so incoming downloads and deadlines are not starved.
                for _ in range(10):
                    mid = await claim_message()
                    if mid is None:
                        break
                    await deliver(bot, mid)
                for _ in range(20):
                    if not await tick(Session): break
                await download_one(bot)
            except Exception:
                log.exception('Worker cycle failed; retrying')
            await asyncio.sleep(1)
    finally:
        await bot.session.close()
        await r.aclose()
        await engine.dispose()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
