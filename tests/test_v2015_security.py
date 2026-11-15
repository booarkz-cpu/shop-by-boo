"""Behavioral checks for the production hardening audit."""
import ast
import importlib
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def shop(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'services' / 'backend'))
    module = importlib.import_module('app.main')
    monkeypatch.setattr(module.settings, 'app_env', 'test')
    return module

@pytest.mark.asyncio
async def test_generated_recovery_code_can_login_once(shop, monkeypatch):
    from app.security import generate_recovery_codes, set_recovery_codes
    admin = NS(id=7, email='admin@example.com', role='admin', disabled=False,
               password_hash='hash', mfa_enabled=True, totp_secret_encrypted=None)
    code = generate_recovery_codes()[0]
    assert len(code) == 10
    set_recovery_codes(admin, [code])
    db = NS(execute=AsyncMock(return_value=Mock(scalar_one_or_none=lambda: admin)),
            commit=AsyncMock(), add=Mock())
    monkeypatch.setattr(shop, 'verify_password', lambda *args: True)
    monkeypatch.setattr(shop, '_redis_allowed', AsyncMock(return_value=True))
    monkeypatch.setattr(shop, 'redis_client', None)
    request = Request({'type':'http','method':'POST','path':'/api/admin/auth/login','headers':[]})
    payload = shop.LoginIn(email=admin.email, password='valid-password', otp=code)
    result = await shop.admin_login(payload, request, Response(), db)
    assert result['mfa_enabled'] is True
    with pytest.raises(HTTPException) as exc:
        await shop.admin_login(payload, request, Response(), db)
    assert exc.value.status_code == 401

@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['register','login','admin'])
async def test_invalid_native_challenge_has_no_database_side_effects(shop, route):
    from app.cabinet_api import auth_login, auth_register, EmailAuthIn
    path = '/api/admin/auth/login' if route == 'admin' else '/api/auth/' + route
    request = Request({'type':'http','method':'POST','path':path,'scheme':'https',
                       'headers':[(b'x-shop-client', b'android-user')]})
    db = NS(execute=AsyncMock(), scalar=AsyncMock(), commit=AsyncMock(), add=Mock())
    payload = (shop.LoginIn if route == 'admin' else EmailAuthIn)(email='user@example.com',password='password123')
    endpoint = {'register':auth_register,'login':auth_login,'admin':shop.admin_login}[route]
    with pytest.raises(HTTPException) as exc: await endpoint(payload, request, Response(), db)
    assert exc.value.status_code == 400
    db.execute.assert_not_awaited(); db.scalar.assert_not_awaited()
    db.commit.assert_not_awaited(); db.add.assert_not_called()

@pytest.mark.parametrize('changes,match', [
    ({'app_secret':'short'},'APP_SECRET'),
    ({'app_secret_previous':'short'},'APP_SECRET_PREVIOUS'),
    ({'admin_password':'123'},'ADMIN_PASSWORD'),
    ({'database_url':'postgresql+asyncpg://user:change-me@db/shop'},'DATABASE_URL'),
    ({'database_url':'postgresql+asyncpg://user:short@db/shop'},'DATABASE_URL'),
])
def test_production_rejects_weak_real_credentials(shop, changes, match):
    settings = shop.settings.model_copy(update={
        'app_env':'production','app_secret':'x'*48,'app_secret_previous':'',
        'admin_email':'owner@example.com','admin_password':'strong-admin-password',
        'database_url':'postgresql+asyncpg://user:strong-database-password@db/shop',
        'redis_url':'redis://redis/0','redis_password':'y'*48,
        'mobile_require_proof':False,'mobile_client_key':'',
        'admin_cors_origins':'','cabinet_cors_origins':'',**changes})
    with pytest.raises(ValueError, match=match): settings.validate_security()


def test_all_route_permissions_are_defined(shop):
    from app.security import PERMISSIONS
    permitted = set.union(*PERMISSIONS.values())
    for path in (ROOT / 'services/backend/app').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'require_permission' and node.args
                    and isinstance(node.args[0], ast.Constant)):
                assert node.args[0].value in permitted, (path, node.lineno)

@pytest.mark.asyncio
async def test_operator_cannot_access_infrastructure_mutations(shop):
    from app.security import require_permission
    operator = NS(role='operator')
    for permission in ('security.manage','provision_nodes'):
        with pytest.raises(HTTPException) as exc: await require_permission(permission)(operator)
        assert exc.value.status_code == 403


@pytest.mark.parametrize('section,value', [
    ('orchestrator', {'auto_heal':'false'}),
    ('orchestrator', {'stale_seconds':0}),
    ('capacity', {'critical_percent':'90'}),
    ('capacity', {'warning_percent':95,'critical_percent':90}),
    ('retention', {'expiry_days':[True]}),
])
def test_invalid_infrastructure_configuration_is_rejected(shop, section, value):
    from app.v6_api import checked_config
    with pytest.raises(HTTPException) as exc: checked_config(section,value)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_native_admin_logout_revokes_bearer_session(shop, monkeypatch):
    session = NS(revoked_at=None)
    db = NS(execute=AsyncMock(return_value=Mock(scalar_one_or_none=lambda: session)),commit=AsyncMock(),rollback=AsyncMock())
    monkeypatch.setattr(shop, 'decode_token', lambda token: {'type':'admin','jti':'session-id'})
    request = Request({'type':'http','method':'POST','path':'/api/admin/auth/logout',
                       'headers':[(b'authorization',b'Bearer native-token')]})
    await shop.admin_logout(request, Response(), db)
    assert session.revoked_at is not None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('role', ['user', 'admin'])
@pytest.mark.parametrize('invalid', ['expired', 'malformed'])
async def test_logout_clears_invalid_session_cookies(shop, monkeypatch, role, invalid):
    import jwt
    token = jwt.encode({'exp': 1}, shop.settings.app_secret, algorithm='HS256') if invalid == 'expired' else 'broken-token'
    cookie = 'rw_admin' if role == 'admin' else 'rw_user'
    request = Request({'type':'http','method':'POST','path':'/',
                       'headers':[(b'cookie', f'{cookie}={token}; rw_csrf=old'.encode())]})
    db = NS(execute=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
    response = Response()
    result = await getattr(shop, role + '_logout')(request, response, db)
    assert result == {'ok': True}
    cookies = response.headers.getlist('set-cookie')
    assert any(cookie + '=' in value and 'Max-Age=0' in value for value in cookies)
    assert any('rw_csrf=' in value and 'Max-Age=0' in value for value in cookies)
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('role', ['user', 'admin'])
async def test_logout_database_failure_is_not_reported_as_success(shop, monkeypatch, role):
    monkeypatch.setattr(shop, 'decode_token', lambda token: {'type':role,'jti':'session-id'})
    request = Request({'type':'http','method':'POST','path':'/',
                       'headers':[(b'authorization', b'Bearer valid-token')]})
    db = NS(execute=AsyncMock(side_effect=RuntimeError('database unavailable')),
            commit=AsyncMock(), rollback=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        await getattr(shop, role + '_logout')(request, Response(), db)
    assert exc.value.status_code == 503
    db.rollback.assert_awaited_once()
