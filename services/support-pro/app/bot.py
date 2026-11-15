import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from .db import Session, engine
from .models import Client, Ticket, Message, Attachment, now
from .services import create_ticket, close_ticket, notify, STATUSES, PRIORITIES
from .storage import safe_name, MAX_BYTES
from .realtime import publish, r

bot = Bot(os.environ['BOT_TOKEN'])
dp = Dispatcher()
# Support is private: never expose or create support tickets from group messages.
dp.message.filter(F.chat.type == 'private')
dp.callback_query.filter(F.message.chat.type == 'private')


def ticket_keyboard(tid):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Закрыть обращение', callback_data=f'close:{tid}')]])


async def get_client(s, user):
    insert = pg_insert if s.bind.dialect.name == 'postgresql' else sqlite_insert
    await s.execute(insert(Client).values(telegram_user_id=user.id, full_name=user.full_name[:255],
                                         username=user.username or '', tags='', notes='').on_conflict_do_nothing(index_elements=['telegram_user_id']))
    c = await s.scalar(select(Client).where(Client.telegram_user_id == user.id).with_for_update())
    c.full_name, c.username = user.full_name[:255], user.username or ''
    return c


async def select_ticket(s, client, message):
    if message.reply_to_message:
        ref = message.reply_to_message.message_id
        previous = await s.scalar(select(Message).join(Ticket, Ticket.id == Message.ticket_id).where(
            Ticket.telegram_user_id == client.telegram_user_id,
            or_(Message.source_key == f'tg:{client.telegram_user_id}:{ref}', Message.telegram_message_id == ref))
            .order_by(Message.id.desc()).limit(1))
        if previous:
            t = await s.scalar(select(Ticket).where(Ticket.id == previous.ticket_id).with_for_update())
            if t.status != 'closed':
                return t
    if client.current_ticket_id:
        t = await s.scalar(select(Ticket).where(Ticket.id == client.current_ticket_id,
            Ticket.telegram_user_id == client.telegram_user_id, Ticket.status != 'closed').with_for_update())
        if t:
            return t
    t = await s.scalar(select(Ticket).where(Ticket.telegram_user_id == client.telegram_user_id, Ticket.status != 'closed')
                       .order_by(Ticket.id.desc()).with_for_update().limit(1))
    return t or await create_ticket(s, client, message.text or message.caption or 'Вложение')


@dp.message(CommandStart())
async def start(m):
    await m.answer('Поддержка готова. Отправьте сообщение, фото, видео, голосовое или документ.\n'
                   '/new тема — отдельный вопрос\n/tickets — выбрать обращение\n/status — текущий статус\n/help — команды')


@dp.message(Command('help'))
async def help_command(m):
    await start(m)


@dp.message(Command('new'))
async def new_ticket(m):
    subject = (m.text.split(maxsplit=1)[1] if len(m.text.split(maxsplit=1)) > 1 else 'Новый вопрос')[:255]
    async with Session() as s:
        c = await get_client(s, m.from_user)
        # Command deduplication survives Telegram update redelivery.
        source_key = f'tg:{m.from_user.id}:{m.message_id}'
        old = await s.scalar(select(Message).where(Message.source_key == source_key))
        if old:
            tid = old.ticket_id
        else:
            t = await create_ticket(s, c, subject)
            msg = Message(ticket_id=t.id, sender='user', text=subject, source_key=source_key)
            s.add(msg)
            await s.flush()
            t.last_customer_message_id = msg.id
            await notify(s, t, f'Новое обращение #{t.id}', f'incoming:{msg.id}')
            tid = t.id
        await s.commit()
    await m.answer(f'Создано обращение #{tid}. Следующие сообщения пойдут в него.', reply_markup=ticket_keyboard(tid))


@dp.message(Command('status'))
async def status(m):
    async with Session() as s:
        c = await s.get(Client, m.from_user.id)
        t = await s.get(Ticket, c.current_ticket_id) if c and c.current_ticket_id else None
        if not t or t.status == 'closed':
            t = await s.scalar(select(Ticket).where(Ticket.telegram_user_id == m.from_user.id, Ticket.status != 'closed').order_by(Ticket.id.desc()).limit(1))
    await m.answer(f'#{t.id}: {STATUSES[t.status]} / {PRIORITIES[t.priority]}' if t else 'Открытых обращений нет.')


async def ticket_list(user_id, page=0):
    async with Session() as s:
        rows = (await s.scalars(select(Ticket).where(Ticket.telegram_user_id == user_id, Ticket.status != 'closed')
                               .order_by(Ticket.id.desc()).offset(page * 5).limit(6))).all()
    buttons = [[InlineKeyboardButton(text=f'#{t.id} · {t.subject[:45]}', callback_data=f'use:{t.id}')] for t in rows[:5]]
    navigation = []
    if page:
        navigation.append(InlineKeyboardButton(text='←', callback_data=f'list:{page - 1}'))
    if len(rows) > 5:
        navigation.append(InlineKeyboardButton(text='→', callback_data=f'list:{page + 1}'))
    if navigation:
        buttons.append(navigation)
    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None


@dp.message(Command('tickets'))
async def tickets(m):
    keyboard = await ticket_list(m.from_user.id)
    await m.answer('Выберите обращение для следующих сообщений:' if keyboard else 'Открытых обращений нет.', reply_markup=keyboard)


