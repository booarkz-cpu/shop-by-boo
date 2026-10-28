"""Runtime settings are typed, secret-safe, atomic and reversible."""

import asyncio
import importlib.util
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import runtime_settings as runtime
from app.config import Settings
from app.models import AppSetting, AuditLog, RuntimeSettingChange, RuntimeSettingState
from test_subscription_commerce import database


ACTOR = SimpleNamespace(email="owner@example.test", role="admin")


@pytest.fixture(autouse=True)
def isolate_process_settings(monkeypatch):
    previous_log_level = logging.getLogger().level
    for definition in runtime.DEFINITIONS:
        monkeypatch.setattr(runtime.settings, definition.env_attr, runtime.ENVIRONMENT_VALUES[definition.key])
    monkeypatch.setattr(runtime, "_loaded_version", -1)
    yield
    logging.getLogger().setLevel(previous_log_level)


def test_every_configuration_field_has_one_explicit_runtime_classification():
    hot = {definition.env_attr for definition in runtime.DEFINITIONS}
    deployment = {item["key"] for item in runtime.RESTART_REQUIRED}
    workflows = {item["key"] for item in runtime.MANAGED_ELSEWHERE}
    assert hot.isdisjoint(deployment)
    assert hot.isdisjoint(workflows)
    assert deployment.isdisjoint(workflows)
    assert hot | deployment | workflows == set(Settings.model_fields)
    assert len(hot) == 115  # v28.39.0: three settings of Pal24 and three of Mulen Pay


def test_integer_limits_are_checked_without_float_rounding():
    definition = runtime.DEFINITION_BY_KEY["admin_telegram_id"]
    assert runtime._parse_value(definition, 2**63 - 1) == 2**63 - 1
    for value in (2**63, 10**1000):
        with pytest.raises(HTTPException) as error:
            runtime._parse_value(definition, value)
        assert error.value.status_code == 422


def test_numeric_overflow_and_nonfinite_values_are_validation_errors():
    definition = runtime.DEFINITION_BY_KEY["default_tax_rate"]
    for value in (10**1000, float("inf"), float("nan")):
        with pytest.raises(HTTPException) as error:
            runtime._parse_value(definition, value)
        assert error.value.status_code == 422


@pytest.mark.parametrize("schema,version", [(runtime.StageSettingsIn, "base_version"), (runtime.RollbackSettingsIn, "expected_version")])
def test_change_reason_is_required_after_trimming(schema, version):
    for reason in ("   ", " x "):
        with pytest.raises(ValidationError):
            schema(**{version: 0, "reason": reason})
    assert schema(**{version: 0, "reason": "  Reviewed operation  "}).reason == "Reviewed operation"


@pytest.mark.asyncio
async def test_secret_whitespace_is_preserved_exactly(database):
    secret = "  smtp-password-with-surrounding-spaces  "
    staged = await runtime.stage_change(
        runtime.StageSettingsIn(base_version=0, changes={"smtp_password": secret}, reason="Preserve provider credential"),
        database,
        ACTOR.email,
    )
    change = staged["change"]
    await runtime.apply_change(
        change["id"],
        runtime.ApplySettingsIn(expected_version=0, fingerprint=change["fingerprint"]),
        database,
        ACTOR.email,
    )
    stored = await database.get(AppSetting, "runtime.smtp_password")
    assert runtime._deserialize_stored(runtime.DEFINITION_BY_KEY["smtp_password"], stored.value) == secret
    assert runtime.settings.smtp_password == secret


@pytest.mark.asyncio
async def test_stage_apply_conflict_and_rollback(database):
    staged = await runtime.stage_change(
        runtime.StageSettingsIn(
            base_version=0,
            changes={"trial_max_days": 7, "default_language": "en"},
            reason="Tune onboarding defaults",
        ),
        database,
        ACTOR.email,
    )
    change = staged["change"]
    assert change["status"] == "staged"
    assert staged["preview"] == [
        {"key": "default_language", "title": "Язык по умолчанию", "clear": False, "value": "en", "secret_changed": False},
        {"key": "trial_max_days", "title": "Максимальный пробный период", "clear": False, "value": 7, "secret_changed": False},
    ]
    applied = await runtime.apply_change(
        change["id"],
        runtime.ApplySettingsIn(expected_version=0, fingerprint=change["fingerprint"]),
        database,
        ACTOR.email,
    )
    assert applied["version"] == 1
    assert runtime.settings.trial_max_days == 7
    assert runtime.settings.default_language == "en"
    with pytest.raises(HTTPException) as stale:
        await runtime.stage_change(
            runtime.StageSettingsIn(base_version=0, changes={"trial_max_days": 8}, reason="Stale update"),
            database,
            ACTOR.email,
        )
    assert stale.value.status_code == 409
    rolled_back = await runtime.rollback_change(
        change["id"],
        runtime.RollbackSettingsIn(expected_version=1, reason="Restore environment defaults"),
        database,
        ACTOR.email,
    )
    assert rolled_back["version"] == 2
    assert runtime.settings.trial_max_days == runtime.ENVIRONMENT_VALUES["trial_max_days"]
    assert runtime.settings.default_language == runtime.ENVIRONMENT_VALUES["default_language"]
    source = await database.get(RuntimeSettingChange, change["id"])
    assert source.status == "rolled_back"


