"""v28.75.0 (stage 16): confirmation of dangerous actions, own sessions and the security history.

* every dangerous route of ``admin_stepup.STEP_UP_ACTIONS`` is declared with ``require_stepup``: without a fresh
  confirmation of this session it answers 428, with one it passes;
* the confirmation is the TOTP code when two-factor is on, otherwise the password; five wrong attempts pause it;
  every attempt is in the audit log; it lives 10 minutes and belongs to one session;
* an administrator sees and ends only their own sessions with ``sessions.self``;
* the security history shows sign-ins, failures and confirmations; sign-ins and failures are audited;
* the reserved permissions are used now, the two legacy ones are gone."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import admin_stepup, main, security, totp
from app.models import AdminSession, AdminUser, AuditLog
from app_contract import all_routes
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def req(sid):
    return SimpleNamespace(state=SimpleNamespace(admin_session_id=sid))


@pytest.fixture(autouse=True)
def local_state(monkeypatch):
    monkeypatch.setattr(main, "redis_client", None)
    monkeypatch.setattr(security, "_stepup_local", {})
    monkeypatch.setattr(admin_stepup, "_fails_local", {})


def test_dangerous_routes_need_step_up():
    marked = {(m, path) for path, route in all_routes() for m in (getattr(route, "methods", None) or ())
              if any(getattr(d.call, "step_up", False) for d in route.dependant.dependencies)}
    for method, path, _ in admin_stepup.STEP_UP_ACTIONS:
        assert (method, path) in marked, (method, path)
    assert marked == {(m, p) for m, p, _ in admin_stepup.STEP_UP_ACTIONS}  # the list in the panel is complete


def test_roles_use_the_reserved_permissions():
    for role, perms in security.PERMISSIONS.items():
        assert "sessions.self" in perms, role
        assert not {"manage_payments", "manage_backups"} & perms, role
    assert "security.stepup" in security.PERMISSIONS["admin"] and "security.stepup" in security.PERMISSIONS["operator"]
    assert {"manage_payments", "manage_backups"}.isdisjoint(security.PERMISSION_LABELS)


@pytest.mark.asyncio
async def test_require_stepup_answers_428_until_confirmed():
    dep = security.require_stepup("backups.restore")
    admin = SimpleNamespace(role="admin")
    with pytest.raises(HTTPException) as err:
        await dep(req(7), admin)
    assert err.value.status_code == 428 and err.value.detail.startswith("STEP_UP_REQUIRED")
    await security.mark_stepup(7)
    assert await dep(req(7), admin) is admin
    with pytest.raises(HTTPException):  # another session is not confirmed by this one
        await dep(req(8), admin)
    assert 590 <= await security.stepup_fresh(7) <= 600


async def make_admin(db, email="owner@corgi.test", mfa=False):
    admin = AdminUser(email=email, password_hash=security.hash_password("correct horse battery"), role="admin")
    secret = None
    if mfa:
        secret = totp.random_base32()
        admin.totp_secret_encrypted = security.encrypt_secret(secret)
        admin.mfa_enabled = True
    db.add(admin)
    await db.commit()
    return admin, secret


@pytest.mark.asyncio
async def test_step_up_with_password_and_pause_after_five_failures(database):
    db = database
    admin, _ = await make_admin(db)
    state = await admin_stepup.step_up_state(req(1), admin)
    assert state["method"] == "password" and not state["fresh"] and len(state["actions"]) == len(admin_stepup.STEP_UP_ACTIONS)
    with pytest.raises(HTTPException) as err:
        await admin_stepup.step_up(admin_stepup.StepUpIn(password="wrong"), req(1), db, admin)
    assert err.value.status_code == 401
    assert (await admin_stepup.step_up(admin_stepup.StepUpIn(password="correct horse battery"), req(1), db, admin))["fresh"]
    assert (await admin_stepup.step_up_state(req(1), admin))["fresh"]
    for _ in range(4):
        with pytest.raises(HTTPException):
            await admin_stepup.step_up(admin_stepup.StepUpIn(password="wrong"), req(2), db, admin)
    with pytest.raises(HTTPException) as err:  # the fifth failure of session 2 is recorded…
        await admin_stepup.step_up(admin_stepup.StepUpIn(password="wrong"), req(2), db, admin)
    with pytest.raises(HTTPException) as err:  # …and then even the right password waits
        await admin_stepup.step_up(admin_stepup.StepUpIn(password="correct horse battery"), req(2), db, admin)
    assert err.value.status_code == 429
    actions = (await db.execute(select(AuditLog.action).where(AuditLog.action.like("security.stepup.%")))).scalars().all()
    assert actions.count("security.stepup.failed") == 6 and actions.count("security.stepup.confirmed") == 1


@pytest.mark.asyncio
async def test_step_up_with_totp_ignores_the_password(database):
    db = database
    admin, secret = await make_admin(db, mfa=True)
    assert (await admin_stepup.step_up_state(req(3), admin))["method"] == "totp"
    with pytest.raises(HTTPException):
        await admin_stepup.step_up(admin_stepup.StepUpIn(password="correct horse battery"), req(3), db, admin)
    assert (await admin_stepup.step_up(admin_stepup.StepUpIn(code=totp.code(secret)), req(3), db, admin))["fresh"]


@pytest.mark.asyncio
async def test_own_sessions_only(database):
    db = database
    from datetime import datetime, timedelta
    admin, _ = await make_admin(db)
    other, _ = await make_admin(db, "second@corgi.test")
    later = datetime.utcnow() + timedelta(minutes=30)
    mine = AdminSession(admin_id=admin.id, jti_hash="a" * 64, ip="198.51.100.1", user_agent="Firefox", expires_at=later)
    spare = AdminSession(admin_id=admin.id, jti_hash="b" * 64, ip="198.51.100.2", user_agent="Phone", expires_at=later)
    foreign = AdminSession(admin_id=other.id, jti_hash="c" * 64, expires_at=later)
    db.add_all([mine, spare, foreign])
    await db.commit()
    rows = await admin_stepup.my_sessions(req(mine.id), db, admin)
    assert {r["id"] for r in rows} == {mine.id, spare.id} and [r["current"] for r in rows if r["id"] == mine.id] == [True]
    with pytest.raises(HTTPException) as err:
        await admin_stepup.revoke_my_session(foreign.id, db, admin)
    assert err.value.status_code == 404
    assert (await admin_stepup.revoke_my_session(spare.id, db, admin))["ok"]
    assert {r["id"] for r in await admin_stepup.my_sessions(req(mine.id), db, admin)} == {mine.id}


@pytest.mark.asyncio
async def test_security_history(database):
    db = database
    admin, _ = await make_admin(db)
    for action, target in (("admin.login.failed", "203.0.113.5"), ("admin.login.failed", "203.0.113.6"), ("admin.login", "198.51.100.1"),
                           ("security.stepup.confirmed", "1"), ("payments.refund", "9")):
        await main.audit(db, action, admin.email, target)
    await db.commit()
    out = await admin_stepup.security_history(7, None, db, admin)
    assert out["summary"] == {"failed_logins_24h": 2, "failed_login_ips_24h": 2, "logins": 1, "step_ups": 1}
    assert [e["action"] for e in out["events"]].count("payments.refund") == 0  # not a security event
    assert {e["level"] for e in out["events"] if e["action"] == "admin.login.failed"} == {"warn"}


@pytest.mark.asyncio
async def test_admin_sign_in_is_audited_and_has_no_timing_oracle(database, monkeypatch):
    """C1 (stage 19): behaviour instead of the source text — an unknown e-mail costs the same password hashing as a known
    one, every failure is in the audit log, the 10th failure in 15 minutes raises an alert, a sign-in is audited."""
    from starlette.responses import Response

    from app import admin_auth_api, mobile_auth
    db = database
    admin, _ = await make_admin(db)
    hashes, alerts = [], []
    real_verify = main.verify_password

    def verify(password, stored):
        hashes.append(stored)
        return real_verify(password, stored)

    async def allowed(*a, **k):
        return True

    async def alert(text):
        alerts.append(text)
    monkeypatch.setattr(main, "verify_password", verify)
    monkeypatch.setattr(main, "_redis_allowed", allowed)
    monkeypatch.setattr(main, "send_alert", alert)
    monkeypatch.setattr(mobile_auth, "require_mobile_proof", lambda request: None)
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="203.0.113.7"), cookies={}, url=SimpleNamespace(scheme="https"))
    monkeypatch.setattr(main, "_client_ip", lambda r: "203.0.113.7")

    async def attempt(email, password):
        return await admin_auth_api.admin_login(main.LoginIn(email=email, password=password), request, Response(), db)

    with pytest.raises(HTTPException) as unknown:
        await attempt("nobody@corgi.test", "whatever")
    with pytest.raises(HTTPException) as wrong:
        await attempt(admin.email, "wrong password")
    assert unknown.value.status_code == wrong.value.status_code == 401 and unknown.value.detail == wrong.value.detail
    assert hashes == [admin_auth_api._DUMMY_HASH, admin.password_hash], "the unknown e-mail is hashed too"
    for _ in range(8):
        with pytest.raises(HTTPException):
            await attempt(admin.email, "wrong password")
    failed = (await db.execute(select(AuditLog).where(AuditLog.action == "admin.login.failed"))).scalars().all()
    assert len(failed) == 10 and {f.target for f in failed} == {"203.0.113.7"}
    assert len(alerts) == 1 and "10" in alerts[0], "one alert at the 10th failure"
    try:
        await attempt(admin.email, "correct horse battery")
    except Exception:
        pass  # the session cookie part needs the full app; the audit entry is written before it
    assert (await db.execute(select(AuditLog).where(AuditLog.action == "admin.login"))).scalars().first() is not None
