"""Two independent MFA administrators must authorize a checksum-bound restore."""
import json
import logging
import os
import secrets
import time
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import select
from .models import AppSetting, AdminUser, AuditLog
from .security import verify_totp
from .config import settings


def require_restore_admin(admin, otp):
    if admin.disabled or admin.role != 'admin':
        raise HTTPException(403, 'Restore requires an active administrator')
    if not admin.mfa_enabled or not otp or not verify_totp(admin, otp):
        raise HTTPException(401, 'Valid MFA code is required for restore')


async def record(db, action, admin, backup_id, approval_id):
    entry = dict(action=action, actor=admin.email, target=str(backup_id), details=approval_id)
    db.add(AuditLog(**entry))
    # A DB restore must not erase its own audit trail. Keep a second, append-only
    # application log on the backup volume, and forward stdout to off-host logs.
    directory = Path(settings.backups_dir)
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / 'restore-audit.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (json.dumps({**entry, 'timestamp': int(time.time())}) + '\n').encode())
    finally:
        os.close(fd)
    logging.getLogger(__name__).warning('Restore audit: %s', entry)


async def request_approval(db, job, admin, otp):
    require_restore_admin(admin, otp)
    if not job or not job.filename or not job.sha256:
        raise HTTPException(409, 'A verified backup with SHA-256 is required')
    approval_id = secrets.token_hex(24)
    data = dict(backup_id=job.id, checksum=job.sha256, requester=admin.id,
                approver=None, expires=int(time.time()) + 600, consumed=False)
    db.add(AppSetting(key='restore.approval:' + approval_id, value=json.dumps(data)))
    await record(db, 'backup.restore.request', admin, job.id, approval_id)
    await db.commit()
    return {'approval_id': approval_id, 'expires_in': 600}


async def use_approval(db, job, admin, otp, approval_id, *, approve=False):
    require_restore_admin(admin, otp)
    if not approval_id or len(approval_id) != 48:
        raise HTTPException(400, 'Restore approval ID required')
    row = (await db.execute(select(AppSetting).where(AppSetting.key == 'restore.approval:' + approval_id).with_for_update())).scalar_one_or_none()
    if not row:
        raise HTTPException(404, 'Restore approval not found')
    data = json.loads(row.value)
    if (not job or data['backup_id'] != job.id or data['checksum'] != job.sha256
            or data['consumed'] or data['expires'] <= int(time.time())):
        raise HTTPException(409, 'Restore approval expired, consumed or backup changed')
    requester = await db.get(AdminUser, data['requester'])
    if not requester or requester.disabled or requester.role != 'admin' or not requester.mfa_enabled:
        raise HTTPException(403, 'Requesting administrator is no longer eligible')
    if approve:
        if admin.id == data['requester'] or data['approver'] is not None:
            raise HTTPException(403, 'A different administrator must approve exactly once')
        data['approver'] = admin.id
        action = 'backup.restore.approve'
    else:
        approver = await db.get(AdminUser, data['approver']) if data['approver'] else None
        if (admin.id != data['requester'] or not approver or approver.id == admin.id
                or approver.disabled or approver.role != 'admin' or not approver.mfa_enabled):
            raise HTTPException(403, 'Independent active MFA administrator approval required')
        data['consumed'] = True
        action = 'backup.restore.execute'
    row.value = json.dumps(data)
    await record(db, action, admin, job.id, approval_id)
    await db.commit()
    return {'ok': True}
