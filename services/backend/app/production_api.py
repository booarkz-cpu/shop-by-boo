"""Production control-plane APIs for Corgi Lusi v15.

These endpoints deliberately expose control-plane state only. They never accept,
inspect, or persist private VPN traffic payloads.
"""
from __future__ import annotations
import hashlib, hmac, json, os, secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .db import get_db
from .models import AppSetting, Deployment, FeatureFlag, StatusComponent, UserDevice
from .security import require_permission

router = APIRouter()
SUPPORTED_LANGS = {"ru", "en", "uk"}

async def _user(request: Request, db: AsyncSession):
    from .main import user_from_token
    return await user_from_token(request, db)

def _now():
    return datetime.now(timezone.utc).isoformat()

def _setting_key(user_id: int, name: str) -> str:
    return f"user:{user_id}:{name}"

class LanguagePayload(BaseModel):
    language: str = Field(min_length=2, max_length=2)

class DeviceTransferPayload(BaseModel):
    device_name: str = Field(default="New device", min_length=1, max_length=100)
    platform: str = Field(default="unknown", min_length=1, max_length=64)

class AgentActionPayload(BaseModel):
    action: str = Field(min_length=1, max_length=64)
    approved: bool = False

@router.get('/api/me/v15/bootstrap')
async def v15_bootstrap(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _user(request, db)
    lang = (await db.scalar(select(AppSetting.value).where(AppSetting.key == _setting_key(user.id, 'language')))) or 'ru'
    return {
        'product': 'Corgi Lusi Platform', 'version': '15.0.0',
        'language': lang if lang in SUPPORTED_LANGS else 'ru',
        'supported_languages': sorted(SUPPORTED_LANGS),
        'privacy': {'private_traffic_inspection': False, 'payload_logging': False, 'diagnostics_opt_in': True},
        'zero_touch': True, 'seamless_roaming': True,
        'features': ['identity','vpn','edge','lusi','business','marketplace','developer','observability']
    }

@router.put('/api/me/preferences/language')
async def set_language(payload: LanguagePayload, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _user(request, db)
    if payload.language not in SUPPORTED_LANGS:
        raise HTTPException(400, 'Unsupported language')
    key = _setting_key(user.id, 'language')
    row = await db.get(AppSetting, key)
    if row:
        row.value = payload.language
    else:
        db.add(AppSetting(key=key, value=payload.language))
    await db.commit()
    return {'ok': True, 'language': payload.language}

@router.get('/api/me/identity')
async def identity(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _user(request, db)
    devices = (await db.execute(select(UserDevice).where(UserDevice.user_id == user.id).order_by(UserDevice.last_seen_at.desc().nullslast()).limit(50))).scalars().all()
    return {'user_id': user.id, 'identity': 'corgi', 'devices': [{'id': d.id, 'name': d.name, 'platform': d.platform, 'status': d.status} for d in devices], 'passwordless_ready': True}

@router.post('/api/me/devices/transfer')
async def device_transfer(payload: DeviceTransferPayload, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _user(request, db)
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    key = _setting_key(user.id, f'transfer:{digest[:16]}')
    db.add(AppSetting(key=key, value=json.dumps({'created_at': _now(), 'device_name': payload.device_name, 'platform': payload.platform, 'one_time': True})))
    await db.commit()
    return {'transfer_token': token, 'expires_in': 300, 'requires_passkey': True}

@router.post('/api/me/lusi/action')
async def lusi_action(payload: AgentActionPayload, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _user(request, db)
    allowed = {'diagnostics', 'recommend_server', 'run_connection_test'}
    if payload.action not in allowed:
        if not payload.approved:
            raise HTTPException(409, 'Explicit approval required for this action')
        allowed.add(payload.action)
    return {'ok': True, 'action': payload.action, 'user_id': user.id, 'private_traffic_inspected': False}

@router.get('/api/admin/v15/operations')
async def operations(request: Request, db: AsyncSession = Depends(get_db), admin=Depends(require_permission('read'))):
    components = (await db.execute(select(StatusComponent).where(StatusComponent.enabled.is_(True)).order_by(StatusComponent.sort_order.asc()))).scalars().all()
    deployments = (await db.execute(select(Deployment).order_by(Deployment.created_at.desc()).limit(10))).scalars().all()
    flags = (await db.execute(select(FeatureFlag).order_by(FeatureFlag.key.asc()))).scalars().all()
    return {
        'status': [{'slug': c.slug, 'name': c.name, 'status': c.status, 'message': c.message} for c in components],
        'deployments': [{'id': d.id, 'version': d.version, 'strategy': d.strategy, 'traffic_percent': d.traffic_percent, 'status': d.status, 'error_rate_percent': str(d.error_rate_percent)} for d in deployments],
        'feature_flags': [{'key': f.key, 'enabled': f.enabled} for f in flags],
        'privacy': {'private_traffic_inspection': False, 'payload_logging': False},
    }

@router.post('/api/admin/v15/deployments/{deployment_id}/rollback')
async def rollback(deployment_id: int, request: Request, db: AsyncSession = Depends(get_db), admin=Depends(require_permission('security.manage'))):
    row = await db.scalar(select(Deployment).where(Deployment.id == deployment_id).with_for_update())
    if not row:
        raise HTTPException(404, 'Deployment not found')
    row.status = 'rolled_back'; row.traffic_percent = 0; row.rollback_reason = 'Manual emergency rollback'; row.updated_at = datetime.utcnow()
    from .main import audit
    await audit(db, 'deployment.rollback_recorded', admin.email, str(row.id))
    await db.commit()
    return {'ok': True, 'deployment_id': row.id, 'status': row.status}

@router.get('/api/public/v15/privacy')
async def public_privacy():
    return {'private_traffic_inspection': False, 'payload_logging': False, 'control_plane_telemetry': 'minimal', 'diagnostics': 'opt_in', 'retention_policy': 'configurable'}
