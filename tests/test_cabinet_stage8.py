"""v28.63.0 (stage 8): the cabinet — sessions, devices under the subscription limit, Google sign-in, Lucy tariffs.

* a customer sees every sign-in and ends one of them; another customer's session cannot be touched;
* devices counted by Remnawave (HWID) are listed with the limit; one or all are deleted through panel 3.x
  bodies ({"userId": <number>, "hwid": …}); the raw HWID never leaves the server;
* Lucy Mini (trial, 1 device, not on sale), Lucy Max (2 devices) and Lucy Ultra (4, cheaper per device);
  once applied, the free trial is granted on Lucy Mini only and for its length;
* Google sign-in is switched on from the admin panel without a restart and shows up in the cabinet config."""
import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app import cabinet_security, lucy_plans, main as shop, remnawave
from app.models import AppSetting, AuditLog, Plan, Subscription, UserSession
from test_subscription_commerce import database, request  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test", role="admin")
HWID_A, HWID_B = "HWID-AAAAAAAAAA-1", "HWID-BBBBBBBBBB-2"


def _session(user_id, jti, **kw):
    return UserSession(user_id=user_id, jti_hash=hashlib.sha256(jti.encode()).hexdigest(), ip="203.0.113.5",
                       user_agent="Firefox", expires_at=datetime.utcnow() + timedelta(days=1), **kw)


@pytest.mark.asyncio
async def test_sessions_are_listed_and_ended_one_by_one(database, monkeypatch):
    db = database
    db.add_all([_session(1, "mine-current"), _session(1, "mine-phone"), _session(2, "someone-else"),
                _session(1, "old", revoked_at=datetime.utcnow())])
    await db.commit()
    monkeypatch.setattr(cabinet_security, "_current_jti_hash", lambda req: hashlib.sha256(b"mine-current").hexdigest())
    rows = await cabinet_security.my_sessions(request(), db)
    assert len(rows) == 3 and sum(r["current"] for r in rows) == 1 and sum(r["active"] for r in rows) == 2
    phone = next(r for r in rows if r["active"] and not r["current"])
    assert await cabinet_security.revoke_session(phone["id"], request(), db) == {"ok": True, "current": False}
    other = await db.scalar(select(UserSession).where(UserSession.user_id == 2))
    with pytest.raises(HTTPException) as err:
        await cabinet_security.revoke_session(other.id, request(), db)
    assert err.value.status_code == 404 and (await db.get(UserSession, other.id)).revoked_at is None
    current = next(r for r in rows if r["current"])
    assert (await cabinet_security.revoke_session(current["id"], request(), db))["current"] is True
    actions = (await db.execute(select(AuditLog.action).where(AuditLog.action == "auth.user.session.revoked"))).scalars().all()
    assert len(actions) == 2


class Panel:
    calls: list = []
    devices = [{"hwid": HWID_A, "userId": 42, "platform": "Android", "osVersion": "15", "deviceModel": "Pixel 9",
                "createdAt": "2026-11-01T10:00:00.000Z", "updatedAt": "2026-11-02T10:00:00.000Z"},
               {"hwid": HWID_B, "userId": 42, "platform": "iOS", "osVersion": "19", "deviceModel": "iPhone",
                "createdAt": "2026-11-01T11:00:00.000Z", "updatedAt": "2026-11-02T11:00:00.000Z"}]

    async def hwid_devices(self, user_id):
        Panel.calls.append(("list", user_id))
        return list(Panel.devices)

    async def get_user(self, user_id):
        return {"id": user_id, "hwidDeviceLimit": 2}

    async def delete_hwid_device(self, user_id, hwid):
        Panel.calls.append(("delete", user_id, hwid))

    async def reset_hwid_devices(self, user_id):
        Panel.calls.append(("reset", user_id))


@pytest.mark.asyncio
async def test_devices_under_the_limit(database, monkeypatch):
    db = database
    Panel.calls = []
    monkeypatch.setattr(shop, "RemnawaveClient", Panel)
    with pytest.raises(HTTPException) as err:  # a 2.x UUID, not a panel 3.x user id
        await cabinet_security.my_hwid_devices(request(), db)
    assert err.value.status_code == 409
    sub = await db.get(Subscription, 1)
    sub.remnawave_uuid = "42"
    await db.commit()
    data = await cabinet_security.my_hwid_devices(request(), db)
    assert data["limit"] == 2 and data["used"] == 2
    assert HWID_A not in json.dumps(data) and data["devices"][0]["model"] == "Pixel 9"
    await cabinet_security.delete_my_hwid_device(data["devices"][1]["id"], request(), db)
    assert ("delete", 42, HWID_B) in Panel.calls
    with pytest.raises(HTTPException) as err:
        await cabinet_security.delete_my_hwid_device("0" * 16, request(), db)
    assert err.value.status_code == 404
    await cabinet_security.reset_my_hwid_devices(request(), db)
    assert ("reset", 42) in Panel.calls
    actions = set((await db.execute(select(AuditLog.action).where(AuditLog.actor == "user:1"))).scalars())
    assert {"cabinet.hwid_device.deleted", "cabinet.hwid_devices.reset"} <= actions


