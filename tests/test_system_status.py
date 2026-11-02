"""v28.62.0 (stage 6): System Control Center — «Состояние системы» shows every part of the installation.

Each check is read-only, has a status (ok / warn / error / off), a sentence of detail and the admin section
where the part is managed. A failure of one part never hides the others and never leaks a secret."""
import json
import re
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app import system_status
from app.models import BackupJob, Job, PaymentProviderHealth, WorkerState
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
ADMIN = SimpleNamespace(email="root@example.test", role="admin")
KEYS = ["backend", "frontend", "database", "migrations", "redis", "remnawave", "nodes", "caddy", "tls", "payments", "jobs", "backup", "telegram", "updates"]


@pytest.fixture(autouse=True)
def fresh_update_cache(monkeypatch):
    monkeypatch.setattr(system_status, "_update_cache", {"at": 0.0, "value": None})


class Redis:
    def __init__(self, fail=False):
        self.fail = fail

    async def ping(self):
        if self.fail:
            raise ConnectionError("redis://:hunter2@redis:6379 refused")
        return True


def remnawave(payload=None, exc=None):
    class Client:
        async def list_nodes(self, start=0, size=25):
            if exc:
                raise exc
            return payload
    return Client


def release(tag):
    name = f"remnawave_vpn_shop_v{tag[1:].replace('.', '_')}_full_release"
    prefix = f"https://github.com/booarkz-cpu/shop-by-boo/releases/download/{tag}/"
    return {"tag_name": tag, "assets": [{"name": n, "browser_download_url": prefix + n}
                                        for n in (f"{name}.zip", f"{name}.zip.sha256", f"{name}_manifest.json")]}


def test_overall_status():
    assert system_status.overall([{"status": "ok"}, {"status": "off"}]) == "ok"
    assert system_status.overall([{"status": "ok"}, {"status": "warn"}]) == "attention"
    assert system_status.overall([{"status": "warn"}, {"status": "error"}]) == "degraded"


def test_migration_head_is_read_from_the_shipped_scripts():
    head = system_status.migration_head()
    assert head and (ROOT / "backend/alembic/versions" / f"{head}.py").exists()


@pytest.mark.asyncio
async def test_database_and_migration_marker(database):
    db = database
    rows = await system_status.database_checks(db)
    assert rows[0]["status"] == "ok" and rows[1]["key"] == "migrations" and rows[1]["status"] == "error"
    await db.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
    await db.execute(text("INSERT INTO alembic_version VALUES ('0001_old')"))
    await db.commit()
    rows = await system_status.database_checks(db)
    assert rows[1]["status"] == "error" and "0001_old" in rows[1]["detail"] and system_status.migration_head() in rows[1]["detail"]
    await db.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": system_status.migration_head()})
    await db.commit()
    assert (await system_status.database_checks(db))[1]["status"] == "ok"


@pytest.mark.asyncio
async def test_frontends():
    async def up(service):
        return 200
    assert (await system_status.frontend_check(up))["status"] == "ok"

    async def cabinet_down(service):
        if service == "cabinet":
            raise OSError("connection refused")
        return 200
    row = await system_status.frontend_check(cabinet_down)
    assert row["status"] == "error" and "кабинет" in row["detail"] and "админка" not in row["detail"]

    async def broken(service):
        return 502
    assert "ни один" in (await system_status.frontend_check(broken))["detail"]


@pytest.mark.asyncio
async def test_redis():
    assert (await system_status.redis_check(None))["status"] == "error"
    ok = await system_status.redis_check(Redis())
    assert ok["status"] == "ok" and ok["latency_ms"] >= 0
    broken = await system_status.redis_check(Redis(fail=True))
    assert broken["status"] == "error" and "hunter2" not in json.dumps(broken)


@pytest.mark.asyncio
async def test_remnawave_and_nodes():
    from app.remnawave import RemnawaveError, RemnawaveNotConfigured
    off = await system_status.remnawave_checks(remnawave(exc=RemnawaveNotConfigured("no url")))
    assert [r["status"] for r in off] == ["off", "off"] and off[0]["tab"] == "remnawave" and off[1]["tab"] == "nodes"
    broken = await system_status.remnawave_checks(remnawave(exc=RemnawaveError("401 token=abc secret body")))
    assert [r["status"] for r in broken] == ["error", "error"] and "secret body" not in json.dumps(broken)
    nodes = {"response": [{"isConnected": True}, {"isConnected": False}, {"isDisabled": True}]}
    rows = await system_status.remnawave_checks(remnawave(nodes))
    assert rows[0]["status"] == "ok" and rows[1]["status"] == "warn" and "1 из 2" in rows[1]["detail"]
    rows = await system_status.remnawave_checks(remnawave({"response": [{"isConnected": False}]}))
    assert rows[1]["status"] == "error"
    rows = await system_status.remnawave_checks(remnawave({"response": []}))
    assert rows[1]["status"] == "warn"
    rows = await system_status.remnawave_checks(remnawave({"response": [{"isConnected": True}, {"isDisabled": True}]}))
    assert rows[1]["status"] == "ok"


