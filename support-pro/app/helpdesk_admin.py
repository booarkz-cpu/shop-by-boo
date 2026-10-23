"""Operator UI of the external helpdesk bridge: status, manual sync and client erasure."""
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from . import main as m
from . import helpdesk_bridge
from .models import ChannelIdentity, Client, HelpdeskLink, Ticket

app = m.app


@app.get('/helpdesk')
async def helpdesk_page(request: Request, op=Depends(m.admin)):
    async with m.Session() as s:
        info = await helpdesk_bridge.status(s)
        recent = (await s.scalars(select(Ticket).where(Ticket.channel.in_(helpdesk_bridge.PROVIDERS)).order_by(Ticket.updated_at.desc()).limit(20))).all()
    return await m.render(request, 'helpdesk.html', op, info=info, recent=recent, result=request.query_params.get('result', ''))


@app.post('/helpdesk/sync')
async def helpdesk_sync(request: Request, op=Depends(m.admin)):
    await m.form_data(request)
    if not helpdesk_bridge.enabled():
        raise HTTPException(400, 'Мост не настроен: задайте HELPDESK_PROVIDER и ключ API в окружении Support Pro')
    result = await helpdesk_bridge.poll(m.Session)
    async with m.Session() as s:
        m.audit(s, op, f'helpdesk sync started manually: {result}')
        await s.commit()
    summary = result.get('error') or f"новых обращений {result.get('tickets', 0)}, сообщений {result.get('comments', 0)}"
    return m.redirect('/helpdesk?result=' + summary)


@app.post('/client/{uid}/helpdesk/erase')
async def helpdesk_erase(request: Request, uid: int, op=Depends(m.admin)):
    data = await m.form_data(request)
    if data.get('confirm') != 'erase':
        raise HTTPException(400, 'Подтвердите удаление данных клиента')
    async with m.Session() as s:
        client = await s.scalar(select(Client).where(Client.telegram_user_id == uid).with_for_update())
        if not client:
            raise HTTPException(404, 'Клиент не найден')
        count = await helpdesk_bridge.erase_client(s, client)
        if not count:
            raise HTTPException(400, 'У клиента нет обращений из внешнего helpdesk')
        m.audit(s, op, f'helpdesk data erased for client {uid}: {count} tickets')
        await s.commit()
    return m.redirect(f'/client/{uid}')


async def context_for_ticket(s, ticket) -> dict | None:
    if ticket.channel not in helpdesk_bridge.PROVIDERS:
        return None
    link = await s.scalar(select(HelpdeskLink).where(HelpdeskLink.ticket_id == ticket.id, HelpdeskLink.kind == 'ticket'))
    identity = await s.scalar(select(ChannelIdentity).where(ChannelIdentity.client_id == ticket.telegram_user_id, ChannelIdentity.channel == ticket.channel))
    return {'provider': ticket.channel, 'external_id': link.external_id if link else '', 'erased': bool(link and link.erased),
            'url': helpdesk_bridge.external_url(ticket.channel, link.external_id) if link and not link.erased else '',
            'address': identity.address if identity else '', 'configured': helpdesk_bridge.enabled() and helpdesk_bridge.provider() == ticket.channel}
