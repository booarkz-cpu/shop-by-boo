"""v28.60.0 (stage 6): the Admin Control Center maps the 30 modules of the task to the panel honestly.

* every panel section it names exists in admin/src/sections.ts, and every API prefix has routes;
* a module without a section names the stage that adds it and shows no operations (no fake switches);
* every permission a route asks for is held by some role and has a label;
* the generated docs/ru/new/ADMIN_CONTROL_MATRIX.md is current;
* the audit log is searchable; settings of the subscription proxy are written to it."""
import importlib.util
import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Response

from app import admin_center, admin_api
from app.models import AuditLog
from app.security import PERMISSION_LABELS, PERMISSIONS
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
ADMIN = SimpleNamespace(email="root@example.test", role="admin")


def _tabs() -> set[str]:
    return set(re.findall(r'\{tab: "([A-Za-z0-9]+)"', (ROOT / "admin/src/sections.ts").read_text()))


def test_thirty_modules_with_real_sections_and_routes():
    modules = admin_center.matrix()
    assert [m["number"] for m in modules] == list(range(1, 31))
    tabs = _tabs()
    for m in modules:
        assert set(m["tabs"]) <= tabs, (m["module"], set(m["tabs"]) - tabs)
        if m["missing"]:
            assert not m["tabs"] and not m["api_prefixes"] and m["routes"] == 0 and m["status"] == "NOT_STARTED"
            assert not any(m["operations"].values()), "a missing module must not claim operations"
            assert re.search(r"этап \d+", m["missing"]), m["module"]
        else:
            assert m["tabs"] and m["routes"] > 0 and m["operations"]["read"], m["module"]


def test_every_api_prefix_of_a_module_has_routes():
    paths = {p for _, p in admin_center._walk(__import__("app.main", fromlist=["app"]).app.routes)}
    for number, name, _tabs, prefixes, _missing in admin_center.MODULES:
        for prefix in prefixes:
            assert any(p == f"/api/admin/{prefix}" or p.startswith(f"/api/admin/{prefix}/") or p.startswith(f"/api/admin/{prefix}.")
                       for p in paths), f"{number} {name}: no route under /api/admin/{prefix}"


def test_permissions_asked_by_routes_are_granted_and_labelled():
    granted = set().union(*PERMISSIONS.values())
    asked = {p for m in admin_center.matrix() for p in m["permissions"]}
    assert asked <= granted, asked - granted
    assert set(PERMISSION_LABELS) == granted


@pytest.mark.asyncio
async def test_roles_endpoint_lists_roles_and_labelled_permissions():
    data = await admin_center.roles(ADMIN)
    assert [r["role"] for r in data["roles"]] == list(PERMISSIONS)
    assert all(p["label"] != p["key"] for p in data["permissions"]) and data["your_role"] == "admin"
    admin_row = next(r for r in data["roles"] if r["role"] == "admin")
    assert "manage_admins" in admin_row["permissions"]


def test_generated_matrix_document_is_current():
    spec = importlib.util.spec_from_file_location("admin_matrix", ROOT / "scripts/generate-admin-matrix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (ROOT / "docs/ru/new/ADMIN_CONTROL_MATRIX.md").read_text() == module.render(), "run: python scripts/generate-admin-matrix.py"


@pytest.mark.asyncio
async def test_audit_log_is_searched_by_actor_action_target_and_period(database):
    db = database
    now = datetime.utcnow()
    db.add(AuditLog(action="payment.refunded", actor="anna@corgi.test", target="501", details="{}", created_at=now - timedelta(days=3)))
    db.add(AuditLog(action="payment.retry", actor="boris@corgi.test", target="502", details="{}", created_at=now - timedelta(hours=1)))
    db.add(AuditLog(action="plan.created", actor="anna@corgi.test", target="7", details="{}", created_at=now))
    db.add(AuditLog(action="plan_created", actor="a%b@corgi.test", target="8", details="{}", created_at=now))
    await db.commit()

    async def search(**kw):
        response = Response()
        params = dict(page=1, page_size=50, actor=None, action=None, target=None, since=None, until=None) | kw
        rows = await admin_api.admin_audit(db=db, admin=ADMIN, response=response, **params)
        return [r["target"] for r in rows], int(response.headers["X-Total-Count"])

    assert await search(actor="anna") == (["7", "501"], 2)
    assert await search(action="payment.") == (["502", "501"], 2)
    assert await search(target="502") == (["502"], 1)
    assert await search(since=now - timedelta(days=1), action="payment") == (["502"], 1)
    # Typed text matches literally: «_» and «%» are not wildcards.
    assert await search(action="plan.") == (["7"], 1)
    assert await search(actor="a%b") == (["8"], 1)


@pytest.mark.asyncio
async def test_subscription_proxy_changes_are_audited(database):
    from sqlalchemy import select

    from app import sub_proxy
    db = database
    await sub_proxy.put_proxy(sub_proxy.ProxyIn(enabled=False), db, ADMIN)
    await sub_proxy.block_device(sub_proxy.BlockIn(hwid="HWID-1", note="кража"), db, ADMIN)
    await sub_proxy.unblock_device("HWID-1", db, ADMIN)
    actions = (await db.execute(select(AuditLog.action).where(AuditLog.action.like("sub_proxy.%")).order_by(AuditLog.id))).scalars().all()
    assert actions == ["sub_proxy.config.saved", "sub_proxy.device.blocked", "sub_proxy.device.unblocked"]
