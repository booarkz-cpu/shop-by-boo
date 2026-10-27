import hashlib
import hmac
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_rollypay_refund_is_signed_with_a_fresh_nonce(monkeypatch):
    from app import payments
    sent = []

    class Client:
        async def post(self, url, content, headers):
            sent.append((url, content, headers))
            return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: {"id": "rf-1", "status": "processing"}})()

    @asynccontextmanager
    async def client(timeout):
        yield Client()
    monkeypatch.setattr(payments, "_public_client", client)
    monkeypatch.setattr(payments.settings, "rollypay_refund_url", "https://rollypay.example/refunds")
    monkeypatch.setattr(payments.settings, "rollypay_signing_secret", "sign-key")
    provider = payments.RollyPayProvider()
    assert await provider.refund("p-1", 100, "RUB", "возврат") == {"id": "rf-1", "status": "processing"}
    await provider.refund("p-1", 100, "RUB", "возврат")
    (_, body, first), (_, _, second) = sent
    assert first["X-Nonce"] != second["X-Nonce"], "every request gets its own nonce"
    assert first["Idempotence-Key"] == second["Idempotence-Key"] == "refund-p-1", "but the refund itself is idempotent"
    assert first["X-Signature"] == hmac.new(b"sign-key", body, hashlib.sha256).hexdigest()

def test_frontend_builds_require_lockfiles():
    for d in ("admin","miniapp"):
        text=(ROOT/d/"Dockerfile").read_text()
        assert ('COPY cabinet/package*.json ./' if d == 'miniapp' else 'COPY admin/package*.json ./') in text
        assert 'npm ci' in text and 'npm install --package-lock=false' in text

def test_rollback_is_fail_closed():
    text=(ROOT/"scripts/rollback.sh").read_text()
    assert 'DATABASE SNAPSHOT' in text or 'Database snapshot is required' in text
    assert 'docker compose up -d db redis' in text
    assert 'doctor.sh' in text

def test_update_does_not_ignore_doctor_failure():
    text=(ROOT/"scripts/update.sh").read_text()
    assert './scripts/doctor.sh || true' not in text

def test_worker_identity_is_unique(monkeypatch):
    import os
    import socket

    import worker
    monkeypatch.delenv("WORKER_ID", raising=False)
    assert worker.worker_identity() == f"{worker.settings.worker_role}:{socket.gethostname()}:{os.getpid()}"
    monkeypatch.setenv("WORKER_ID", "worker-blue")
    assert worker.worker_identity() == "worker-blue"

def test_digest_pinning_is_enforced():
    text=(ROOT/"scripts/preflight.sh").read_text()
    assert 'REDIS_IMAGE=.*@sha256:' in text
    assert 'POSTGRES_IMAGE=.*@sha256:' in text
    assert 'CADDY_IMAGE=.*@sha256:' in text

def test_release_signature_verifier_exists():
    assert (ROOT/"scripts/verify-release.sh").exists()
    assert (ROOT/"release-manifest.template.json").exists()
    text=(ROOT/"scripts/verify-release.sh").read_text()
    assert 'DEFAULT_MANIFEST' in text and '_manifest.json' in text

def test_v30_migration_exists():
    assert (ROOT/"backend/alembic/versions/0014_v30_final_hardening.py").exists()