@dp.callback_query(F.data.startswith('list:'))
async def list_page(c):
    try:
        page = max(0, min(100000, int(c.data.split(':')[1])))
    except ValueError:
        return await c.answer('Некорректная страница')
    keyboard = await ticket_list(c.from_user.id, page)
    await c.message.edit_text('Выберите обращение:' if keyboard else 'Обращений нет.', reply_markup=keyboard)
    await c.answer()


@dp.callback_query(F.data.startswith('use:'))
async def use_ticket(c):
    try:
        tid = int(c.data.split(':')[1])
    except ValueError:
        return await c.answer('Некорректный номер')
    async with Session() as s:
        client = await get_client(s, c.from_user)
        t = await s.get(Ticket, tid)
        if not t or t.telegram_user_id != c.from_user.id or t.status == 'closed':
            return await c.answer('Обращение недоступно', show_alert=True)
        client.current_ticket_id = tid
        await s.commit()
    await c.message.answer(f'Выбрано обращение #{tid}.', reply_markup=ticket_keyboard(tid))
    await c.answer()


@dp.callback_query(F.data.startswith('close:'))
async def close(c):
    try:
        tid = int(c.data.split(':')[1])
    except ValueError:
        return await c.answer('Некорректный номер')
    async with Session() as s:
        t = await s.scalar(select(Ticket).where(Ticket.id == tid).with_for_update())
        if not t or t.telegram_user_id != c.from_user.id:
            return await c.answer('Нет доступа', show_alert=True)
        await close_ticket(s, t)
        await notify(s, t, f'Клиент закрыл обращение #{tid}', f'client-close:{tid}')
        await s.commit()
    await publish(tid, {'type': 'changed'})
    await c.answer('Обращение закрыто')


@dp.callback_query(F.data.startswith('rate:'))
async def rate(c):
    try:
        _, tid, score = c.data.split(':')
        tid, score = int(tid), int(score)
    except ValueError:
        return await c.answer('Некорректная оценка')
    async with Session() as s:
        t = await s.scalar(select(Ticket).where(Ticket.id == tid).with_for_update())
        if not t or t.telegram_user_id != c.from_user.id or t.status != 'closed' or not t.rating_requested or score not in range(1, 6):
            return await c.answer('Оценка недоступна', show_alert=True)
        if t.rating is not None:
            return await c.answer('Оценка уже сохранена')
        t.rating = score
        await s.commit()
    await c.message.edit_text(f'Спасибо! Ваша оценка обращения #{tid}: {score}/5')
    await c.answer()


async def receive(m):
    async with Session() as s:
        client = await get_client(s, m.from_user)
        source = f'tg:{m.from_user.id}:{m.message_id}'
        old = await s.scalar(select(Message).where(Message.source_key == source))
        if old:
            return old.ticket_id
        t = await select_ticket(s, client, m)
        client.current_ticket_id = t.id
        media, filename, mime = None, 'attachment', 'application/octet-stream'
        if m.photo:
            media, filename, mime = m.photo[-1], 'photo.jpg', 'image/jpeg'
        else:
            for kind, default, default_mime in [('document', 'document', 'application/octet-stream'),
                    ('video', 'video.mp4', 'video/mp4'), ('voice', 'voice.ogg', 'audio/ogg'),
                    ('audio', 'audio.mp3', 'audio/mpeg'), ('video_note', 'video_note.mp4', 'video/mp4'),
                    ('animation', 'animation.mp4', 'video/mp4'), ('sticker', 'sticker.webp', 'image/webp')]:
                media = getattr(m, kind, None)
                if media:
                    filename = getattr(media, 'file_name', None) or default
                    mime = getattr(media, 'mime_type', None) or default_mime
                    break
        text = m.text or m.caption or ('[вложение]' if media else '[неподдерживаемый тип сообщения]')
        message = Message(ticket_id=t.id, sender='user', text=text, source_key=source)
        s.add(message)
        await s.flush()
        if media:
            too_big = (media.file_size or 0) > MAX_BYTES
            s.add(Attachment(ticket_id=t.id, message_id=message.id, filename=safe_name(filename), path='',
                content_type=mime, size=media.file_size or 0, telegram_file_id=media.file_id,
                state='failed' if too_big else 'pending', error='Превышен допустимый размер файла' if too_big else ''))
        t.last_customer_message_id = message.id
        t.updated_at = now()
        if not t.waiting_since:
            t.waiting_since = now()
        if t.status == 'pending':
            t.status = 'open'
        await notify(s, t, f'Новое сообщение в обращении #{t.id}', f'incoming:{message.id}')
        await s.commit()
    await publish(t.id, {'type': 'changed'})
    return t.id


@dp.message()
async def incoming(m):
    tid = await receive(m)
    await m.answer(f'Сообщение принято в обращение #{tid}.', reply_markup=ticket_keyboard(tid))


async def main():
    try:
        # Sequential ingestion makes acknowledgement order deterministic. DB locking also protects retries.
        await dp.start_polling(bot, handle_as_tasks=False)
    finally:
        await bot.session.close()
        await engine.dispose()
        await r.aclose()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
