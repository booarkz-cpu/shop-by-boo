"""v29 final hardening, checked by running the code (was: code lines searched in main.py and payments.py).
The remote-expiry reconciliation of extensions runs in test_integration_billing_vpn.py."""
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main as shop
from app.models import Payment, ReferralLedger, RefundRequest, User, WithdrawalRequest
from app_contract import permissions
from test_behaviour_payments_v2 import checkout
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).parents[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("name,setting", [("PlategaProvider", "platega_refund_url"), ("RollyPayProvider", "rollypay_refund_url")])
async def test_provider_refunds_go_to_their_own_provider(monkeypatch, name, setting):
    from app import payments
    posted = []

    class Client:
        async def post(self, url, **kw):
            posted.append(url)
            return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: {"id": "rf-9"}})()

    @asynccontextmanager
    async def client(timeout):
        yield Client()
    monkeypatch.setattr(payments, "_public_client", client)
    provider = getattr(payments, name)()
    monkeypatch.setattr(payments.settings, setting, "")
    with pytest.raises(payments.PaymentError):
        await provider.refund("p-1", 100, "RUB")
    monkeypatch.setattr(payments.settings, setting, "https://refunds.provider.example/v1")
    await provider.refund("p-1", 100, "RUB")
    assert posted == ["https://refunds.provider.example/v1"], "never a YooKassa URL"


@pytest.mark.asyncio
async def test_a_withdrawal_takes_the_balance_once_and_a_rejection_returns_it(database, monkeypatch):
    if database.bind.dialect.name != "postgresql":
        pytest.skip("balance updates are atomic SQL on PostgreSQL (Decimal parameters, FOR UPDATE)")
    (await database.get(User, 1)).referral_balance = Decimal("50")
    await database.commit()
    request = checkout([(b"idempotency-key", b"w-1")])
    payload = shop.WithdrawalIn(amount=Decimal("30"), destination="card 2200…1234")
    first = await shop.request_withdrawal(payload, request, database)
    again = await shop.request_withdrawal(payload, request, database)
    assert first == again, "the same Idempotency-Key returns the same request"
    assert (await database.get(User, 1, populate_existing=True)).referral_balance == Decimal("20")
    with pytest.raises(HTTPException) as too_much:
        await shop.request_withdrawal(shop.WithdrawalIn(amount=Decimal("30"), destination="card"), checkout([(b"idempotency-key", b"w-2")]), database)
    assert too_much.value.detail == "Insufficient referral balance"
    await shop.reject_withdrawal(first["id"], None, database, SimpleNamespace(email="a@b.c"))
    assert (await database.get(User, 1, populate_existing=True)).referral_balance == Decimal("50")
    kinds = {r.kind for r in (await database.execute(select(ReferralLedger))).scalars()}
    assert {f"withdrawal:{first['id']}", f"withdrawal_reversal:{first['id']}"} <= kinds
    with pytest.raises(HTTPException):
        await shop.reject_withdrawal(first["id"], None, database, SimpleNamespace(email="a@b.c"))
    assert (await database.get(WithdrawalRequest, first["id"])).status == "rejected"


@pytest.mark.asyncio
async def test_a_failed_revoke_after_a_refund_can_be_retried(database, monkeypatch):
    database.add(Payment(id=80, user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="o-80", amount=Decimal("100"),
                         currency="RUB", status="refunded", fulfillment_status="completed", idempotency_key="k-80", duration_days_snapshot=30))
    database.add(RefundRequest(id=11, payment_id=80, user_id=1, amount=Decimal("100"), status="refunded_pending_revoke"))
    await database.commit()
    disabled = []

    class Panel:
        async def disable_user(self, uid):
            disabled.append(uid)
    monkeypatch.setattr(shop, "RemnawaveClient", Panel)
    out = await shop.retry_refund_revoke(11, database, SimpleNamespace(email="a@b.c"))
    assert out["status"] == "refunded" and disabled == ["remote-1"]
    with pytest.raises(HTTPException) as done:
        await shop.retry_refund_revoke(11, database, SimpleNamespace(email="a@b.c"))
    assert done.value.status_code == 404, "a finished refund is not revoked twice"


@pytest.mark.asyncio
async def test_secrets_status_reads_the_real_settings(monkeypatch):
    monkeypatch.setattr(shop.settings, "bot_token", "123:abc")
    monkeypatch.setattr(shop.settings, "remnawave_token", "")
    out = await shop.secret_status(SimpleNamespace(email="a@b.c"))
    assert out["TELEGRAM_BOT_TOKEN"] == "configured" and out["REMNAWAVE_API_TOKEN"] == "missing"
    assert "123:abc" not in str(out)
    assert permissions("GET", "/api/admin/security/secrets/status") == {"manage_admins"}


@pytest.mark.asyncio
async def test_a_backup_download_is_never_cached(database, monkeypatch, tmp_path):
    from app.models import BackupJob
    monkeypatch.setattr(shop.settings, "backups_dir", str(tmp_path))
    (tmp_path / "backup-1.tar.gz").write_bytes(b"x")
    database.add(BackupJob(id=5, status="completed", filename="backup-1.tar.gz"))
    await database.commit()
    response = await shop.download_backup(5, database, SimpleNamespace(email="a@b.c"))
    assert response.headers["Cache-Control"] == "private, no-store"


def test_rollback_excludes_secrets_and_has_db_dump():
    u = (ROOT / "scripts/update.sh").read_text()
    r = (ROOT / "scripts/rollback.sh").read_text()
    assert "--exclude='./.env'" in u and "--exclude='./.env.*'" in u
    assert "pg_dump" in u and "psql" in u and "DB_DUMP" in u
    assert "pg_dump" not in r or "psql" in r


def test_integration_uses_published_port():
    c = (ROOT / "docker-compose.integration.yml").read_text()
    t = (ROOT / "scripts/integration-test.sh").read_text()
    assert '"18000:8000"' in c and "localhost:18000/health" in t


def test_v29_migration_exists():
    from app_contract import revision
    assert revision("0013_v29_final_hardening") is not None