@pytest.mark.asyncio
async def test_reverse_proxy_and_certificates(monkeypatch):
    s = system_status.settings
    for field in ("api_domain", "admin_domain", "cabinet_domain", "app_domain"):
        monkeypatch.setattr(s, field, "localhost")
    assert [r["status"] for r in await system_status.proxy_checks()] == ["off", "off"]

    monkeypatch.setattr(s, "api_domain", "api.corgi.test")
    monkeypatch.setattr(s, "admin_domain", "admin.corgi.test")
    now = datetime.now(timezone.utc)
    ends = {}

    async def probe(domain):
        value = ends[domain]
        if isinstance(value, Exception):
            raise value
        return value

    ends.update({"api.corgi.test": now + timedelta(days=80), "admin.corgi.test": now + timedelta(days=60)})
    caddy, tls = await system_status.proxy_checks(probe)
    assert caddy["status"] == "ok" and tls["status"] == "ok" and "2 доменов" in tls["detail"]
    ends["admin.corgi.test"] = now + timedelta(days=3)
    assert (await system_status.proxy_checks(probe))[1]["status"] == "warn"
    ends["admin.corgi.test"] = ssl.SSLCertVerificationError("certificate has expired")
    caddy, tls = await system_status.proxy_checks(probe)
    assert caddy["status"] == "ok" and tls["status"] == "error" and "admin.corgi.test" in tls["detail"]
    ends.update({d: ConnectionRefusedError() for d in ends})
    caddy, tls = await system_status.proxy_checks(probe)
    assert caddy["status"] == "error" and tls["status"] == "error"


@pytest.mark.asyncio
async def test_payments(database, monkeypatch):
    db = database
    s = system_status.settings
    from app.payment_policy import PAYMENT_AGENTS
    from app.gateways import GATEWAYS
    for name in {k for p in PAYMENT_AGENTS for k in (GATEWAYS[p].keys if p in GATEWAYS else ())} | {
            "yookassa_shop_id", "yookassa_secret_key", "platega_merchant_id", "platega_secret", "rollypay_api_key",
            "rollypay_signing_secret", "cryptobot_token", "freekassa_shop_id", "freekassa_secret1", "freekassa_secret2", "freekassa_api_key"}:
        monkeypatch.setattr(s, name, "")
    monkeypatch.setattr(s, "payments_sandbox", False)
    assert (await system_status.payments_check(db, False))["status"] == "error"
    monkeypatch.setattr(s, "payments_sandbox", True)
    assert (await system_status.payments_check(db, False))["status"] == "off"
    monkeypatch.setattr(s, "cryptobot_token", "12345:SECRET-TOKEN")
    ok = await system_status.payments_check(db, False)
    assert ok["status"] == "ok" and "cryptobot" in ok["detail"] and "SECRET" not in json.dumps(ok)
    assert (await system_status.payments_check(db, True))["status"] == "warn"
    db.add(PaymentProviderHealth(provider="cryptobot", circuit_open_until=datetime.utcnow() + timedelta(minutes=5)))
    await db.commit()
    assert (await system_status.payments_check(db, False))["status"] == "error"


@pytest.mark.asyncio
async def test_background_jobs(database):
    db = database
    role = system_status.settings.worker_role
    assert (await system_status.jobs_check(db))["status"] == "error"
    db.add(WorkerState(worker_id="w1", role=role, status="online", last_seen_at=datetime.utcnow()))
    await db.commit()
    assert (await system_status.jobs_check(db))["status"] == "ok"
    old = datetime.utcnow() - timedelta(hours=1)
    db.add(Job(job_key="j1", kind="fulfillment", status="queued", created_at=old))
    db.add(Job(job_key="j2", kind="fulfillment", status="failed", created_at=datetime.utcnow()))
    await db.commit()
    row = await system_status.jobs_check(db)
    assert row["status"] == "warn" and "1." in row["detail"] and row["tab"] == "jobs"