@pytest.mark.asyncio
async def test_secret_is_encrypted_masked_and_absent_from_audit(database):
    secret = "smtp-password-that-must-never-leak"
    staged = await runtime.stage_change(
        runtime.StageSettingsIn(
            base_version=0,
            changes={
                "smtp_host": "smtp.example.test",
                "smtp_from": "alerts@example.test",
                "smtp_password": secret,
                "alert_email": "owner@example.test",
            },
            reason="Enable mail alerts",
        ),
        database,
        ACTOR.email,
    )
    assert next(item for item in staged["preview"] if item["key"] == "smtp_password") == {
        "key": "smtp_password",
        "title": "SMTP-пароль",
        "clear": False,
        "value": None,
        "secret_changed": True,
    }
    change = staged["change"]
    await runtime.apply_change(
        change["id"],
        runtime.ApplySettingsIn(expected_version=0, fingerprint=change["fingerprint"]),
        database,
        ACTOR.email,
    )
    stored = await database.get(AppSetting, "runtime.smtp_password")
    assert stored is not None and secret not in stored.value
    result = await runtime.catalog(database)
    assert result["can_write"] is False
    writable_result = await runtime.catalog(database, can_write=True)
    assert writable_result["can_write"] is True
    password = next(item for item in result["settings"] if item["key"] == "smtp_password")
    assert password["value"] is None
    assert password["configured"] is True
    audits = (await database.scalars(select(AuditLog).where(AuditLog.action.like("runtime_settings.%")))).all()
    assert secret not in " ".join(item.details or "" for item in audits)
    await runtime.rollback_change(
        change["id"],
        runtime.RollbackSettingsIn(expected_version=1, reason="Mail provider disabled"),
        database,
        ACTOR.email,
    )


@pytest.mark.asyncio
async def test_types_dependencies_integrity_and_discard(database):
    for changes in (
        {"trial_max_days": "7"},
        {"payment_risk_review_score": 95, "payment_risk_block_score": 90},
        {"smtp_host": "https://smtp.example.test"},
        {"yookassa_shop_id": "shop-without-secret"},
        {"unknown_setting": True},
    ):
        with pytest.raises(HTTPException) as error:
            await runtime.stage_change(
                runtime.StageSettingsIn(base_version=0, changes=changes, reason="Invalid candidate"),
                database,
                ACTOR.email,
            )
        assert error.value.status_code == 422
    allowlist = await runtime.stage_change(
        runtime.StageSettingsIn(
            base_version=0,
            changes={"yookassa_webhook_ip_allowlist": "185.71.76.0/27"},
            reason="Preconfigure official callback network",
        ),
        database,
        ACTOR.email,
    )
    await runtime.discard_change(allowlist["change"]["id"], database, ACTOR.email)
    staged = await runtime.stage_change(
        runtime.StageSettingsIn(base_version=0, changes={"trial_max_days": 8}, reason="Discard candidate"),
        database,
        ACTOR.email,
    )
    change = staged["change"]
    discarded = await runtime.discard_change(change["id"], database, ACTOR.email)
    assert discarded == {"discarded": True, "id": change["id"]}
    with pytest.raises(HTTPException) as error:
        await runtime.apply_change(
            change["id"],
            runtime.ApplySettingsIn(expected_version=0, fingerprint=change["fingerprint"]),
            database,
            ACTOR.email,
        )
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_bot_config_never_loads_runtime_override_secrets(database, monkeypatch):
    from app import bot

    database.add(AppSetting(key="bot_name", value="Visible shop name"))
    database.add(AppSetting(key="runtime.smtp_password", value="encrypted-secret-record"))
    await database.commit()
    monkeypatch.setattr(bot, "engine", database.bind)

    values, *_ = await bot.get_bot_config()
    assert values == {"bot_name": "Visible shop name"}


