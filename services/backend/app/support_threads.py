"""One ordered conversation for customer and operator interfaces."""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select

from .models import SupportMessage,SupportAttachment


async def preserve_previous_reply(db, ticket):
    """Also covers legacy imports added after migration 0043."""
    if ticket.admin_reply and not await db.scalar(select(SupportMessage.id).where(
        SupportMessage.ticket_id == ticket.id, SupportMessage.role == "admin"
    ).limit(1)):
        db.add(SupportMessage(ticket_id=ticket.id, role="admin", body=ticket.admin_reply,
                              created_at=ticket.updated_at))
        await db.flush()


async def append_message(db, ticket, role, body, key=None, attachment_ids=None, actor=None, importing=False):
    if ticket.merged_into_id:
        raise HTTPException(409, f"Обращение объединено с #{ticket.merged_into_id}; откройте итоговое обращение")
    if not importing:
        from .models import SupportImportLink
        if await db.scalar(select(SupportImportLink.source_key).where(SupportImportLink.ticket_id==ticket.id,SupportImportLink.completed.is_(False))):
            raise HTTPException(409,'Дождитесь завершения переноса истории обращения')
    attachment_ids=attachment_ids or []
    actor=actor or f"customer:{ticket.user_id}"
    # Caller holds the ticket row lock, so state changes and retry checks serialize.
    body = body.strip()
    if not body:
        raise HTTPException(400, "Сообщение не может быть пустым")
    if key is not None:
        if not 1 <= len(key) <= 128 or any(ord(c) < 32 or ord(c) > 126 for c in key):
            raise HTTPException(400, "Некорректный ключ повторной отправки")
        previous = await db.scalar(select(SupportMessage).where(
            SupportMessage.ticket_id == ticket.id, SupportMessage.role == role,
            SupportMessage.idempotency_key == key))
        if previous:
            if previous.body != body:
                raise HTTPException(409, "Этот ключ уже использован для другого сообщения")
            existing=(await db.execute(select(SupportAttachment.id).where(SupportAttachment.message_id==previous.id))).scalars().all()
            if set(existing)!=set(attachment_ids):raise HTTPException(409,"Этот ключ использован для другого набора вложений")
            return previous, False
    await preserve_previous_reply(db, ticket)
    message = SupportMessage(ticket_id=ticket.id, role=role, body=body, idempotency_key=key)
    db.add(message)
    ticket.updated_at = datetime.utcnow()
    ticket.status = "open" if role == "customer" else "resolved"
    if role == "admin":
        ticket.admin_reply = body  # Compatibility projection for older clients.
    await db.flush()
    from .support_attachments import bind
    await bind(db,ticket,message,attachment_ids,actor)
    return message, True


async def read_thread(db, ticket, after=0):
    rows = (await db.execute(select(SupportMessage).where(
        SupportMessage.ticket_id == ticket.id, SupportMessage.id > after
    ).order_by(SupportMessage.id).limit(101))).scalars().all()
    visible = rows[:100]
    messages = [{"id": x.id, "role": x.role, "body": x.body, "created_at": x.created_at} for x in visible]
    from .support_attachments import metadata
    files=(await db.execute(select(SupportAttachment).where(SupportAttachment.message_id.in_([x.id for x in visible])))).scalars().all() if visible else []
    for message in messages:message["attachments"]=[metadata(item) for item in files if item.message_id==message["id"]]
    if after == 0:
        messages.insert(0, {"id": 0, "role": "customer", "body": ticket.message, "created_at": ticket.created_at})
        # A legacy imported ticket can have no message rows until its next reply.
        if ticket.admin_reply and not rows:
            messages.append({"id": -1, "role": "admin", "body": ticket.admin_reply, "created_at": ticket.updated_at})
    return {"ticket_id": ticket.id, "subject": ticket.subject, "status": ticket.status,
            "merged_into_id": ticket.merged_into_id, "messages": messages, "next_cursor": visible[-1].id if len(rows) > 100 else None}
