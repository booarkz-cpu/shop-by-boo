"""Journaled customer import and local bulk operations with a mandatory preview."""
import asyncio
import hashlib
import json
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .account_actions import revoke_access
from .config import settings
from .db import get_db
from .models import AutoRenewMethod, CustomerImportIdentity, CustomerImportJob, CustomerBatchOperation, FinancialLedger, Notification, Subscription, User, UserSession
from .security import decrypt_secret, encrypt_secret, require_permission
from .sqlite_import import MappingIn, MAX_BYTES, extract


def private(response: Response):response.headers['Cache-Control'] = 'private, no-store'
router = APIRouter(prefix='/api/admin/customer-operations', dependencies=[Depends(private)])


def digest(value):return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
def identity_key(namespace, source_id):return digest(['customer-import-identity-v1', namespace, source_id])


async def advisory(db, key):
    if db.bind.dialect.name == 'postgresql':
        await db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': int.from_bytes(bytes.fromhex(key)[:8], 'big', signed=True)})


async def uploaded(file):
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:raise HTTPException(413, 'Snapshot превышает 5 МБ')
    return data


@router.post('/import/inspect')
async def inspect(file: UploadFile = File(...), table: str = Form('users'), admin=Depends(require_permission('users.import'))):
    return {**await asyncio.to_thread(extract, await uploaded(file), table), 'currency': settings.default_currency}


async def import_snapshot(db, payload, lock=False):
    rows, mapping = payload['rows'], MappingIn.model_validate(payload['mapping'])
    keys = [identity_key(mapping.namespace, row['source_id']) for row in rows]
    bindings = {row.key: row for row in (await db.scalars(select(CustomerImportIdentity).where(CustomerImportIdentity.key.in_(keys)).execution_options(populate_existing=True))).all()}
    statement = select(User).where(User.telegram_id.in_([row['telegram_id'] for row in rows])).order_by(User.id).execution_options(populate_existing=True)
    if lock:statement = statement.with_for_update()
    users = {row.telegram_id: row for row in (await db.scalars(statement)).all()}
    from .account_merge import identity_user
    for telegram_id in {row['telegram_id'] for row in rows} - set(users):
        resolved = await identity_user(db, 'telegram', telegram_id)
        if resolved and lock:
            resolved = await db.scalar(select(User).where(User.id == resolved.id).with_for_update().execution_options(populate_existing=True))
        if resolved:
            users[telegram_id] = resolved
    if mapping.currency != settings.default_currency:raise HTTPException(409, 'Валюта snapshot отличается от валюты магазина')
    states, output = [], []
    for row, key in zip(rows, keys):
        binding, user = bindings.get(key), users.get(row['telegram_id'])
        blocked = False
        if binding:
            if binding.telegram_digest != identity_key(mapping.namespace, str(row['telegram_id'])):
                blocked = True
            elif not user or user.id != binding.user_id or user.deleted_at:blocked = True
            status = 'blocked' if blocked else 'already_imported'
        else:status = 'blocked' if user and (user.deleted_at or user.restricted_at) else 'existing' if user else 'new'
        states.append([key, binding.user_id if binding else None, binding.telegram_digest if binding else None,
            user.id if user else None, str(user.wallet_balance) if user else None,
            str(user.deleted_at) if user else None, str(user.restricted_at) if user else None])
        output.append({**row, 'status': status, 'user_id': user.id if user else None,
            'credit': row['balance'] if status == 'new' and mapping.credit_balances else '0.00'})
    return users, output, digest({'payload': payload, 'states': states, 'currency': settings.default_currency})


def import_result(job, rows):
    counts = {status: sum(row['status'] == status for row in rows) for status in ('new', 'existing', 'already_imported', 'blocked')}
    return {'id': job.id, 'fingerprint': job.fingerprint, 'namespace': job.namespace, 'source_sha256': job.source_sha256,
        'expires_at': job.expires_at, 'counts': counts, 'total_credit': str(sum(Decimal(row['credit']) for row in rows)),
        'rows': [{**row, 'telegram_id': str(row['telegram_id'])} for row in rows]}


async def cleanup_import_previews(db):
    await db.execute(update(CustomerImportJob).where(CustomerImportJob.status=='preview',
        CustomerImportJob.expires_at<=datetime.utcnow()).values(status='expired', payload_encrypted=''))


async def import_cleanup_scheduler():
    from .db import engine
    import logging
    while True:
        try:
            async with AsyncSession(engine) as db:
                await cleanup_import_previews(db);await db.commit()
        except Exception as error:logging.getLogger(__name__).warning('Import preview cleanup failed: %s', type(error).__name__)
        await asyncio.sleep(60)