@pytest.mark.asyncio
async def test_devices_without_the_panel_answer_clearly(database, monkeypatch):
    db = database
    (await db.get(Subscription, 1)).remnawave_uuid = "42"
    await db.commit()

    class Off(Panel):
        async def hwid_devices(self, user_id):
            raise remnawave.RemnawaveNotConfigured("no url")

    class Down(Panel):
        async def hwid_devices(self, user_id):
            raise remnawave.RemnawaveError("GET /api/hwid: 500: token=SECRET")

    for client, code in ((Off, 503), (Down, 502)):
        monkeypatch.setattr(shop, "RemnawaveClient", client)
        with pytest.raises(HTTPException) as err:
            await cabinet_security.my_hwid_devices(request(), db)
        assert err.value.status_code == code and "SECRET" not in err.value.detail


@pytest.mark.asyncio
async def test_panel_3_hwid_bodies(monkeypatch):
    sent = []

    async def capture(self, method, path, **kw):
        sent.append((method, path, kw.get("json")))
        return {}

    monkeypatch.setattr(remnawave.RemnawaveClient, "_request", capture)
    client = remnawave.RemnawaveClient()
    await client.reset_hwid_devices("42")
    await client.delete_hwid_device(42, HWID_A)
    assert sent == [("POST", "/api/hwid/devices/delete-all", {"userId": 42}),
                    ("POST", "/api/hwid/devices/delete", {"userId": 42, "hwid": HWID_A})]


def test_ultra_must_be_cheaper_per_device():
    lucy_plans.LucyIn(max_price=Decimal("300"), ultra_price=Decimal("500"))
    with pytest.raises(ValidationError):
        lucy_plans.LucyIn(max_price=Decimal("300"), ultra_price=Decimal("600"))


@pytest.mark.asyncio
async def test_lucy_tariffs_and_the_trial_on_lucy_mini(database, monkeypatch):
    db = database
    out = await lucy_plans.lucy_apply(lucy_plans.LucyIn(max_price=Decimal("299"), ultra_price=Decimal("499")), db, ADMIN)
    assert out["result"] == {"Lucy Mini": "created", "Lucy Max": "created", "Lucy Ultra": "created"}
    plans = {p.name: p for p in (await db.execute(select(Plan).where(Plan.name.like("Lucy %")))).scalars()}
    mini, mx, ultra = plans["Lucy Mini"], plans["Lucy Max"], plans["Lucy Ultra"]
    assert (mini.device_limit, mini.duration_days, mini.enabled) == (1, 3, False)
    assert (mx.device_limit, mx.traffic_limit_gb, mx.enabled) == (2, None, True)
    assert (ultra.device_limit, ultra.traffic_limit_gb) == (4, None)
    assert out["trial_is_mini"] and (await db.get(AppSetting, "trial_plan_id")).value == str(mini.id)

    again = await lucy_plans.lucy_apply(lucy_plans.LucyIn(max_price=Decimal("349"), ultra_price=Decimal("599")), db, ADMIN)
    assert set(again["result"].values()) == {"updated"}
    assert len((await db.execute(select(Plan).where(Plan.name.like("Lucy %")))).scalars().all()) == 3

    # On sale: Max and Ultra, never Mini.
    on_sale = {p["name"] for p in await shop.plans(db, None)}
    assert {"Lucy Max", "Lucy Ultra"} <= on_sale and "Lucy Mini" not in on_sale
    assert (await lucy_plans.public_trial(db))["plan"]["device_limit"] == 1

    # The trial: only Lucy Mini, and not longer than Lucy Mini.
    with pytest.raises(HTTPException) as err:
        await lucy_plans.trial_plan(db, mx.id)
    assert err.value.status_code == 400
    assert (await lucy_plans.trial_plan(db, mini.id)).id == mini.id
    assert lucy_plans.trial_days(mini, 30, 30) == 3 and lucy_plans.trial_days(mx, 30, 7) == 7

    await lucy_plans.lucy_trial_off(db, ADMIN)
    assert (await lucy_plans.public_trial(db))["plan"] is None
    assert (await lucy_plans.trial_plan(db, mx.id)).id == mx.id
    with pytest.raises(HTTPException):
        await lucy_plans.trial_plan(db, mini.id)  # not on sale and no longer the trial plan


def test_google_sign_in_is_a_runtime_setting_and_reaches_the_cabinet():
    from app import runtime_settings as runtime
    for key in ("google_client_id", "google_client_secret", "google_redirect_uri"):
        assert key in runtime.DEFINITION_BY_KEY, key
    assert runtime.DEFINITION_BY_KEY["google_client_secret"].secret
    source = (shop.__file__ and open(shop.__file__).read())
    assert '"google_enabled":bool(settings.google_client_id and settings.google_redirect_uri)' in source
