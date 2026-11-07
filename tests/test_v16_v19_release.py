import ast, pathlib, re, yaml
ROOT=pathlib.Path(__file__).resolve().parents[1]
MAIN=ROOT/'backend/app/main.py'
COMPOSE=ROOT/'docker-compose.yml'

def read(p): return p.read_text(encoding='utf-8')

def test_python_compiles():
    for p in (ROOT/'backend/app').glob('*.py'):
        ast.parse(read(p))

def test_main_has_v19_features():
    import inspect
    from app import main as shop
    from app_contract import missing_paths
    assert not missing_paths('/api/admin/analytics','/api/admin/sessions','/api/admin/payments/{payment_id}/retry','/api/admin/backups/{backup_id}/verify',
                             '/api/admin/backups/{backup_id}/restore','/api/me/referral','/api/me/subscription')
    assert callable(shop.fulfillment_retry_scheduler) and callable(shop.expiry_notification_scheduler)
    assert 'payload' not in inspect.signature(shop.admin_menu_delete).parameters  # a DELETE takes no body

def test_security_session_and_permissions():
    # Admin sessions are registered by jti and revocable: test_v42_hardening.py.
    from app.security import PERMISSIONS
    assert {'users.keys', 'sessions.manage', 'backups.write'} <= PERMISSIONS['admin']
    assert 'users.keys' in PERMISSIONS['operator'] and 'backups.write' not in PERMISSIONS['operator']

def test_models():
    from app import models
    for name in ['AdminSession','PromoRedemption','ReferralReward']:
        assert hasattr(models, name), name
    for column in ['fulfillment_status','next_retry_at','idempotency_key']:
        assert column in models.Payment.__table__.columns, column
    for column in ['referral_code','referral_balance']:
        assert column in models.User.__table__.columns, column

def test_migration_chain():
    files=sorted((ROOT/'backend/alembic/versions').glob('*.py'))
    revisions=[]; downs=[]
    for p in files:
        s=read(p); m=re.search(r'revision\s*=\s*["\']([^"\']+)',s); d=re.search(r'down_revision\s*=\s*["\']([^"\']+)',s)
        assert m, p; revisions.append(m.group(1)); downs.append(d.group(1) if d else None)
    assert len(revisions)==len(set(revisions))
    assert '0008_v16_v19' in revisions and '0007_v15_production' in downs

def test_compose_private_ports():
    c=yaml.safe_load(read(COMPOSE))
    assert set(c['services']['caddy']['ports'])=={'80:80','443:443','443:443/udp'}
    for name in ['db','redis','backend','bot','admin','miniapp']:
        assert not c['services'][name].get('ports')

def test_no_float_money_in_discount_logic():
    from decimal import Decimal

    from app import main as shop
    assert shop.discounted_amount("0.10", "percent", "33.3333") == Decimal("0.03"), "Decimal maths, rounded half up"
    assert shop.discounted_amount(Decimal("99.99"), "percent", 10) == Decimal("10.00")

def test_env_s3():
    s=read(ROOT/'.env.example')
    for x in ['S3_ENDPOINT_URL','S3_BUCKET','S3_ACCESS_KEY','S3_SECRET_KEY','REFERRAL_REWARD_PERCENT']:
        assert x in s