@pytest.mark.asyncio
async def test_cached_session_observes_a_new_configuration_version(database):
    state = await runtime._state(database)
    await database.commit()
    assert state.version == 0
    async with AsyncSession(database.bind, expire_on_commit=False) as other:
        row = await other.get(RuntimeSettingState, 1)
        row.version = 1
        await other.commit()
    with pytest.raises(HTTPException) as error:
        await runtime.stage_change(
            runtime.StageSettingsIn(base_version=0, changes={"trial_max_days": 7}, reason="Stale session"),
            database,
            ACTOR.email,
        )
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_apply_rejects_changed_environment_before_writing(database, monkeypatch):
    monkeypatch.setitem(runtime.ENVIRONMENT_VALUES, "smtp_host", "")
    monkeypatch.setitem(runtime.ENVIRONMENT_VALUES, "alert_email", "")
    database.add_all([
        AppSetting(key="runtime.smtp_host", value='"smtp.example.test"'),
        AppSetting(key="runtime.smtp_from", value='"alerts@example.test"'),
    ])
    await database.commit()
    staged = await runtime.stage_change(
        runtime.StageSettingsIn(base_version=0, clear=["smtp_host"], reason="Disable unused SMTP"),
        database,
        ACTOR.email,
    )
    # Simulate .env being changed by a deployment after the candidate was staged.
    monkeypatch.setitem(runtime.ENVIRONMENT_VALUES, "alert_email", "owner@example.test")
    change = staged["change"]
    with pytest.raises(HTTPException) as error:
        await runtime.apply_change(
            change["id"],
            runtime.ApplySettingsIn(expected_version=0, fingerprint=change["fingerprint"]),
            database,
            ACTOR.email,
        )
    assert error.value.status_code == 409
    await database.rollback()
    assert (await database.get(RuntimeSettingState, 1)).version == 0
    assert (await database.get(RuntimeSettingChange, change["id"])).status == "staged"
    assert (await database.get(AppSetting, "runtime.smtp_host")).value == '"smtp.example.test"'


@pytest.mark.asyncio
async def test_rollback_rejects_changed_environment_and_preserves_applied_revision(database, monkeypatch):
    monkeypatch.setitem(runtime.ENVIRONMENT_VALUES, "smtp_host", "")
    monkeypatch.setitem(runtime.ENVIRONMENT_VALUES, "alert_email", "")
    staged = await runtime.stage_change(
        runtime.StageSettingsIn(
            base_version=0,
            changes={"smtp_host": "smtp.example.test", "smtp_from": "alerts@example.test", "alert_email": "owner@example.test"},
            reason="Enable SMTP alerts",
        ),
        database,
        ACTOR.email,
    )
    change = staged["change"]
    await runtime.apply_change(
        change["id"],
        runtime.ApplySettingsIn(expected_version=0, fingerprint=change["fingerprint"]),
        database,
        ACTOR.email,
    )
    monkeypatch.setitem(runtime.ENVIRONMENT_VALUES, "alert_email", "retained@example.test")
    with pytest.raises(HTTPException) as error:
        await runtime.rollback_change(
            change["id"],
            runtime.RollbackSettingsIn(expected_version=1, reason="Restore pre-SMTP configuration"),
            database,
            ACTOR.email,
        )
    assert error.value.status_code == 409
    await database.rollback()
    assert (await database.get(RuntimeSettingState, 1)).version == 1
    assert (await database.get(RuntimeSettingChange, change["id"])).status == "applied"
    assert (await database.get(AppSetting, "runtime.smtp_host")).value == '"smtp.example.test"'
    assert runtime.settings.smtp_host == "smtp.example.test"


@pytest.mark.asyncio
async def test_tampered_candidate_cannot_apply(database):
    staged = await runtime.stage_change(
        runtime.StageSettingsIn(base_version=0, changes={"trial_max_days": 7}, reason="Integrity regression"),
        database,
        ACTOR.email,
    )
    change = staged["change"]
    row = await database.get(RuntimeSettingChange, change["id"])
    internal = runtime._load_payload(row)
    internal["changes"]["trial_max_days"] = 30
    row.payload_encrypted = runtime.encrypt_secret(runtime._canonical(internal))
    await database.commit()
    with pytest.raises(HTTPException) as error:
        await runtime.apply_change(
            change["id"],
            runtime.ApplySettingsIn(expected_version=0, fingerprint=change["fingerprint"]),
            database,
            ACTOR.email,
        )
    assert error.value.status_code == 409
    await database.rollback()
    assert (await database.get(RuntimeSettingState, 1)).version == 0
    assert await database.get(AppSetting, "runtime.trial_max_days") is None


