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


@pytest.mark.parametrize("scenario", ["success", "partial-start", "existing-volume", "remote-daemon"])
def test_integration_cleanup_is_scoped_to_a_disposable_project(tmp_path, scenario):
    import json
    import os
    import re
    import shutil
    import subprocess
    import sys

    repo = tmp_path / "checkout"
    repo.mkdir()
    for name in ("scripts/integration-test.sh", ".env.test.example", "support-pro/README.txt"):
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, target)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=test@example.test",
                    "-c", "user.name=Test", "commit", "-qm", "fixture"], check=True)
    (repo / ".env").write_text("BOT_TOKEN=external-sentinel\n")

    tools = tmp_path / "bin"
    tools.mkdir()
    trace, fixture = tmp_path / "calls", tmp_path / "fixture"
    docker = tools / "docker"
    docker.write_text(f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open({str(trace)!r}, "a") as out:
    print(json.dumps([os.getcwd(), args, os.getenv("COMPOSE_PROJECT_NAME"), os.getenv("BOT_TOKEN")]), file=out)
if args[:2] == ["volume", "ls"] and {scenario!r} == "existing-volume":
    print("previous-volume")
if args[0] == "compose" and "up" in args:
    Path({str(fixture)!r}).write_bytes(Path(".env").read_bytes())
    sys.exit(37 if {scenario!r} == "partial-start" else 0)
if args[0] == "compose" and "port" in args:
    print("127.0.0.1:44123")
""")
    docker.chmod(0o755)
    curl = tools / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n")
    curl.chmod(0o755)
    host = "ssh://example.test" if scenario == "remote-daemon" else "unix:///var/run/docker.sock"
    env = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}", COMPOSE_PROJECT_NAME="production",
               BOT_TOKEN="external-sentinel", DATABASE_URL="external-sentinel", DOCKER_HOST=host, TMPDIR=str(tmp_path))
    result = subprocess.run(["bash", str(repo / "scripts/integration-test.sh")], env=env,
                            capture_output=True, text=True, timeout=40)
    assert (repo / ".env").read_text() == "BOT_TOKEN=external-sentinel\n"
    if scenario == "remote-daemon":
        assert result.returncode != 0 and not trace.exists()
        return
    calls = [json.loads(line) for line in trace.read_text().splitlines()]
    assert not any(project or token for _, _, project, token in calls)
    commands = [args for _, args, _, _ in calls if args[0] == "compose"]
    if scenario == "existing-volume":
        assert result.returncode != 0 and commands == []
        return
    assert result.returncode == (37 if scenario == "partial-start" else 0), result.stderr
    projects = {args[args.index("--project-name") + 1] for args in commands}
    assert len(projects) == 1 and re.fullmatch(r"corgi-integration-[a-f0-9]{32}", projects.pop())
    assert all(Path(cwd) != repo and not Path(cwd).exists() for cwd, *_ in calls)
    assert "down" in commands[-1] and "--volumes" in commands[-1]
    settings = fixture.read_text()
    values = dict(line.split("=", 1) for line in settings.splitlines() if line and not line.startswith("#"))
    assert "external-sentinel" not in settings and not any("CHANGE_ME" in value for value in values.values())
    assert values["PAYMENTS_SANDBOX"] == "true" and values["BOT_TOKEN"] == ""


def test_integration_api_is_published_only_on_loopback():
    import yaml

    spec = yaml.safe_load((ROOT / "docker-compose.integration.yml").read_text())
    assert spec["services"]["backend"]["ports"] == ["127.0.0.1:${INTEGRATION_API_PORT-18000}:8000"]
    suite = spec["services"]["integration_tests"]
    assert suite["read_only"] and suite["volumes"] == [".:/project:ro"]
    assert suite["environment"]["AUDIT_TEST_DATABASE_URL"].endswith("/integration_pytest")
    assert suite["command"] == ["tests"]


def test_v29_migration_exists():
    from app_contract import revision
    assert revision("0013_v29_final_hardening") is not None