@router.get('/import/history')
async def import_history(db: AsyncSession = Depends(get_db), admin=Depends(require_permission('users.import'))):
    rows = (await db.scalars(select(CustomerImportJob).where(CustomerImportJob.actor==admin.email).order_by(CustomerImportJob.created_at.desc()).limit(50))).all()
    return [{'id':row.id,'namespace':row.namespace,'source_sha256':row.source_sha256,'status':row.status,
        'expires_at':row.expires_at,'created_at':row.created_at,'result':row.result} for row in rows]


@router.post('/import/preview')
async def import_preview(file: UploadFile = File(...), mapping: str = Form(...), db: AsyncSession = Depends(get_db), admin=Depends(require_permission('users.import'))):
    try:configuration = MappingIn.model_validate_json(mapping)
    except ValidationError as error:raise HTTPException(422, 'Проверьте mapping полей') from error
    data = await uploaded(file)
    rows = await asyncio.to_thread(extract, data, configuration.table, configuration)
    payload = {'mapping': configuration.model_dump(), 'rows': rows}
    users, output, fingerprint = await import_snapshot(db, payload)
    job = CustomerImportJob(id=secrets.token_hex(24), namespace=configuration.namespace,
        source_sha256=hashlib.sha256(data).hexdigest(), actor=admin.email, fingerprint=fingerprint,
        payload_encrypted=encrypt_secret(json.dumps(payload, ensure_ascii=False)), expires_at=datetime.utcnow()+timedelta(minutes=30))
    db.add(job);await db.commit()
    return import_result(job, output)


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fingerprint: str = Field(pattern='^[a-f0-9]{64}$')


@router.post('/import/{job_id}/apply')
async def import_apply(job_id: str, payload: ApplyIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission('users.import'))):
    from .main import audit
    job = await db.scalar(select(CustomerImportJob).where(CustomerImportJob.id == job_id).with_for_update().execution_options(populate_existing=True))
    if not job or job.actor != admin.email:raise HTTPException(404, 'Preview не найден')
    if job.fingerprint != payload.fingerprint:raise HTTPException(409, 'Fingerprint не совпадает')
    if job.status == 'applied':return job.result
    if job.status != 'preview' or job.expires_at <= datetime.utcnow():raise HTTPException(409, 'Preview истёк или отменён')
    staged = json.loads(decrypt_secret(job.payload_encrypted))
    await advisory(db, digest(['customer-import', job.namespace]))
    users, output, fingerprint = await import_snapshot(db, staged, True)
    if fingerprint != job.fingerprint:raise HTTPException(409, 'Клиенты изменились; создайте новый preview')
    if any(row['status'] == 'blocked' for row in output):raise HTTPException(409, 'Preview содержит конфликты идентичностей')
    created, linked, credited, target_ids = 0, 0, Decimal(0), []
    try:
        for row in output:
            if row['status'] == 'already_imported':
                target_ids.append(row['user_id']);continue
            user = users.get(row['telegram_id'])
            if not user:
                user = User(telegram_id=row['telegram_id'], username=row['username'], wallet_balance=Decimal(row['credit']))
                db.add(user);await db.flush();created += 1
                if Decimal(row['credit']):
                    key = identity_key(job.namespace, row['source_id'])
                    db.add(FinancialLedger(operation_key='customer-import:'+key, user_id=user.id,
                        kind='wallet_import', direction='credit', amount=Decimal(row['credit']), currency=staged['mapping']['currency'],
                        balance_after=user.wallet_balance, metadata_json=json.dumps({'import_job': job.id})))
                    credited += Decimal(row['credit'])
            else:linked += 1
            target_ids.append(user.id)
            db.add(CustomerImportIdentity(key=identity_key(job.namespace, row['source_id']), user_id=user.id,
                telegram_digest=identity_key(job.namespace, str(row['telegram_id']))))
        job.result = {'ok': True, 'created': created, 'linked_existing': linked,
            'already_imported': sum(row['status']=='already_imported' for row in output), 'credited': str(credited), 'user_ids': sorted(target_ids)}
        job.status = 'applied';job.payload_encrypted = ''
        await audit(db, 'customers.import.applied', admin.email, job.id, job.result)
        await db.commit()
    except IntegrityError as error:
        await db.rollback();raise HTTPException(409, 'Регистрация/импорт изменили клиентов; создайте новый preview') from error
    return job.result


@router.post('/import/{job_id}/cancel')
async def cancel_import(job_id: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission('users.import'))):
    job = await db.scalar(select(CustomerImportJob).where(CustomerImportJob.id == job_id).with_for_update())
    if not job or job.actor != admin.email:raise HTTPException(404, 'Preview не найден')
    if job.status == 'applied':raise HTTPException(409, 'Применённый импорт нельзя отменить как preview')
    job.status = 'cancelled';job.payload_encrypted = '';await db.commit();return {'ok': True}


class BulkIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_ids: list[int] = Field(min_length=1, max_length=200)
    action: str = Field(pattern='^(revoke_sessions|disable_auto_renew|restrict_shop|restore_shop|notify)$')
    reason: str = Field(min_length=3, max_length=500)
    title: str = Field(default='', max_length=255)
    body: str = Field(default='', max_length=5000)
    fingerprint: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')