@pytest.mark.asyncio
async def test_standalone_worker_loads_committed_settings_and_converges(database, monkeypatch):
    import worker
    from app import account_actions, account_merge

    database.add(RuntimeSettingState(id=1, version=1))
    database.add(AppSetting(key="runtime.trial_max_days", value="7"))
    await database.commit()
    monkeypatch.setattr(worker.main, "engine", database.bind)
    monkeypatch.setattr(worker.main, "redis_client", None)
    monkeypatch.setattr(runtime, "POLL_INTERVAL_SECONDS", 0.01)
    seen = []
    finished = asyncio.Event()
    committed = asyncio.Event()
    sessions = async_sessionmaker(database.bind, expire_on_commit=False)

    @asynccontextmanager
    async def scheduled_session():
        # SQLite's in-memory fixture shares one physical connection. Start the
        # polling read after the independent writer commits, so another session's
        # rollback cannot cancel that writer on this test-only connection.
        await committed.wait()
        async with sessions() as session:
            yield session

    monkeypatch.setattr(runtime, "SessionLocal", scheduled_session)

    def validate(_settings):
        seen.append(("startup", _settings.trial_max_days))

    class FakeRedis:
        async def ping(self):
            seen.append(("redis", runtime.settings.trial_max_days))

    async def idle():
        await asyncio.Event().wait()

    async def jobs():
        seen.append(("job", runtime.settings.trial_max_days))
        async with AsyncSession(database.bind, expire_on_commit=False) as other:
            (await other.get(AppSetting, "runtime.trial_max_days")).value = "9"
            (await other.get(RuntimeSettingState, 1)).version = 2
            await other.commit()
        committed.set()
        while runtime.settings.trial_max_days != 9:
            await asyncio.sleep(0.005)
        finished.set()
        await idle()

    monkeypatch.setattr(type(runtime.settings), "validate_security", validate)
    monkeypatch.setattr(worker.Redis, "from_url", lambda *args, **kwargs: FakeRedis())
    for name in ("worker_heartbeat", "health_alert_worker"):
        monkeypatch.setattr(worker, name, idle)
    monkeypatch.setattr(worker, "job_worker", jobs)
    for name in ("backup_scheduler", "fulfillment_retry_scheduler", "expiry_notification_scheduler", "reconciliation_scheduler", "auto_renew_scheduler", "refund_revoke_scheduler", "subscription_lifecycle_scheduler"):
        monkeypatch.setattr(worker.main, name, idle)
    monkeypatch.setattr(account_actions, "mail_scheduler", idle)
    monkeypatch.setattr(account_merge, "account_merge_cleanup_scheduler", idle)
    # Every background loop started by the worker is replaced: the real push, plugin
    # and network loops use the application engine and outbound HTTP, and a task
    # cancelled mid-connection could stall event-loop teardown.
    from app import mail_domain, network_intel, node_terminal, plugins, push, torrent_detection
    monkeypatch.setattr(push, "push_scheduler", idle)
    monkeypatch.setattr(plugins, "plugin_scheduler", idle)
    monkeypatch.setattr(network_intel, "network_intel_scheduler", idle)
    monkeypatch.setattr(mail_domain, "mail_domain_scheduler", idle)
    monkeypatch.setattr(node_terminal, "terminal_scheduler", idle)
    monkeypatch.setattr(torrent_detection, "torrent_scheduler", idle)
    task = asyncio.create_task(worker.main_worker())
    try:
        await asyncio.wait_for(finished.wait(), 5)
        assert seen == [("startup", 7), ("redis", 7), ("job", 7)]
        assert runtime.settings.trial_max_days == 9
        assert runtime._loaded_version == 2
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_postgres_two_staged_changes_cannot_both_apply(database):
    if database.bind.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock race")
    one = await runtime.stage_change(
        runtime.StageSettingsIn(base_version=0, changes={"trial_max_days": 8}, reason="Candidate one"),
        database,
        ACTOR.email,
    )
    two = await runtime.stage_change(
        runtime.StageSettingsIn(base_version=0, changes={"trial_max_days": 9}, reason="Candidate two"),
        database,
        ACTOR.email,
    )

    async def apply(item):
        async with AsyncSession(database.bind, expire_on_commit=False) as session:
            try:
                result = await runtime.apply_change(
                    item["change"]["id"],
                    runtime.ApplySettingsIn(expected_version=0, fingerprint=item["change"]["fingerprint"]),
                    session,
                    ACTOR.email,
                )
                return result["version"]
            except HTTPException as error:
                await session.rollback()
                return error.status_code

    assert sorted(await asyncio.gather(apply(one), apply(two))) == [1, 409]
    assert (await database.get(RuntimeSettingState, 1)).version == 1


@pytest.mark.asyncio
async def test_runtime_settings_migration_roundtrip(database):
    if database.bind.dialect.name != "postgresql":
        pytest.skip("PostgreSQL DDL")
    path = Path("backend/alembic/versions/0064_runtime_settings.py")
    spec = importlib.util.spec_from_file_location("runtime_settings_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    await database.rollback()
    async with database.bind.begin() as connection:
        def cycle(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration.downgrade()
                migration.upgrade()
        await connection.run_sync(cycle)
    async with AsyncSession(database.bind) as session:
        state = await session.get(RuntimeSettingState, 1)
        assert state is not None and state.version == 0
