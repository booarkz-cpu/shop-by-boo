from main_source import main_source
from pathlib import Path

ROOT=Path(__file__).parents[1]

def read(rel): return (ROOT/rel).read_text()

def test_v42_version_and_migration():
    main_source()
    mig=read('backend/alembic/versions/0021_v43_hardening_docs.py')
    assert 'down_revision="0020_v42_bot_miniapp"' in mig

def test_payment_creation_does_not_ambiguous_fallback():
    s=main_source()
    part=s[s.index('async def create_payment'):s.index('async def fulfill')]
    assert 'fallback_blocked' in part
    assert 'candidate=provider_order[0]' in part
    assert 'for candidate in provider_order:' not in part

def test_admin_session_persists_last_seen():
    s=read('backend/app/security.py')
    part=s[s.index('async def current_admin'):s.index('def require_permission')]
    assert 'session.last_seen_at=now' in part
    assert 'await db.commit()' in part

def test_staging_gate_requires_full_e2e_marker():
    s=main_source()
    assert "full_pass = False" in s
    # Real payments are an administrator's switch, open by default.
    assert 'PRODUCTION_PAYMENTS_CLOSED_KEY="payments.real.closed"' in s

def test_content_upload_endpoints_and_public_config():
    s=main_source()
    assert '/api/admin/bot/start-image' in s
    assert '/api/admin/miniapp/image' in s
    assert 'bot_start_image' in s
    assert 'miniapp_image' in s

def test_miniapp_consumes_configured_buttons_and_images():
    s=__import__('frontend_sources').miniapp_sources()
    assert 'runButton' in s
    assert 'm.background_image' in s
    assert 'm.image' in s

def test_bot_consumes_start_image():
    s=read('backend/app/bot_banners.py')
    assert 'bot_start_image' in s
    assert 'answer_photo' in s
    assert 'send_section(message,"start"' in read('backend/app/bot.py')

def test_build_release_points_to_v42():
    read('scripts/build-release.sh')

def test_public_config_does_not_dump_private_app_settings():
    s=main_source()
    assert 'AppSetting.key.in_({' in s
    assert 'staging_e2e.config' not in s[s.index('async def public_config'):s.index('async def api_me')]
    assert 'backup_password' not in s[s.index('async def public_config'):s.index('async def api_me')]


def test_content_setting_endpoint_is_allowlisted():
    s=main_source()
    start=s.index('async def admin_setting')
    end=s.index('@app.post("/api/admin/bot/start-image")')
    part=s[start:end]
    assert 'key not in {"app_name","bot_name","theme_default"}' in part
    assert 'staging_e2e.config' not in part
    assert 'payments.production_gate' not in part


def test_invalidated_admin_sessions_are_persistently_revoked():
    s=read('backend/app/security.py')
    start=s.index('async def current_admin')
    end=s.index('def require_permission')
    part=s[start:end]
    assert part.count('await db.commit()') >= 3
