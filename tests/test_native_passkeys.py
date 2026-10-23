"""Native passkeys in the customer apps: app origins, header binding, PKCE code, app association."""
import base64
import hashlib
import secrets

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException, Response
from sqlalchemy import func, select
from starlette.requests import Request

from app import customer_passkeys as keys
from app import mobile_auth
from app.models import CustomerPasskey, FeatureFlag, User, UserSession
from app.security import hash_password
from test_admin_passkeys import assertion, attestation
from test_subscription_commerce import database

ORIGIN = 'https://cabinet.example.test'
PASSWORD = 'native-passkey-password'
FINGERPRINT = ':'.join(['AB'] * 32)
ANDROID_ORIGIN = 'android:apk-key-hash:' + base64.urlsafe_b64encode(bytes([0xAB] * 32)).decode().rstrip('=')
VERIFIER = 'v' * 64


def native(client='android-user', binding='', pkce=True, browser_origin=None):
    headers = [(b'x-shop-client', client.encode())]
    if binding:
        headers.append((keys.BINDING_HEADER.encode(), binding.encode()))
    if pkce:
        headers.append((b'x-shop-code-challenge', mobile_auth.pkce_challenge(VERIFIER).encode()))
    if browser_origin:
        headers.append((b'origin', browser_origin.encode()))
    return Request({'type': 'http', 'method': 'POST', 'scheme': 'https', 'server': ('api.example.test', 443),
        'path': '/api/auth/passkeys/login/verify', 'headers': headers, 'client': ('127.0.0.1', 123)})


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(keys.settings, 'customer_webauthn_origin', ORIGIN)
    monkeypatch.setattr(keys.settings, 'android_user_cert_sha256', FINGERPRINT)
    monkeypatch.setattr(keys.settings, 'ios_user_app_id', 'TEAM123456.shop.remnawave.user')
    monkeypatch.setattr(keys.settings, 'mobile_require_proof', False)
    monkeypatch.setattr(keys.settings, 'api_domain', 'api.example.test')


async def register(db, client, origin):
    user = await db.get(User, 1)
    user.email_password_hash = hash_password(PASSWORD)
    if not await db.scalar(select(FeatureFlag).where(FeatureFlag.key == 'passkeys')):
        db.add(FeatureFlag(key='passkeys', enabled=True))
    await db.commit()
    private = ec.generate_private_key(ec.SECP256R1())
    identifier = secrets.token_bytes(32)
    response = Response()
    options = await keys.registration_options(keys.RegisterIn(password=PASSWORD, name='Телефон'), native(client), response, db)
    assert 'set-cookie' not in response.headers, 'native ceremonies do not use cookies'
    assert options['binding'] and options['options']['rp']['id'] == 'cabinet.example.test'
    await keys.registration_verify(keys.VerifyIn(ticket=options['ticket'],
        credential=attestation(options['options'], private, identifier, origin=origin)),
        native(client, options['binding']), Response(), db)
    return user, private, identifier


async def sign_in(db, client, user, private, identifier, origin, **request_args):
    options = await keys.login_options(native(client), Response(), db)
    credential = assertion(options['options'], private, identifier, user.passkey_user_handle, origin=origin)
    return await keys.login_verify(keys.VerifyIn(ticket=options['ticket'], credential=credential),
        native(client, options['binding'], **request_args), Response(), db)


class Redis:
    def __init__(self):
        self.keys = set()

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True


def test_android_origin_is_the_base64url_signing_certificate_digest():
    assert keys.android_origins(FINGERPRINT) == [ANDROID_ORIGIN]
    assert keys.android_origins('ab' * 32 + ', ' + 'CD' * 32)[1].startswith('android:apk-key-hash:')
    with pytest.raises(HTTPException):
        keys.android_origins('not-a-fingerprint')


@pytest.mark.asyncio
async def test_android_passkey_registers_and_signs_in_with_pkce_code(database, configured):
    user, private, identifier = await register(database, 'android-user', ANDROID_ORIGIN)
    assert (await database.scalar(select(CustomerPasskey))).name == 'Телефон'
    result = await sign_in(database, 'android-user', user, private, identifier, ANDROID_ORIGIN)
    assert result['auth_method'] == 'passkey' and 'authorization_code' in result and 'access_token' not in result
    token_request = native('android-user')
    exchanged = await mobile_auth.exchange_mobile_code(token_request, result['authorization_code'], VERIFIER, Redis())
    assert exchanged['token_type'] == 'bearer' and exchanged['access_token']
    assert await database.scalar(select(func.count()).select_from(UserSession)) == 1
    with pytest.raises(HTTPException):
        await mobile_auth.exchange_mobile_code(token_request, result['authorization_code'], 'w' * 64, Redis())


