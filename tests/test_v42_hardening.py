"""v42–v43 hardening, checked by running the code (was: code lines searched in main.py and security.py).
The «no ambiguous fallback» rule of checkout runs in test_behaviour_payments_v2.py and the content-setting
allowlist in test_v44_5_19_branding_ui_and_security.py."""
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from starlette.requests import Request

from app import main as shop
from app.models import AdminSession, AdminUser, AppSetting
from app.security import current_admin, hash_password, issue_token
from app_contract import missing_routes, revision
from test_behaviour_auth import db  # noqa: F401
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).parents[1]


def read(rel): return (ROOT / rel).read_text()


def test_v42_version_and_migration():
    assert revision("0021_v43_hardening_docs").down_revision == "0020_v42_bot_miniapp"


def admin_request(ua="Mozilla/5.0 admin"):
    return Request({"type": "http", "method": "GET", "path": "/api/admin/overview", "client": ("10.0.0.1", 1), "query_string": b"",
                    "headers": [(b"user-agent", ua.encode())]})


async def signed_in(db, last_seen=None, ua="Mozilla/5.0 admin"):  # noqa: F811
    admin = AdminUser(email="ops@corgi.test", password_hash=hash_password("x"), role="operator")
    db.add(admin)
    await db.flush()
    db.add(AdminSession(admin_id=admin.id, jti_hash=hashlib.sha256(b"jti-1").hexdigest(), ip="10.0.0.1", user_agent=ua,
                        expires_at=datetime.utcnow() + timedelta(minutes=30), last_seen_at=last_seen or datetime.utcnow()))
    await db.commit()
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=issue_token(admin, False, 30, jti="jti-1"))


@pytest.mark.asyncio
async def test_admin_activity_is_stored_and_idle_or_moved_sessions_are_revoked(db):  # noqa: F811
    token = await signed_in(db)
    assert (await current_admin(admin_request(), token, db)).email == "ops@corgi.test"
    session = (await db.execute(select(AdminSession).execution_options(populate_existing=True))).scalar_one()
    assert session.last_seen_at is not None and session.revoked_at is None, "activity is committed even by read-only pages"
    with pytest.raises(HTTPException) as moved:
        await current_admin(admin_request("curl/8.0"), token, db)
    assert moved.value.detail == "Admin session device changed"
    session = (await db.execute(select(AdminSession).execution_options(populate_existing=True))).scalar_one()
    assert session.revoked_at is not None, "the revocation is stored, the token stays dead"
    with pytest.raises(HTTPException):
        await current_admin(admin_request(), token, db)


@pytest.mark.asyncio
async def test_an_idle_admin_session_ends(db):  # noqa: F811
    token = await signed_in(db, last_seen=datetime.utcnow() - timedelta(minutes=16))
    with pytest.raises(HTTPException) as idle:
        await current_admin(admin_request(), token, db)
    assert idle.value.detail == "Admin session expired by inactivity"
    assert (await db.execute(select(AdminSession).execution_options(populate_existing=True))).scalar_one().revoked_at is not None


@pytest.mark.asyncio
async def test_real_payments_are_open_until_the_owner_closes_them(database):
    from app.staging_e2e_api import production_payments_allowed
    assert shop.PRODUCTION_PAYMENTS_CLOSED_KEY == "payments.real.closed"
    assert await production_payments_allowed(database) is True
    database.add(AppSetting(key=shop.PRODUCTION_PAYMENTS_CLOSED_KEY, value="1"))
    await database.commit()
    assert await production_payments_allowed(database) is False


def test_content_upload_endpoints_exist():
    assert not missing_routes("POST /api/admin/bot/start-image", "POST /api/admin/miniapp/image")


@pytest.mark.asyncio
async def test_public_config_shows_only_public_settings(database):
    database.add_all([AppSetting(key="app_name", value="Корги"), AppSetting(key="bot_start_image", value="/media/start.png"),
                      AppSetting(key="staging_e2e.config", value="ENCRYPTED-STAGING"), AppSetting(key="backup_password", value="BACKUP-PASS")])
    await database.commit()
    out = await shop.public_config(database)
    text = str(out)
    assert "/media/start.png" in text and "Корги" in text
    assert "ENCRYPTED-STAGING" not in text and "BACKUP-PASS" not in text


def test_miniapp_consumes_configured_buttons_and_images():
    s = __import__('frontend_sources').miniapp_sources()
    assert 'runButton' in s
    assert 'm.background_image' in s
    assert 'm.image' in s


def test_bot_consumes_start_image():
    s = read('backend/app/bot_banners.py')
    assert 'bot_start_image' in s
    assert 'answer_photo' in s
