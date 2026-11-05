"""Stage 18 (docs/ru/new/ADMIN_VERIFICATION.md): changing admin routes of «Remnawave» (hosts and Internal Squads),
«Бэкапы» and the provisioning retry."""
import io
import tarfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import backups_api, panel_admin, recovery_api, restore_approval, telegram_backup
from app import main as shop
from app.models import AdminUser, AppSetting, AuditLog, BackupJob, ProvisioningOperation
from test_subscription_commerce import database  # noqa: F401


class FakePanel:
    calls: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def _request(self, method, path, json=None):
        FakePanel.calls.append((method, path, json))
        if json and json.get("remark") == "taken":
            raise RuntimeError("Host with this remark already exists")
        return {"uuid": "h-1", **(json or {})}

    async def squad_add_all_users(self, uuid):
        FakePanel.calls.append(("ADD-ALL", uuid, None))

    async def squad_remove_all_users(self, uuid):
        FakePanel.calls.append(("REMOVE-ALL", uuid, None))


@pytest.fixture
def panel(monkeypatch):
    from app import remnawave
    FakePanel.calls = []
    monkeypatch.setattr(remnawave, "RemnawaveClient", FakePanel)
    return FakePanel.calls


ADMIN = SimpleNamespace(id=1, email="owner@corgi.test", role="admin")


@pytest.mark.asyncio
async def test_hosts_editor_goes_to_the_panel_contract(panel):
    edit = panel_admin.HostEdit(remark="NL", address="nl.corgi.test", port=443, profile="p-1", inbound="i-1", sni="nl.corgi.test", tag="NL_1")
    assert (await panel_admin.host_create(edit, ADMIN))["host"]["uuid"] == "h-1"
    method, path, body = panel[-1]
    assert (method, path) == ("POST", "/api/hosts")
    assert body["inbound"] == {"configProfileUuid": "p-1", "configProfileInboundUuid": "i-1"} and body["host"] is None and body["tag"] == "NL_1"
    await panel_admin.host_update("h-1", edit, ADMIN)
    assert panel[-1][:2] == ("PATCH", "/api/hosts") and panel[-1][2]["uuid"] == "h-1"
    assert await panel_admin.host_delete("h-1", ADMIN) == {"ok": True}
    assert panel[-1][:2] == ("DELETE", "/api/hosts/h-1")
    await panel_admin.set_host("h-1", panel_admin.HostIn(disabled=True), ADMIN)
    assert panel[-1][:3] == ("POST", "/api/hosts/bulk/disable", {"uuids": ["h-1"]})
    await panel_admin.set_host("h-1", panel_admin.HostIn(disabled=False), ADMIN)
    assert panel[-1][1] == "/api/hosts/bulk/enable"
    with pytest.raises(HTTPException) as err:  # the panel's own message reaches the admin as 502
        await panel_admin.host_create(edit.model_copy(update={"remark": "taken"}), ADMIN)
    assert err.value.status_code == 502 and "already exists" in err.value.detail
    with pytest.raises(ValueError):  # tags are the panel's upper-case format
        panel_admin.HostEdit(remark="x", address="a", port=1, profile="p", inbound="i", tag="lower")


@pytest.mark.asyncio
async def test_internal_squads_editor_and_bulk_membership(panel):
    squad = panel_admin.SquadEdit(name="Premium", inbounds=["i-1", "i-2"])
    await panel_admin.squad_create(squad, ADMIN)
    assert panel[-1] == ("POST", "/api/internal-squads", {"name": "Premium", "inbounds": ["i-1", "i-2"]})
    await panel_admin.squad_update("s-1", squad, ADMIN)
    assert panel[-1] == ("PATCH", "/api/internal-squads", {"uuid": "s-1", "name": "Premium", "inbounds": ["i-1", "i-2"]})
    await panel_admin.squad_delete("s-1", ADMIN)
    assert panel[-1][:2] == ("DELETE", "/api/internal-squads/s-1")
    await panel_admin.squad_bulk("s-1", "add-all", ADMIN)
    assert panel[-1][:2] == ("ADD-ALL", "s-1")
    await panel_admin.squad_bulk("s-1", "remove-all", ADMIN)
    assert panel[-1][:2] == ("REMOVE-ALL", "s-1")
    with pytest.raises(HTTPException) as err:
        await panel_admin.squad_bulk("s-1", "drop-everything", ADMIN)
    assert err.value.status_code == 404
    with pytest.raises(ValueError):
        panel_admin.SquadEdit(name="bad;name")


def archive(path, members):
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