@pytest.mark.asyncio
async def test_backups(database):
    db = database
    assert (await system_status.backup_check(db))["status"] == "error"
    db.add(BackupJob(status="completed", created_at=datetime.utcnow() - timedelta(days=3), finished_at=datetime.utcnow() - timedelta(days=3)))
    await db.commit()
    assert (await system_status.backup_check(db))["status"] == "warn"
    db.add(BackupJob(status="failed", created_at=datetime.utcnow()))
    db.add(BackupJob(status="completed", created_at=datetime.utcnow(), finished_at=datetime.utcnow()))
    await db.commit()
    assert (await system_status.backup_check(db))["status"] == "ok"


def test_telegram(monkeypatch):
    s = system_status.settings
    monkeypatch.setattr(s, "bot_token", "")
    assert system_status.telegram_check()["status"] == "off"
    monkeypatch.setattr(s, "bot_token", "123:SECRET")
    monkeypatch.setattr(s, "bot_username", "")
    assert system_status.telegram_check()["status"] == "warn"
    monkeypatch.setattr(s, "bot_username", "corgi_bot")
    row = system_status.telegram_check()
    assert row["status"] == "ok" and "@corgi_bot" in row["detail"] and "SECRET" not in json.dumps(row)


@pytest.mark.asyncio
async def test_updates_are_cached_and_never_block():
    calls = []

    async def newer():
        calls.append(1)
        return release("v99.0.0")

    row = await system_status.updates_check("21.5.1", "v28.62.0", newer)
    assert row["status"] == "warn" and "v99.0.0" in row["detail"]
    await system_status.updates_check("21.5.1", "v28.62.0", newer)
    assert len(calls) == 1, "the GitHub answer is cached"

    system_status._update_cache.update(at=0.0, value=None)

    async def same():
        return release("v28.62.0")
    assert (await system_status.updates_check("21.5.1", "v28.62.0", same))["status"] == "ok"

    system_status._update_cache.update(at=0.0, value=None)

    async def down():
        raise RuntimeError("github down")
    assert (await system_status.updates_check("21.5.1", "v28.62.0", down))["status"] == "warn"


@pytest.mark.asyncio
async def test_summary_endpoint_lists_every_part_with_a_real_section(database, monkeypatch):
    from app import admin_api, main as shop
    import app.github_update as github_update

    async def latest():
        return release("v28.62.0")

    monkeypatch.setattr(github_update, "fetch_latest_release", latest)
    monkeypatch.setattr(shop, "redis_client", Redis())
    monkeypatch.setattr(shop, "RemnawaveClient", remnawave({"response": [{"isConnected": True}]}))
    monkeypatch.setattr(system_status.settings, "bot_token", "999:TOP-SECRET")

    async def up(service):
        return 200
    monkeypatch.setattr(system_status, "frontend_page", up)
    monkeypatch.setattr(system_status.frontend_check, "__defaults__", (up,))
    data = await admin_api.health_summary(db=database, admin=ADMIN)
    assert [c["key"] for c in data["checks"]] == KEYS
    tabs = set(re.findall(r'\{tab: "([A-Za-z0-9]+)"', (ROOT / "admin/src/sections.ts").read_text()))
    for row in data["checks"]:
        assert row["status"] in {"ok", "warn", "error", "off"} and row["detail"] and row["tab"] in tabs, row
    assert data["status"] in {"ok", "attention", "degraded"} and "TOP-SECRET" not in json.dumps(data, default=str)
    assert {c["key"]: c["status"] for c in data["checks"]}["redis"] == "ok"


@pytest.mark.asyncio
async def test_certificate_probe_verifies_the_chain(tmp_path):
    """The real probe opens TLS with the domain as SNI and refuses a certificate the system does not trust."""
    import asyncio
    import shutil
    import subprocess
    if not shutil.which("openssl"):
        pytest.skip("openssl is not installed")
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=shop.corgi.test",
                    "-addext", "subjectAltName=DNS:shop.corgi.test", "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(cert, key)

    async def handle(reader, writer):
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_ctx)
    port = server.sockets[0].getsockname()[1]
    try:
        with pytest.raises(ssl.SSLCertVerificationError):
            await system_status.certificate_expiry("shop.corgi.test", host="127.0.0.1", port=port)
    finally:
        server.close()
        await server.wait_closed()
    with pytest.raises(OSError):
        await system_status.certificate_expiry("shop.corgi.test", host="127.0.0.1", port=port)
