"""Explicit configuration boundaries, scoped CORS and bounded rate fallback."""
from collections import OrderedDict
import ipaddress
import logging
import time
from urllib.parse import urlsplit, unquote
from fastapi.middleware.cors import CORSMiddleware

LEGACY_MOBILE_KEY = 'b7e1c4a09f6d42e8a1c35b77d0e94f12'
_LOCAL = OrderedDict()
MAX_LOCAL_KEYS = 10000


def redis_connection_kwargs(url, password):
    embedded = unquote(urlsplit(url).password or '')
    if password and embedded and password != embedded:
        raise ValueError('REDIS_PASSWORD conflicts with REDIS_URL password')
    return {'password': password} if password and not embedded else {}


def trusted_proxy(host, cidrs):
    try:
        peer = ipaddress.ip_address(host)
        return any(peer in ipaddress.ip_network(item.strip()) for item in cidrs.split(',') if item.strip())
    except ValueError:
        return False


def _origins(value, production, permitted_hosts):
    result = []
    for origin in value.split(','):
        origin = origin.strip()
        if not origin:
            continue
        parsed = urlsplit(origin)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or '*' in origin or origin == 'null'):
            raise ValueError('CORS origins must be exact scheme://host[:port] values')
        if production and (parsed.scheme != 'https' or parsed.hostname not in permitted_hosts):
            raise ValueError('Production CORS origin must use HTTPS and a configured frontend domain')
        result.append(origin)
    return result


def validate_configuration(settings):
    prod = settings.app_env.lower() == 'production'
    redis_connection_kwargs(settings.redis_url, settings.redis_password)
    for item in settings.trusted_proxy_cidrs.split(','):
        if item.strip():
            net = ipaddress.ip_network(item.strip())
            if net.prefixlen == 0:
                raise ValueError('TRUSTED_PROXY_CIDRS must not trust every address')
    _origins(settings.admin_cors_origins, prod, {settings.admin_domain})
    _origins(settings.cabinet_cors_origins, prod, {settings.cabinet_domain, settings.app_domain, settings.miniapp_domain})
    if not prod:
        return
    if settings.rollypay_test_mode:
        raise ValueError('ROLLYPAY_TEST_MODE must be false in production')
    if settings.support_pro_url or settings.support_pro_sso_secret:
        secret = settings.support_pro_sso_secret
        if not settings.support_pro_url or len(secret) < 32 or secret.startswith("change-me"):
            raise ValueError("Support Pro requires a URL and a unique SSO secret of at least 32 characters")
    if settings.mobile_client_key == LEGACY_MOBILE_KEY:
        raise ValueError('Remove the public default MOBILE_CLIENT_KEY; native apps use PKCE')
    if settings.mobile_require_proof and len(settings.mobile_client_key) < 32:
        raise ValueError('MOBILE_CLIENT_KEY must be unique and at least 32 characters')
    # Native clients no longer use a shared application key as authentication.
    if settings.mobile_require_proof:
        raise ValueError('Legacy mobile HMAC is disabled in production; use PKCE and MOBILE_REQUIRE_PROOF=false')
    password = settings.redis_password or unquote(urlsplit(settings.redis_url).password or '')
    if len(password) < 32 or password.startswith('change-me'):
        raise ValueError('Production Redis requires a unique password of at least 32 characters')
    groups = [
        ('YooKassa', (settings.yookassa_shop_id, settings.yookassa_secret_key), (settings.yookassa_webhook_ip_allowlist,)),
        ('Platega', (settings.platega_merchant_id, settings.platega_secret), ()),
        ('RollyPay', (settings.rollypay_api_key, settings.rollypay_signing_secret), ()),
        ('Stripe', (settings.stripe_secret_key, settings.stripe_webhook_secret), ()),
        ('PayPal', (settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_webhook_id), ()),
    ]
    for name, credentials, required in groups:
        if any(credentials) and not all((*credentials, *required)):
            raise ValueError(f'{name}: incomplete credentials or webhook authentication configuration')
    for item in settings.yookassa_webhook_ip_allowlist.split(','):
        if item.strip():
            net = ipaddress.ip_network(item.strip())
            if not net.network_address.is_global or net.prefixlen == 0:
                raise ValueError('YooKassa allowlist must contain explicit public provider networks')
    if settings.yookassa_shop_id and not settings.trusted_proxy_cidrs:
        raise ValueError('YooKassa behind ingress requires explicit TRUSTED_PROXY_CIDRS')
    def strong(value, minimum):
        return len(value) >= minimum and not value.lower().startswith(('change-me', 'changeme', 'replace-me'))
    if not strong(settings.app_secret, 32):
        raise ValueError('APP_SECRET must be unique and at least 32 characters')
    if settings.app_secret_previous and not strong(settings.app_secret_previous, 32):
        raise ValueError('APP_SECRET_PREVIOUS must be unique and at least 32 characters')
    if settings.admin_email and not strong(settings.admin_password, 12):
        raise ValueError('ADMIN_PASSWORD must be unique and at least 12 characters')
    password = unquote(urlsplit(settings.database_url).password or '')
    if not strong(password, 16):
        raise ValueError('DATABASE_URL requires a unique password of at least 16 characters')



def local_rate_allowed(key, limit, window):
    now = time.monotonic()
    # Expired buckets are bounded in number. Do not evict live buckets: an
    # attacker rotating keys must not reset another client's login limit.
    for old in list(_LOCAL):
        if _LOCAL[old][1] <= now:
            del _LOCAL[old]
    count, expires = _LOCAL.get(key, (0, now + window))
    if key not in _LOCAL and len(_LOCAL) >= MAX_LOCAL_KEYS:
        return False
    _LOCAL[key] = (count + 1, expires)
    return count < limit


async def rate_allowed(redis, key, limit, window):
    fallback = local_rate_allowed(key, limit, window)
    if redis is None:
        return fallback
    try:
        count = await redis.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n", 1, key, window)
        return int(count) <= limit
    except Exception:
        return fallback


async def reset_login_attempts(redis, key: str) -> None:
    """Reset only a verified login's attempt bucket, including Redis fallback."""
    if not key.startswith("login:"):
        raise ValueError("Only a verified login attempt bucket can be reset")
    _LOCAL.pop(key, None)
    if redis is None:
        return
    try:
        await redis.delete(key)
    except Exception:
        logging.getLogger(__name__).warning(
            "Shared login counter reset unavailable; local counter cleared"
        )


class ScopedCORSMiddleware:
    def __init__(self, app, settings):
        prod = settings.app_env.lower() == 'production'
        admin = _origins(settings.admin_cors_origins, prod, {settings.admin_domain})
        cabinet = _origins(settings.cabinet_cors_origins, prod, {settings.cabinet_domain, settings.app_domain, settings.miniapp_domain})
        common = dict(allow_credentials=True, allow_methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS'],
                      allow_headers=['Content-Type','Idempotency-Key','X-CSRF-Token'])
        self.admin = CORSMiddleware(app, allow_origins=admin, **common)
        self.cabinet = CORSMiddleware(app, allow_origins=cabinet, **common)
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('path', '').startswith('/api/auth/mobile/'):
            return await self.app(scope, receive, send)
        target = self.admin if scope.get('path','').startswith('/api/admin/') else self.cabinet
        return await target(scope, receive, send)
