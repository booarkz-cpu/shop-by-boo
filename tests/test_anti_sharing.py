"""Anti-sharing: more devices than the plan allows resets the device list or switches the config off."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import anti_sharing
from app.models import AbuseViolation, Subscription, User
from app_contract import permissions
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="a@b.c")


class Panel:
    def __init__(self, devices=3):
        self.devices = [{"hwid": f"h{i}", "deviceModel": f"Phone {i}"} for i in range(devices)]
        self.reset, self.disabled = [], []

    async def hwid_devices(self, uid):
        return self.devices

    async def reset_hwid_devices(self, uid):
        self.reset.append(uid)

    async def disable_user(self, uid):
        self.disabled.append(uid)


@pytest.fixture
def panel(monkeypatch):
    p = Panel()
    monkeypatch.setattr("app.main.RemnawaveClient", lambda: p)
    monkeypatch.setattr("app.remnawave.RemnawaveClient", lambda: p)
    return p


@pytest.mark.asyncio
async def test_nothing_happens_until_the_owner_switches_it_on(database, panel):
    assert (await anti_sharing.check_pass(database, panel=panel))["checked"] == 0 and panel.reset == []


@pytest.mark.asyncio
async def test_extra_devices_are_reset_and_the_customer_is_told(database, panel):
    await anti_sharing.put_anti_sharing(anti_sharing.AntiSharingIn(enabled=True, action="reset"), database, ADMIN)
    told = []

    async def notify(user, text):
        told.append((user.id, text))
    out = await anti_sharing.check_pass(database, panel=panel, notify=notify)
    assert out["over"] == [1] and panel.reset == ["remote-1"], "3 devices on a 2-device plan"
    assert told and "3 устройствах при лимите 2" in told[0][1]
    assert (await database.get(Subscription, 1)).lifecycle_status == "active", "reset keeps the subscription on"
    violation = await database.scalar(select(AbuseViolation))
    assert violation.recommendation == "warn" and "Phone 2" in violation.analyzers["devices"]
    panel.devices = panel.devices[:2]
    assert (await anti_sharing.check_pass(database, panel=panel))["over"] == [], "within the limit again"


@pytest.mark.asyncio
async def test_block_switches_the_config_off_until_the_operator_lifts_it(database, panel):
    await anti_sharing.put_anti_sharing(anti_sharing.AntiSharingIn(enabled=True, action="block"), database, ADMIN)
    await anti_sharing.check_pass(database, panel=panel)
    user, sub = await database.get(User, 1, populate_existing=True), await database.get(Subscription, 1, populate_existing=True)
    assert user.restricted_at is not None and sub.lifecycle_status == "suspended" and panel.disabled == ["remote-1"]
    from app.platform_api import resume_access
    panel_enabled = []

    async def enable(uid):
        panel_enabled.append(uid)
    panel.enable_user = enable
    assert await resume_access(database, user) == 1 and panel_enabled == ["remote-1"]


@pytest.mark.asyncio
async def test_tolerance_allows_a_phone_swap(database, panel):
    await anti_sharing.put_anti_sharing(anti_sharing.AntiSharingIn(enabled=True, action="reset", tolerance=1), database, ADMIN)
    assert (await anti_sharing.check_pass(database, panel=panel))["over"] == []


def test_anti_sharing_is_a_security_setting():
    assert permissions("PUT", "/api/admin/anti-sharing") == {"security.manage"}
