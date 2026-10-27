"""3.1.2 panel leak audit contracts."""
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from app_contract import permissions
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_version_312_is_first():
    manifest = (ROOT / "release-manifest.template.json").read_text()
    assert '"version": "3.1.2"' in manifest
    assert '"previous_release": "3.1.1"' in manifest
    assert "remnawave_vpn_shop_v3_1_2_full_release.zip" in manifest


def test_remote_payload_and_audit_are_redacted():
    os.environ.setdefault("MEDIA_DIR", "/tmp/media")
    sys.path.insert(0, str(ROOT / "backend"))
    from app.main import _public_audit_details, _public_refund_reason, _remote_user_id
    from app.remnawave import redact_remote

    clean = redact_remote({
        "username": "buyer",
        "status": "ACTIVE",
        "subscriptionUrl": "https://secret.example/sub",
        "shortUuid": "abc",
        "trojanPassword": "secret",
        "response": {"users": [{"id": "1", "vlessUuid": "u", "ssPassword": "pw"}]},
    })
    assert clean["username"] == "buyer"
    assert clean["status"] == "ACTIVE"
    assert "subscriptionUrl" not in clean
    assert "shortUuid" not in clean
    assert "trojanPassword" not in clean
    assert clean["response"]["users"][0] == {"id": "1"}
    user_id = "550e8400-e29b-41d4-a716-446655440000"
    assert _remote_user_id(user_id) == user_id
    with pytest.raises(HTTPException) as bad:
        _remote_user_id("../etc/passwd")
    assert bad.value.status_code == 400
    assert bad.value.detail == "Некорректный идентификатор пользователя Remnawave"
    hidden = _public_audit_details('{"provider":"yookassa","error":"dsn leaked","nested":{"token":"abc"}}')
    assert "yookassa" in hidden
    assert "dsn leaked" not in hidden
    assert "abc" not in hidden
    assert hidden.count("unavailable") == 2
    assert _public_audit_details("оператор отметил инцидент") == "оператор отметил инцидент"
    assert _public_refund_reason("клиент просил\nRevoke pending: connection refused") == "клиент просил"
    assert _public_refund_reason("обычная причина") == "обычная причина"


def test_admin_routes_hide_credentials_and_stderr():
    for path in ("/api/admin/remnawave/users/{user_id}/subscription", "/api/admin/remnawave/users/{user_id}/keys"):
        assert permissions("GET", path) == {"users.keys"}, path
    provisioner = (ROOT / "backend/app/provisioner.py").read_text()
    body = provisioner[provisioner.index("def run_ssh"):]
    assert '"output"' not in body
    assert 'ProvisionError("Remote install failed")' in body
    assert "err[-4000:]" not in body.split("raise ProvisionError", 1)[1][:200]


def test_docs_describe_312_and_keep_311():
    readme = (ROOT / "docs/archive/README_BEFORE_WORKSPACE.md").read_text()
    security = (ROOT / "docs/archive/SECURITY_BEFORE_ALPHA_6.md").read_text()
    instruction = (ROOT / "docs/archive/INSTRUCTION_BEFORE_ALPHA_6.md").read_text()
    notes = (ROOT / "docs/archive/root/RELEASE_NOTES_V3_1_2.md").read_text()
    docs = (ROOT / "docs/archive/DOCUMENTATION_BEFORE_ALPHA_6.md").read_text()
    steps = (ROOT / "docs/archive/INSTALL_STEPS_BEFORE_ALPHA_6.md").read_text()
    ui = (ROOT / "admin/src/main.tsx").read_text()
    assert "3.1.2" in readme and "3.1.1" in readme and "3.1.0" in readme
    assert "личный кабинет" in readme and "Конструктор тарифов" in readme
    assert "9.16" in readme and "FULL_E2E_PASS" in readme
    assert "3.1.2" in security and "3.1.1" in security and "[скрыто]" in security and "FULL_E2E_PASS" in security
    assert instruction.count("## 9.16.") == 2
    assert instruction.count("## 9.15.") == 2
    assert "FULL_E2E_PASS" in instruction and "users.keys" in instruction
    assert "Русский" in notes and "English" in notes
    assert "2.10.0" in notes and "2.12.0" in notes and "0038_v2_6_0_platform" in notes
    assert "RELEASE_NOTES_V3_1_2.md" in docs and "INSTALL_STEPS.md" in docs and "RELEASE_NOTES_V3_1_1.md" in docs
    assert '"version": "3.1.2"' in steps
    assert "client-logo" not in ui


@pytest.mark.asyncio
async def test_admin_lists_hide_errors_and_stack_tails(database):
    from types import SimpleNamespace
    from decimal import Decimal

    from app import main as shop
    from app.models import AuditLog, MonitoringCheck, Payment, RefundRequest
    database.add_all([
        AuditLog(action="payment.failed", actor="system", details='{"provider":"yookassa","error":"postgres://u:pw@db","token":"t-1"}'),
        MonitoringCheck(name="api", url="https://status.example/x", last_error="ConnectError: 10.0.0.5:5432 refused"),
        Payment(id=95, user_id=1, plan_id=1, provider="yookassa", order_id="o-95", amount=Decimal("1"), currency="RUB", status="paid", idempotency_key="k-95"),
        RefundRequest(payment_id=95, user_id=1, amount=Decimal("1"), reason="клиент просил\nRevoke pending: ReadTimeout panel.internal:3000"),
    ])
    await database.commit()
    admin = SimpleNamespace(email="a@b.c", role="admin")
    shown = str(await shop.admin_audit(1, 50, database, admin)) + str(await shop.enterprise_monitoring(database, admin)) + str(await shop.admin_refunds(database, admin))
    for leak in ("postgres://", "t-1", "10.0.0.5", "panel.internal"):
        assert leak not in shown, leak
    assert "yookassa" in shown and "клиент просил" in shown
