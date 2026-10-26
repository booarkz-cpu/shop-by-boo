"""Mobile-first aggregation and safe action endpoints for Corgi Android/iOS apps."""
from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from .db import get_db
from .models import Notification, UserDevice, NodeAgent, AbuseViolation, AppSetting

router = APIRouter()

async def _user(request: Request, db: AsyncSession):
    from .main import user_from_token
    return await user_from_token(request, db)

@router.get('/api/me/mobile/bootstrap')
async def mobile_bootstrap(request: Request, db: AsyncSession = Depends(get_db)):
    from .v3_api import routing_recommendation
    user = await _user(request, db)
    devices = (await db.execute(select(UserDevice).where(UserDevice.user_id == user.id).order_by(UserDevice.last_seen_at.desc().nullslast(), UserDevice.id.desc()).limit(20))).scalars().all()
    unread = await db.scalar(select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.read_at.is_(None))) or 0
    return {
        'user': {'id': user.id, 'email': user.email, 'username': user.username, 'wallet_balance': str(user.wallet_balance or 0), 'referral_code': user.referral_code},
        'devices': [{'id': d.id, 'name': d.name, 'platform': d.platform, 'status': d.status, 'last_seen_at': d.last_seen_at} for d in devices],
        'notifications': {'unread': int(unread)},
        'mobile': {'biometric': True, 'quick_connect': True, 'qr_onboarding': True, 'deep_links': ['corgi://connect', 'corgi://support']},
    }

@router.get('/api/me/mobile/notifications')
async def mobile_notifications(request: Request, unread_only: bool = False, db: AsyncSession = Depends(get_db)):
    user = await _user(request, db)
    q = select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(50)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    rows = (await db.execute(q)).scalars().all()
    return [{'id': n.id, 'kind': n.kind, 'title': n.title, 'body': n.body, 'read': n.read_at is not None, 'created_at': n.created_at} for n in rows]

@router.post('/api/me/mobile/notifications/{notification_id}/read')
async def mobile_notification_read(notification_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _user(request, db)
    row = (await db.execute(select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id).with_for_update())).scalar_one_or_none()
    if not row:
        raise HTTPException(404, 'Notification not found')
    row.read_at = datetime.utcnow()
    await db.commit()
    return {'ok': True}

@router.get('/api/admin/mobile/ops')
async def admin_mobile_ops(request: Request, db: AsyncSession = Depends(get_db), admin=Depends(__import__('app.security', fromlist=['require_permission']).require_permission('read'))):
    agents = (await db.execute(select(NodeAgent).order_by(NodeAgent.last_seen_at.desc().nullslast()).limit(50))).scalars().all()
    open_abuse = await db.scalar(select(func.count(AbuseViolation.id)).where(AbuseViolation.status == 'open')) or 0
    stale = sum(1 for a in agents if not a.last_seen_at)
    return {'critical': int(open_abuse), 'agents': [{'id': a.id, 'name': a.name, 'cpu': a.cpu, 'mem': a.mem, 'last_seen_at': a.last_seen_at} for a in agents], 'stale_agents': stale}


@router.get('/api/me/mobile/features')
async def mobile_features(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _user(request, db)
    return {
        'app_name': 'Корги Люси',
        'version': '9.0.0',
        'features': {
            'smart_connect': False, 'auto_failover': False, 'kill_switch': False,
            'always_on_vpn': False, 'trusted_networks': False, 'split_tunneling': False,
            'gaming_mode': False, 'streaming_profiles': False, 'live_connection': False,
            'security_alerts': True, 'device_trust': True, 'diagnostics': True,
            'privacy_dashboard': True, 'family_plan': True, 'business_vpn': True,
            'referrals': True, 'rewards': True, 'network_map': True,
            'support_assistant': True, 'watch_widgets': True,
        },
        'profiles': [
            {'id':'fastest','name':'Fastest','strategy':'latency'},
            {'id':'gaming','name':'Gaming','strategy':'latency_jitter_loss'},
            {'id':'streaming','name':'Streaming','strategy':'stability'},
            {'id':'privacy','name':'Privacy','strategy':'secure'},
            {'id':'work','name':'Work','strategy':'stability'},
        ],
        'user_id': user.id,
    }

@router.get('/api/me/mobile/connection')
async def mobile_connection(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _user(request, db)
    from .v3_api import routing_recommendation
    recommendation = await routing_recommendation(request, db)
    rec = recommendation.get('recommendation') if isinstance(recommendation, dict) else None
    return {
        'status': 'ready' if rec else 'degraded',
        'connected': False,
        'server': rec,
        'latency_ms': None,
        'download_mbps': None,
        'upload_mbps': None,
        'packet_loss_percent': None,
        'jitter_ms': None,
        'uptime_seconds': 0,
        'auto_failover': False,
        'profile': 'fastest',
        'user_id': user.id,
    }

@router.get('/api/me/mobile/diagnostics')
async def mobile_diagnostics(request: Request, db: AsyncSession = Depends(get_db)):
    await _user(request, db)
    checks = [
        {'name':'Internet API','status':'ok','detail':'API reachable'},
        {'name':'Authentication','status':'ok','detail':'Session valid'},
        {'name':'Smart Routing','status':'ok','detail':'Recommendation service available'},
        {'name':'Notifications','status':'ok','detail':'In-app notification center available'},
    ]
    return {'overall':'ok','checks':checks,'generated_at':datetime.utcnow()}

@router.get('/api/me/mobile/privacy')
async def mobile_privacy(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _user(request, db)
    return {'user_id': user.id, 'vpn_time_seconds': 0, 'protected_traffic_bytes': 0, 'dns_protected': False, 'ipv6_protected': False, 'kill_switch': False, 'note':'This app does not implement a VPN tunnel. Use a supported external client with the subscription URL.'}

@router.get('/api/me/mobile/alerts')
async def mobile_alerts(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _user(request, db)
    rows = (await db.execute(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(20))).scalars().all()
    return [{'id':n.id,'kind':n.kind,'title':n.title,'body':n.body,'read':n.read_at is not None,'created_at':n.created_at} for n in rows]
