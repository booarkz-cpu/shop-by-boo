"""Switching incident mode off lifts the maintenance it switched on, except after a failed restore.

The shared fixture stubs maintenance_enabled(), so the stored flag is read directly."""
from types import SimpleNamespace

import pytest

from app import main
from app.config import settings
from test_subscription_commerce import database

ADMIN = SimpleNamespace(email="root@example.test")


@pytest.mark.asyncio
async def test_incident_mode_round_trip_restores_sales(database, monkeypatch):
    monkeypatch.setattr(settings, "maintenance_mode", False)
    monkeypatch.setattr(main, "redis_client", None)
    on = await main.incident_mode({"enabled": True}, database, ADMIN)
    assert on["enabled"] is True and on["maintenance_mode"] is True
    assert await main.setting_value(database, "maintenance_mode", "0") == "1"
    off = await main.incident_mode({"enabled": False}, database, ADMIN)
    assert off == {"enabled": False, "maintenance_mode": False, "maintenance_kept": False}
    assert await main.setting_value(database, "maintenance_mode", "0") == "0"


@pytest.mark.asyncio
async def test_failed_restore_keeps_maintenance(database, monkeypatch):
    monkeypatch.setattr(settings, "maintenance_mode", False)
    monkeypatch.setattr(main, "redis_client", None)
    await main.incident_mode({"enabled": True}, database, ADMIN)
    await main.set_setting(database, "restore_state", "failed")
    await database.commit()
    off = await main.incident_mode({"enabled": False}, database, ADMIN)
    assert off["maintenance_kept"] is True and off["maintenance_mode"] is True
    assert await main.setting_value(database, "maintenance_mode", "0") == "1"


@pytest.mark.asyncio
async def test_env_maintenance_is_reported(database, monkeypatch):
    monkeypatch.setattr(main, "redis_client", None)
    monkeypatch.setattr(settings, "maintenance_mode", True)
    off = await main.incident_mode({"enabled": False}, database, ADMIN)
    assert off["maintenance_kept"] is False and off["maintenance_mode"] is True


@pytest.mark.asyncio
async def test_recovery_center_reports_incident_mode(database, monkeypatch):
    monkeypatch.setattr(settings, "maintenance_mode", False)
    monkeypatch.setattr(main, "redis_client", None)
    assert (await main.admin_recovery(database, ADMIN))["incident_mode"] is False
    await main.incident_mode({"enabled": True}, database, ADMIN)
    assert (await main.admin_recovery(database, ADMIN))["incident_mode"] is True