@pytest.mark.asyncio
async def test_ios_passkey_uses_the_associated_cabinet_origin(database, configured):
    user, private, identifier = await register(database, 'ios-user', ORIGIN)
    result = await sign_in(database, 'ios-user', user, private, identifier, ORIGIN)
    assert 'authorization_code' in result


@pytest.mark.asyncio
@pytest.mark.parametrize('attack', ['web-origin-from-android', 'other-app', 'cookie-binding', 'no-pkce', 'browser-origin'])
async def test_native_ceremony_rejects_attacks(database, configured, attack):
    user, private, identifier = await register(database, 'android-user', ANDROID_ORIGIN)
    options = await keys.login_options(native('android-user'), Response(), database)
    origin = {'web-origin-from-android': ORIGIN,
              'other-app': 'android:apk-key-hash:' + base64.urlsafe_b64encode(bytes(32)).decode().rstrip('=')}.get(attack, ANDROID_ORIGIN)
    credential = assertion(options['options'], private, identifier, user.passkey_user_handle, origin=origin)
    request = native('android-user', '' if attack == 'cookie-binding' else options['binding'],
        pkce=attack != 'no-pkce', browser_origin=ORIGIN if attack == 'browser-origin' else None)
    with pytest.raises(HTTPException):
        await keys.login_verify(keys.VerifyIn(ticket=options['ticket'], credential=credential), request, Response(), database)
    assert await database.scalar(select(func.count()).select_from(UserSession)) == 0
    if attack == 'no-pkce':
        # The challenge was not spent: the app can retry with a PKCE challenge.
        retried = await keys.login_verify(keys.VerifyIn(ticket=options['ticket'], credential=credential),
            native('android-user', options['binding']), Response(), database)
        assert 'authorization_code' in retried


@pytest.mark.asyncio
async def test_native_passkeys_need_app_identity(database, monkeypatch):
    monkeypatch.setattr(keys.settings, 'customer_webauthn_origin', ORIGIN)
    monkeypatch.setattr(keys.settings, 'mobile_require_proof', False)
    monkeypatch.setattr(keys.settings, 'android_user_cert_sha256', '')
    monkeypatch.setattr(keys.settings, 'ios_user_app_id', '')
    monkeypatch.setattr(keys.settings, 'apns_team_id', '')
    monkeypatch.setattr(keys.settings, 'api_domain', 'api.example.test')
    database.add(FeatureFlag(key='passkeys', enabled=True))
    await database.commit()
    for client in ('android-user', 'ios-user'):
        with pytest.raises(HTTPException) as error:
            await keys.login_options(native(client), Response(), database)
        assert error.value.status_code == 503
    # The admin apps are not customer passkey clients and keep the browser rules.
    with pytest.raises(HTTPException) as error:
        await keys.login_options(native('android-admin'), Response(), database)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_app_association_documents(monkeypatch):
    monkeypatch.setattr(keys.settings, 'android_user_cert_sha256', 'ab' * 32 + ',broken')
    monkeypatch.setattr(keys.settings, 'android_user_package', 'shop.remnawave.user')
    monkeypatch.setattr(keys.settings, 'ios_user_app_id', '')
    monkeypatch.setattr(keys.settings, 'apns_team_id', 'TEAM123456')
    monkeypatch.setattr(keys.settings, 'apns_bundle_id', 'shop.remnawave.user')
    response = Response()
    links = await keys.assetlinks(response)
    assert links[0]['target'] == {'namespace': 'android_app', 'package_name': 'shop.remnawave.user',
                                  'sha256_cert_fingerprints': [FINGERPRINT]}
    assert 'delegate_permission/common.get_login_creds' in links[0]['relation']
    assert response.headers['cache-control'].startswith('public')
    assert await keys.apple_app_site_association(Response()) == {'webcredentials': {'apps': ['TEAM123456.shop.remnawave.user']}}
    monkeypatch.setattr(keys.settings, 'android_user_cert_sha256', '')
    monkeypatch.setattr(keys.settings, 'apns_team_id', '')
    assert await keys.assetlinks(Response()) == []
    assert await keys.apple_app_site_association(Response()) == {'webcredentials': {'apps': []}}


def test_app_association_is_routed_on_the_cabinet_domain():
    from pathlib import Path
    caddy = (Path(__file__).resolve().parents[1] / 'deploy/Caddyfile').read_text()
    cabinet = caddy[caddy.index('{$CABINET_DOMAIN} {'):caddy.index('{$API_DOMAIN} {')]
    assert 'handle /.well-known/assetlinks.json' in cabinet and 'handle /.well-known/apple-app-site-association' in cabinet
    digest = hashlib.sha256(b'unused').hexdigest()
    assert len(digest) == 64
