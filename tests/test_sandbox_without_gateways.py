"""Contracts for gateway-free checkout and the production sandbox ban."""
import hashlib
import hmac
import time
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import main as shop
from app import sandbox_mode
from app.models import Base, Plan

ROOT = Path(__file__).resolve().parents[1]


def sandbox(monkeypatch, env="development", on=True, live=False, panel=False):
    s = sandbox_mode.settings
    monkeypatch.setattr(s, "app_env", env)
    monkeypatch.setattr(s, "payments_sandbox", on)
    monkeypatch.setattr(s, "yookassa_shop_id", "shop" if live else "")
    monkeypatch.setattr(s, "yookassa_secret_key", "key" if live else "")
    monkeypatch.setattr(s, "platega_merchant_id", "")
    monkeypatch.setattr(s, "rollypay_api_key", "")
    monkeypatch.setattr(s, "remnawave_url", "https://panel.example" if panel else "")
    monkeypatch.setattr(s, "remnawave_token", "t" if panel else "")


def test_sandbox_is_never_used_in_production(monkeypatch):
    assert "production" not in sandbox_mode.SANDBOX_ENVS
    sandbox(monkeypatch, env="production")
    assert not sandbox_mode.payments_sandbox_allowed() and not sandbox_mode.sandbox_checkout_requested("sandbox")
    sandbox(monkeypatch)
    assert sandbox_mode.sandbox_checkout_requested("") and sandbox_mode.sandbox_checkout_requested("sandbox")
    assert not sandbox_mode.sandbox_checkout_requested("yookassa"), "a named live provider is never rewritten"
    sandbox(monkeypatch, live=True)
    assert not sandbox_mode.sandbox_checkout_requested(""), "with a live gateway the default checkout is real"
    sandbox(monkeypatch, panel=False)
    assert sandbox_mode.sandbox_local_vpn()
    sandbox(monkeypatch, panel=True)
    assert not sandbox_mode.sandbox_local_vpn(), "with Remnawave connected the sandbox issues real panel users"


@pytest.mark.asyncio
async def test_a_sandbox_shop_starts_with_a_test_plan(monkeypatch):
    sandbox(monkeypatch)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as db:
        assert await shop.seed_starter_plans(db) == 1
        await db.commit()
        assert (await db.execute(select(Plan.name))).scalars().all() == ["Тестовый месяц"]
        assert await shop.seed_starter_plans(db) == 0, "an existing catalogue is never touched"
    await engine.dispose()


def test_rollypay_webhooks_need_a_fresh_valid_signature(monkeypatch):
    from app import payments
    monkeypatch.setattr(payments.settings, "rollypay_signing_secret", "sign")
    body = b'{"order_id":"o-1","status":"paid"}'
    now = str(int(time.time()))
    good = hmac.new(b"sign", now.encode() + b"." + body, hashlib.sha256).hexdigest()
    provider = payments.RollyPayProvider()
    provider.verify_webhook({"X-Timestamp": now, "X-Signature": good}, body)
    old = str(int(time.time()) - 600)
    stale = hmac.new(b"sign", old.encode() + b"." + body, hashlib.sha256).hexdigest()
    for headers in ({"X-Timestamp": now, "X-Signature": "0" * 64}, {"X-Timestamp": old, "X-Signature": stale}, {}):
        with pytest.raises(payments.SignatureVerificationError):
            provider.verify_webhook(headers, body)


def test_sandbox_test_stack_files():
    assert (ROOT / "docker-compose.test.yml").is_file()
    assert (ROOT / "scripts/test-up.sh").is_file()
    assert "PAYMENTS_SANDBOX=true" in (ROOT / ".env.test.example").read_text()
    assert "APP_ENV=development" in (ROOT / ".env.test.example").read_text()
    compose = (ROOT / "docker-compose.test.yml").read_text()
    opener = (ROOT / "scripts/open-ports.sh").read_text()
    installer = (ROOT / "deploy/install-vps.sh").read_text()
    assert '"127.0.0.1:18080:8000"' in compose
    assert '"127.0.0.1:18081:80"' in compose
    assert "--env-file .env.test" in (ROOT / "scripts/test-up.sh").read_text()
    assert "open-ports.sh" in installer
    assert "ufw allow 80/tcp" in installer
    assert "18080:18083/tcp" in opener
    assert "443/udp" in opener
    assert "8000/tcp" not in opener
    assert "8000/tcp" not in installer
