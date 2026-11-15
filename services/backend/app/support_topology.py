"""Previewed, atomic ticket merge/split without crossing customer boundaries."""
import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import SupportTicket, SupportMessage, SupportAttachment, SupportImportLink, SupportTopologyOperation
from .security import require_permission
from .support_threads import preserve_previous_reply

router = APIRouter(prefix='/api/admin/support/topology', tags=['support-topology'])


class OperationIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str = Field(pattern='^(merge|split)$')
    source_id: int = Field(gt=0)
    target_id: int | None = Field(default=None, gt=0)
    message_ids: list[int] = Field(default_factory=list, max_length=1000)
    subject: str = Field(default='', max_length=255)
    fingerprint: str | None = Field(default=None, min_length=64, max_length=64)


async def snapshot(db, payload, lock=False):
    ids = sorted({payload.source_id, *([payload.target_id] if payload.target_id else [])})
    statement = select(SupportTicket).where(SupportTicket.id.in_(ids)).order_by(SupportTicket.id)
    if lock:statement = statement.with_for_update().execution_options(populate_existing=True)
    tickets = {x.id: x for x in (await db.scalars(statement)).all()}
    if len(tickets) != len(ids):raise HTTPException(404, 'Обращение не найдено')
    source = tickets[payload.source_id]
    if any(x.merged_into_id for x in tickets.values()):raise HTTPException(409, 'Обращение уже объединено; откройте итоговое обращение')
    if await db.scalar(select(SupportImportLink.source_key).where(SupportImportLink.ticket_id.in_(ids), SupportImportLink.completed.is_(False))):
        raise HTTPException(409, 'Дождитесь окончания переноса истории')
    if payload.kind == 'merge':
        if not payload.target_id or payload.target_id == payload.source_id or payload.message_ids:
            raise HTTPException(422, 'Для объединения нужны два разных обращения без списка сообщений')
        if tickets[payload.target_id].user_id != source.user_id:
            raise HTTPException(409, 'Нельзя объединять обращения разных клиентов')
    else:
        if payload.target_id or not payload.subject.strip() or not payload.message_ids or len(set(payload.message_ids)) != len(payload.message_ids):
            raise HTTPException(422, 'Для разделения нужны тема и разные ID сообщений')
    messages = (await db.scalars(select(SupportMessage).where(SupportMessage.ticket_id.in_(ids)).order_by(SupportMessage.id))).all()
    if payload.kind == 'split' and set(payload.message_ids) - {m.id for m in messages if m.ticket_id == source.id}:
        raise HTTPException(404, 'Сообщения не принадлежат исходному обращению')
    files = (await db.scalars(select(SupportAttachment).where(SupportAttachment.ticket_id.in_(ids)).order_by(SupportAttachment.id))).all()
    content = {'kind': payload.kind, 'source_id': source.id, 'target_id': payload.target_id,
        'subject': payload.subject.strip(), 'message_ids': sorted(payload.message_ids),
        'tickets': [[x.id, x.user_id, x.status, x.subject, x.message, x.admin_reply, str(x.updated_at)] for x in tickets.values()],
        'messages': [[m.id, m.ticket_id, m.role, m.body, m.idempotency_key] for m in messages],
        'attachments': [[f.id, f.ticket_id, f.message_id, f.actor, f.sha256] for f in files]}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return tickets, messages, files, digest


@router.post('/preview')
async def preview(payload: OperationIn, db: AsyncSession = Depends(get_db),
        admin=Depends(require_permission('support.write'))):
    tickets, messages, files, digest = await snapshot(db, payload)
    moving = [m.id for m in messages if m.ticket_id == payload.source_id and
        (payload.kind == 'merge' or m.id in payload.message_ids)]
    return {'fingerprint': digest, 'kind': payload.kind, 'source_id': payload.source_id,
        'target_id': payload.target_id, 'user_id': tickets[payload.source_id].user_id,
        'moving_messages': moving, 'moving_attachments': [f.id for f in files if
            f.ticket_id == payload.source_id and (payload.kind == 'merge' or f.message_id in moving)],
        'initial_message_copied': payload.kind == 'merge'}


