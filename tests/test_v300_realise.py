"""3.0.0-realise production audit contracts."""
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app import main as shop
from app.models import AuditLog, FeatureFlag
from app_contract import permissions, revision
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_release_identity_and_docs():
    notes = (ROOT / "docs/archive/root/RELEASE_NOTES_V3_0_0.md").read_text()
    readme = (ROOT / "docs/archive/README_BEFORE_WORKSPACE.md").read_text()
    checklist = (ROOT / "docs/archive/instructions_before_21_0_1/PRODUCTION_CHECKLIST.md").read_text()
    instruction = (ROOT / "docs/archive/INSTRUCTION_BEFORE_ALPHA_6.md").read_text()
    assert "3.0.0-realise" in notes and "Русский" in notes and "English" in notes
    assert "3.0.0-realise" in readme and "2.13.0" in readme
    assert "личный кабинет" in readme
    assert "Конструктор тарифов" in readme
    assert "## Русский" in checklist and "## English" in checklist
    assert "9.12" in instruction
    assert "0038_v2_6_0_platform" in notes


def test_package_upload_limit_and_auth_order():
    import inspect

    from app import mobile_catalog
    assert shop.PACKAGE_UPLOAD_BYTES == mobile_catalog.MAX_PACKAGE_BYTES == 80 * 1024 * 1024
    for route in ("/api/admin/apps/{app_id}/file", "/api/admin/apps/logo"):
        assert permissions("POST", route) == {"manage_content"}, route
    for handler in (mobile_catalog.upload_app_file, mobile_catalog.upload_client_logo):
        params = list(inspect.signature(handler).parameters)
        assert params.index("admin") < params.index("file"), "the permission is resolved before the upload is read"


@pytest.mark.asyncio
async def test_an_oversized_body_is_refused_before_it_is_read():
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=shop.app), base_url="http://localhost") as client:
        big = await client.post("/api/payments/create", content=b"{}", headers={"content-length": str(shop.MAX_REQUEST_BYTES + 1),
                                                                               "content-type": "application/json"})
    assert big.status_code == 413


@pytest.mark.asyncio
async def test_health_summary_does_not_show_internal_errors(database, monkeypatch):
    class Down:
        async def list_nodes(self, **kw):
            raise RuntimeError("token=SECRET-PANEL-TOKEN at 10.0.0.5")
    monkeypatch.setattr(shop, "RemnawaveClient", Down)
    monkeypatch.setattr(shop, "redis_client", None)
    out = await shop.health_summary(database, SimpleNamespace(email="a@b.c"))
    assert {"name": "Remnawave", "status": "error", "error": "unavailable"} in out["checks"]
    assert "SECRET" not in str(out) and "10.0.0.5" not in str(out)


@pytest.mark.asyncio
async def test_feature_flags_are_loaded_by_key(database):
    database.add_all([FeatureFlag(id=1, key="gifts", enabled=True), FeatureFlag(id=2, key="payments", enabled=False)])
    await database.commit()
    assert (await shop._feature_flag(database, "payments")).enabled is False, "looked up by key, not by primary key"
    assert await shop._feature_flag(database, "missing") is None


@pytest.mark.asyncio
async def test_audit_keeps_the_request_id_and_decimal_prices(database):
    token = shop._REQUEST_ID.set("req-77")
    try:
        await shop.audit(database, "plan.updated", "a@b.c", "1", {"price": Decimal("199.90"), "at": datetime(2026, 1, 2)})
        await database.commit()
    finally:
        shop._REQUEST_ID.reset(token)
    row = await database.scalar(select(AuditLog).where(AuditLog.action == "plan.updated"))
    assert row.request_id == "req-77" and json.loads(row.details) == {"price": "199.90", "at": "2026-01-02T00:00:00"}


def test_scrypt_password_hashes_verify():
    from app.security import hash_password, verify_password
    encoded = hash_password("correct horse")
    assert encoded.startswith("scrypt$32768$8$1$")
    assert verify_password("correct horse", encoded) and not verify_password("wrong", encoded)


@pytest.mark.asyncio
async def test_alembic_version_column_fits_long_revision_ids():
    long_ids = [r for r in ("0025_v44_5_8_entitlement_idempotency", "0030_v44_5_16_privacy_and_refund_integrity") if revision(r)]
    assert long_ids and all(len(r) > 32 for r in long_ids)
    url = os.environ.get("AUDIT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("checked on the migrated PostgreSQL in CI")
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            size = await conn.scalar(text("SELECT character_maximum_length FROM information_schema.columns "
                                          "WHERE table_name = 'alembic_version' AND column_name = 'version_num' LIMIT 1"))
    finally:
        await engine.dispose()
    assert size == 128


def test_helpers_accept_caddy_and_package_size(monkeypatch, tmp_path):
    import ipaddress
    import sys

    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
    sys.path.insert(0, str(ROOT / "backend"))
    from app.main import PACKAGE_UPLOAD_BYTES, _peer_is_trusted_proxy, _request_body_limit

    from app.config import settings
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "172.30.84.2/32")
    assert _peer_is_trusted_proxy("172.30.84.2") is True
    assert _peer_is_trusted_proxy("127.0.0.1") is False
    assert _peer_is_trusted_proxy("10.1.2.3") is False
    assert _peer_is_trusted_proxy("203.0.113.9") is False
    assert _peer_is_trusted_proxy("testclient") is False
    assert _request_body_limit("POST", "/api/admin/apps/android-user/file") == PACKAGE_UPLOAD_BYTES
    assert _request_body_limit("POST", "/api/admin/apps/ios-admin/file") == PACKAGE_UPLOAD_BYTES
    assert _request_body_limit("POST", "/api/payments/create") == 12 * 1024 * 1024
    assert _request_body_limit("GET", "/api/admin/apps/android-user/file") == 12 * 1024 * 1024
    assert ipaddress.ip_address("203.0.113.9").is_global is False


def test_x_forwarded_for_is_trusted_only_from_the_proxy(monkeypatch):
    from starlette.requests import Request
    monkeypatch.setattr(shop.settings, "trusted_proxy_cidrs", "172.30.84.2/32")

    def req(peer, forwarded):
        return Request({"type": "http", "method": "GET", "path": "/", "client": (peer, 1), "query_string": b"",
                        "headers": [(b"x-forwarded-for", forwarded.encode())]})
    assert shop._client_ip(req("172.30.84.2", "198.51.100.7, 172.30.84.2")) == "198.51.100.7"
    assert shop._client_ip(req("203.0.113.9", "198.51.100.7")) == "203.0.113.9", "a client cannot pick its own address"
    assert shop._client_ip(req("172.30.84.2", "not-an-ip")) == "172.30.84.2"