@pytest.mark.asyncio
async def test_backup_settings_run_and_archive_validation(database, monkeypatch, tmp_path):
    db = database
    monkeypatch.setattr(shop.settings, "backups_dir", str(tmp_path))
    with pytest.raises(HTTPException) as err:
        await backups_api.update_backup_config(backups_api.BackupConfigIn(schedule="5m"), db, ADMIN)
    assert err.value.status_code == 400
    with pytest.raises(HTTPException) as err:  # .env never leaves unencrypted
        await backups_api.update_backup_config(backups_api.BackupConfigIn(encrypt=False, include_env=True), db, ADMIN)
    assert err.value.status_code == 400
    with pytest.raises(HTTPException) as err:  # encryption needs a password
        await backups_api.update_backup_config(backups_api.BackupConfigIn(), db, ADMIN)
    assert err.value.status_code == 400
    out = await backups_api.update_backup_config(backups_api.BackupConfigIn(schedule="12h", retention=5, password="long-backup-password"), db, ADMIN)
    assert out["schedule"] == "12h" and out["retention"] == 5 and out["password_configured"] is True
    stored = (await db.execute(select(AppSetting.value).where(AppSetting.key == "backup_password"))).scalar_one()
    assert stored != "long-backup-password" and shop.decrypt_secret(stored) == "long-backup-password"
    assert (await db.execute(select(AuditLog).where(AuditLog.action == "backup.config.updated"))).scalars().first()

    async def broken(db, actor):
        raise RuntimeError("pg_dump: connection refused")
    monkeypatch.setattr(shop, "create_project_backup", broken)
    with pytest.raises(HTTPException) as err:  # the internal error stays in the log
        await backups_api.run_backup(db, ADMIN)
    assert err.value.status_code == 500 and err.value.detail == "Backup failed"

    async def made(db, actor):
        return {"id": 7, "status": "completed", "actor": actor}
    monkeypatch.setattr(shop, "create_project_backup", made)
    assert (await backups_api.run_backup(db, ADMIN))["actor"] == "owner@corgi.test"

    archive(tmp_path / "good.tar.gz", {"database.sql": b"select 1;", "media/a.png": b"x"})
    archive(tmp_path / "evil.tar.gz", {"database.sql": b"", "../escape": b"x"})
    archive(tmp_path / "empty.tar.gz", {"media/a.png": b"x"})
    jobs = [BackupJob(status="completed", filename=name, sha256="0" * 64) for name in ("good.tar.gz", "evil.tar.gz", "empty.tar.gz")]
    db.add_all(jobs)
    await db.commit()
    good = await backups_api.validate_backup_archive(jobs[0].id, db, ADMIN)
    assert good["ok"] and good["members"] == 2
    for job in jobs[1:]:
        with pytest.raises(HTTPException) as err:
            await backups_api.validate_backup_archive(job.id, db, ADMIN)
        assert err.value.status_code == 400
    with pytest.raises(HTTPException) as err:
        await backups_api.validate_backup_archive(999, db, ADMIN)
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_restore_needs_two_different_mfa_admins(database, monkeypatch, tmp_path):
    db = database
    monkeypatch.setattr(restore_approval.settings, "backups_dir", str(tmp_path))
    monkeypatch.setattr(restore_approval, "verify_totp", lambda admin, otp: otp == "123456")
    first = AdminUser(email="first@corgi.test", password_hash="x", role="admin", mfa_enabled=True)
    second = AdminUser(email="second@corgi.test", password_hash="x", role="admin", mfa_enabled=True)
    job = BackupJob(status="completed", filename="b.tar.gz", sha256="a" * 64)
    db.add_all([first, second, job])
    await db.commit()
    code = backups_api.RestoreApprovalIn(otp="123456")
    with pytest.raises(HTTPException) as err:
        await backups_api.request_restore(job.id, backups_api.RestoreApprovalIn(otp="000000"), db, first)
    assert err.value.status_code == 401
    approval = (await backups_api.request_restore(job.id, code, db, first))["approval_id"]
    again = code.model_copy(update={"approval_id": approval})
    with pytest.raises(HTTPException) as err:  # the requester cannot approve their own restore
        await backups_api.approve_restore(job.id, again, db, first)
    assert err.value.status_code == 403
    assert await backups_api.approve_restore(job.id, again, db, second) == {"ok": True}
    with pytest.raises(HTTPException) as err:  # exactly once
        await backups_api.approve_restore(job.id, again, db, second)
    assert err.value.status_code == 403
    assert (tmp_path / "restore-audit.jsonl").read_text().count("backup.restore") == 2


@pytest.mark.asyncio
async def test_telegram_backup_now_and_provisioning_retry(database, monkeypatch):
    db = database

    async def failing(db, **kw):
        raise RuntimeError("Укажите ID чата для копий")
    monkeypatch.setattr(telegram_backup, "run_backup", failing)
    with pytest.raises(HTTPException) as err:
        await telegram_backup.send_now(db, ADMIN)
    assert err.value.status_code == 409

    async def sent(db, **kw):
        return {"parts": 1, "bytes": 1024}
    monkeypatch.setattr(telegram_backup, "run_backup", sent)
    assert await telegram_backup.send_now(db, ADMIN) == {"parts": 1, "bytes": 1024}
    assert (await db.execute(select(AuditLog).where(AuditLog.action == "backups.telegram.sent"))).scalars().first()

    op = ProvisioningOperation(payment_id=41, user_id=1, operation_key="pay-41", status="failed", last_error="timeout")
    db.add(op)
    await db.commit()
    done = []

    async def fulfil(payment_id, db):
        done.append(payment_id)
    monkeypatch.setattr(shop, "fulfill", fulfil)
    assert await recovery_api.retry_operation(op.id, db, ADMIN) == {"ok": True, "status": "completed"}
    assert done == [41]

    async def still_down(payment_id, db):
        raise RuntimeError("Remnawave 503 with internal details")
    monkeypatch.setattr(shop, "fulfill", still_down)
    out = await recovery_api.retry_operation(op.id, db, ADMIN)
    assert out["ok"] is False and "503" not in out["error"]
    with pytest.raises(HTTPException) as err:
        await recovery_api.retry_operation(999, db, ADMIN)
    assert err.value.status_code == 404
