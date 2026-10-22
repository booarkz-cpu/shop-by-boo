"""Operator UI of the email channel: status page, erasure and history transfer."""
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from . import main as m
from . import email_channel
from .models import ChannelIdentity, Client, EmailLink, Ticket

app = m.app


@app.get('/email')
async def email_page(request: Request, op=Depends(m.admin)):
    async with m.Session() as s:
        info = await email_channel.status(s)
        recent = (await s.scalars(select(Ticket).where(Ticket.channel == email_channel.CHANNEL).order_by(Ticket.id.desc()).limit(20))).all()
    return await m.render(request, 'email.html', op, info=info, recent=recent)


@app.post('/client/{uid}/email/erase')
async def erase(request: Request, uid: int, op=Depends(m.admin)):
    data = await m.form_data(request)
    if data.get('confirm') != 'erase':
        raise HTTPException(400, 'Подтвердите удаление данных клиента')
    async with m.Session() as s:
        client = await s.scalar(select(Client).where(Client.telegram_user_id == uid).with_for_update())
        if not client:
            raise HTTPException(404, 'Клиент не найден')
        if not await s.scalar(select(ChannelIdentity.id).where(ChannelIdentity.client_id == uid, ChannelIdentity.channel == email_channel.CHANNEL)):
            raise HTTPException(400, 'У клиента нет email-канала')
        count = await email_channel.erase_client(s, client)
        m.audit(s, op, f'email data erased for client {uid}: {count} tickets')
        await s.commit()
    return m.redirect(f'/client/{uid}')


@app.post('/client/{uid}/email/link')
async def link(request: Request, uid: int, op=Depends(m.admin)):
    data = await m.form_data(request)
    target_id = m.int_field(data, 'target', 0)
    async with m.Session() as s:
        source = await s.scalar(select(Client).where(Client.telegram_user_id == uid).with_for_update())
        target = await s.scalar(select(Client).where(Client.telegram_user_id == target_id).with_for_update())
        if not source or not target:
            raise HTTPException(404, 'Клиент не найден')
        try:
            moved = await email_channel.link_client(s, source, target)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        m.audit(s, op, f'email client {uid} linked to {target_id}: {moved} tickets moved')
        await s.commit()
    return m.redirect(f'/client/{target_id}')


async def context_for_client(s, uid: int) -> list:
    return (await s.scalars(select(ChannelIdentity).where(ChannelIdentity.client_id == uid).order_by(ChannelIdentity.id))).all()


async def context_for_ticket(s, ticket) -> dict | None:
    if ticket.channel != email_channel.CHANNEL:
        return None
    identity = await s.scalar(select(ChannelIdentity).where(ChannelIdentity.client_id == ticket.telegram_user_id, ChannelIdentity.channel == email_channel.CHANNEL))
    last_in = await s.scalar(select(EmailLink).where(EmailLink.ticket_id == ticket.id, EmailLink.direction == 'in').order_by(EmailLink.id.desc()).limit(1))
    return {'address': identity.address if identity else '', 'auth': last_in.auth if last_in else 'none', 'outbound': email_channel.sending_enabled()}