async def bulk_snapshot(db, payload, lock=False):
    ids = sorted(payload.user_ids)
    if len(set(ids)) != len(ids) or any(identifier <= 0 for identifier in ids) or not payload.reason.strip():
        raise HTTPException(422, 'Укажите разные положительные ID и причину')
    if payload.action == 'notify' and (not payload.title.strip() or not payload.body.strip()):raise HTTPException(422, 'Укажите заголовок и текст')
    statement = select(User).where(User.id.in_(ids)).order_by(User.id).execution_options(populate_existing=True)
    if lock:statement = statement.with_for_update()
    users = (await db.scalars(statement)).all()
    if len(users) != len(ids) or any(user.deleted_at for user in users):raise HTTPException(409, 'Клиент не найден или удалён')
    # Readers and writers share User -> subscription/method/session lock order.
    profiles_query = select(Subscription).where(Subscription.user_id.in_(ids)).order_by(Subscription.id).execution_options(populate_existing=True)
    methods_query = select(AutoRenewMethod).where(AutoRenewMethod.user_id.in_(ids)).order_by(AutoRenewMethod.id).execution_options(populate_existing=True)
    if lock:profiles_query=profiles_query.with_for_update();methods_query=methods_query.with_for_update()
    profiles, methods = (await db.scalars(profiles_query)).all(), (await db.scalars(methods_query)).all()
    sessions = (await db.execute(select(UserSession.id, UserSession.user_id).where(UserSession.user_id.in_(ids), UserSession.revoked_at.is_(None)).order_by(UserSession.id))).all()
    notices = (await db.execute(select(Notification.user_id, func.max(Notification.id)).where(Notification.user_id.in_(ids)).group_by(Notification.user_id).order_by(Notification.user_id))).all()
    state = {'request': payload.model_dump(exclude={'fingerprint'}),
        'users': [[user.id, user.auto_renew_enabled, str(user.restricted_at)] for user in users],
        'profiles': [[row.id, row.auto_renew_enabled, str(row.next_renewal_at)] for row in profiles],
        'methods': [[row.id, row.enabled, row.status] for row in methods], 'sessions': [list(row) for row in sessions], 'notifications': [list(row) for row in notices]}
    return users, profiles, methods, len(sessions), digest(state)


@router.post('/bulk/preview')
async def bulk_preview(payload: BulkIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission('users.bulk'))):
    users, profiles, methods, sessions, fingerprint = await bulk_snapshot(db, payload)
    return {'fingerprint': fingerprint, 'action': payload.action, 'user_ids': [user.id for user in users], 'users': len(users), 'subscriptions': len(profiles), 'sessions': sessions}


@router.post('/bulk/apply')
async def bulk_apply(payload: BulkIn, request: Request, db: AsyncSession = Depends(get_db), admin=Depends(require_permission('users.bulk'))):
    from .main import audit
    key = request.headers.get('Idempotency-Key', '')
    if not 1 <= len(key) <= 128 or any(ord(char) < 32 or ord(char) > 126 for char in key):raise HTTPException(422, 'Укажите Idempotency-Key')
    scope = digest([admin.email, key]);await advisory(db, scope)
    prior = await db.get(CustomerBatchOperation, scope)
    if prior:
        if prior.fingerprint != digest(payload.model_dump()):raise HTTPException(409, 'Ключ использован для другого запроса')
        return prior.result
    users, profiles, methods, sessions, fingerprint = await bulk_snapshot(db, payload, True)
    if payload.fingerprint != fingerprint:raise HTTPException(409, 'Данные изменились; обновите preview')
    now = datetime.utcnow()
    for user in users:
        if payload.action == 'revoke_sessions':await revoke_access(db, user)
        elif payload.action == 'restrict_shop':
            user.restricted_at=now;user.auto_renew_enabled=False;await revoke_access(db,user)
        elif payload.action == 'restore_shop':user.restricted_at=None
        elif payload.action == 'disable_auto_renew':user.auto_renew_enabled = False
        else:db.add(Notification(user_id=user.id, channel='in_app', kind='admin.bulk', title=payload.title.strip(),
            body=payload.body.strip(), status='sent', sent_at=now, dedupe_key='customer-bulk:'+scope))
    if payload.action in ('disable_auto_renew','restrict_shop'):
        for profile in profiles:profile.auto_renew_enabled=False;profile.next_renewal_at=None
    result = {'ok': True, 'action': payload.action, 'users': len(users), 'user_ids': [user.id for user in users]}
    db.add(CustomerBatchOperation(key=scope, fingerprint=digest(payload.model_dump()), result=result))
    await audit(db, 'customers.bulk.'+payload.action, admin.email, scope, {**result, 'reason': payload.reason})
    await db.commit();return result