def request_fingerprint(payload):
    return hashlib.sha256(json.dumps(payload.model_dump(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@router.post('/apply')
async def apply(payload: OperationIn, request: Request, db: AsyncSession = Depends(get_db),
        admin=Depends(require_permission('support.write'))):
    from .main import audit
    key = request.headers.get('Idempotency-Key', '')
    if not 1 <= len(key) <= 128 or any(ord(c) < 32 or ord(c) > 126 for c in key):
        raise HTTPException(422, 'Idempotency-Key обязателен')
    scope = hashlib.sha256((admin.email + ":" + key).encode()).hexdigest()
    if db.bind.dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(bytes.fromhex(scope)[:8], "big", signed=True)})
    # Lock source/target in numeric order; repeat lookup occurs under these locks.
    ids = sorted({payload.source_id, *([payload.target_id] if payload.target_id else [])})
    await db.scalars(select(SupportTicket).where(SupportTicket.id.in_(ids)).order_by(SupportTicket.id).with_for_update())
    previous = await db.get(SupportTopologyOperation, scope)
    if previous:
        if previous.fingerprint != request_fingerprint(payload):raise HTTPException(409, 'Ключ использован для другой операции')
        return previous.result
    tickets, messages, files, digest = await snapshot(db, payload, True)
    if payload.fingerprint != digest:raise HTTPException(409, 'История изменилась; обновите preview')
    source = tickets[payload.source_id]
    await preserve_previous_reply(db, source)
    if payload.kind == 'merge':
        target = tickets[payload.target_id]
        await preserve_previous_reply(db, target)
        # Keep the original root text and timestamp as a real message before
        # archiving the source. Attachment IDs remain stable after relocation.
        db.add(SupportMessage(ticket_id=target.id, role='customer',
            body=f'Обращение #{source.id}: {source.subject}\n\n{source.message}', created_at=source.created_at))
        messages = (await db.scalars(select(SupportMessage).where(SupportMessage.ticket_id == source.id))).all()
        source.merged_into_id = target.id
        source.status = 'merged'
    else:
        target = SupportTicket(user_id=source.user_id, subject=payload.subject.strip(),
            message=f'Продолжение обращения #{source.id}', status='open')
        db.add(target);await db.flush()
        messages = [m for m in messages if m.id in payload.message_ids]
    moving = {m.id for m in messages}
    for message in messages:
        message.ticket_id = target.id
        # Different tickets may share a retry key. Namespace transferred keys
        # rather than dropping either message or violating its unique constraint.
        if message.idempotency_key:
            message.delivery_key = message.delivery_key or message.idempotency_key
            message.idempotency_key = 'moved:' + hashlib.sha256(f'{source.id}:{message.id}:{message.idempotency_key}'.encode()).hexdigest()
    for file in files:
        if file.ticket_id == source.id and (payload.kind == 'merge' or file.message_id in moving):
            file.ticket_id = target.id
            file.idempotency_key = 'moved:' + hashlib.sha256(f'{source.id}:{file.id}:{file.idempotency_key}'.encode()).hexdigest()
    source.topology_version=(source.topology_version or 0)+1
    target.topology_version=(target.topology_version or 0)+1
    source.updated_at = target.updated_at = datetime.utcnow()
    target.status = 'open'
    # Compatibility reply projections must not expose a reply that moved away.
    for ticket in (source, target):
        await db.flush()
        ticket.admin_reply = await db.scalar(select(SupportMessage.body).where(
            SupportMessage.ticket_id == ticket.id, SupportMessage.role == 'admin').order_by(SupportMessage.id.desc()).limit(1))
    result = {'ok': True, 'kind': payload.kind, 'source_id': source.id, 'target_id': target.id,
        'moved_messages': sorted(moving)}
    db.add(SupportTopologyOperation(key=scope, fingerprint=request_fingerprint(payload), result=result))
    await audit(db, 'support.' + payload.kind, admin.email, str(source.id), result)
    await db.commit()
    return result
