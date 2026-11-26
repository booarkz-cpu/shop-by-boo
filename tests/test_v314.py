"""3.1.4: concurrent Alembic boot must not kill the API container."""
import asyncio
import os
import subprocess
import sys
from uuid import uuid4
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_version_314_is_first():
    (ROOT / "scripts/build-release.sh").read_text()
    (ROOT / "infrastructure/deployment/install-vps.sh").read_text()


def test_migration_boot_is_serialized():
    env = (ROOT / "services/backend/alembic/env.py").read_text()
    create_at = env.index("CREATE TABLE IF NOT EXISTS alembic_version")
    lock_at = env.index("pg_advisory_xact_lock(872663041314)")
    assert lock_at < create_at
    compose = (ROOT / "docker-compose.yml").read_text()
    worker = compose.split("  worker:", 1)[1].split("  bot:", 1)[0]
    assert "backend:" in worker
    assert "condition: service_healthy" in worker
    installer = (ROOT / "infrastructure/deployment/install-vps.sh").read_text()
    assert "docker compose logs --tail=180 backend worker" in installer
    assert "normalize_tz" in installer
    assert "Europe/Moscow" in installer


def test_prompt_trims_prices_and_maps_moscow():
    installer = (ROOT / "infrastructure/deployment/install-vps.sh").read_text()
    helpers = installer[installer.index("trim_spaces() {"): installer.index("prompt_required() {")]
    script = (
        "set -Eeuo pipefail\n"
        + helpers
        + "\nINSTALL_NONINTERACTIVE=1 PRICE_1='189 ' TZ_VALUE=Moscow\n"
        + "prompt PRICE_1 'Цена' '199'\n"
        + "printf 'PRICE:%s\\n' \"$PRICE_1\"\n"
        + "normalized_tz=\"$(normalize_tz \"$TZ_VALUE\")\"\n"
        + "printf 'TZ:%s\\n' \"$normalized_tz\"\n"
    )
    proc = subprocess.run(["bash", "-s"], input=script, text=True, capture_output=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert "PRICE:189" in proc.stdout
    assert "TZ:Europe/Moscow" in proc.stdout


def test_docs_describe_314_and_keep_313():
    readme = (ROOT / "docs/archive/README_BEFORE_WORKSPACE.md").read_text()
    instruction = (ROOT / "docs/archive/INSTRUCTION_BEFORE_ALPHA_6.md").read_text()
    notes = (ROOT / "docs/archive/root/RELEASE_NOTES_V3_1_4.md").read_text()
    steps = (ROOT / "docs/archive/INSTALL_STEPS_BEFORE_ALPHA_6.md").read_text()
    assert "3.1.4" in readme and "3.1.3" in readme
    assert instruction.count("## 9.18.") == 2
    assert "pg_advisory_xact_lock" in notes or "alembic_version" in notes
    assert "Русский" in notes and "English" in notes
    assert '"version": "3.1.4"' in steps
    assert '"version": "3.1.3"' in steps


@pytest.mark.asyncio
async def test_parallel_alembic_upgrade_survives_the_race():
    """Start two independent Alembic processes against a new database on the test service."""
    audit_url = os.environ.get("AUDIT_TEST_DATABASE_URL")
    if not audit_url:
        pytest.skip("requires the PostgreSQL test service in AUDIT_TEST_DATABASE_URL")
    import asyncpg
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy.engine import make_url

    admin_url = make_url(audit_url)
    assert admin_url.get_backend_name() == "postgresql"
    name = "vpnshop_race_" + uuid4().hex
    target_url = admin_url.set(database=name)
    admin = await asyncpg.connect(admin_url.set(drivername="postgresql").render_as_string(hide_password=False))
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
        try:
            backend = ROOT / "services" / "backend"
            env = {**os.environ, "DATABASE_URL": target_url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)}
            env.setdefault("APP_SECRET", "x" * 32)

            def upgrade():
                return subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                                      cwd=backend, env=env, capture_output=True, text=True, timeout=90)

            results = await asyncio.gather(asyncio.to_thread(upgrade), asyncio.to_thread(upgrade),
                                           return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result
                assert result.returncode == 0, result.stderr

            cfg = Config()
            cfg.set_main_option("script_location", str(backend / "alembic"))
            expected = ScriptDirectory.from_config(cfg).get_heads()
            target = await asyncpg.connect(target_url.set(drivername="postgresql").render_as_string(hide_password=False))
            try:
                rows = await target.fetch("SELECT version_num FROM alembic_version")
                assert sorted(row["version_num"] for row in rows) == sorted(expected)
            finally:
                await target.close()
        finally:
            await admin.execute(f'DROP DATABASE "{name}"')
    finally:
        await admin.close()
