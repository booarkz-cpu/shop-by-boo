import ast
import io
import pathlib
import tarfile

import pytest
import yaml
from fastapi import HTTPException

from app import main as shop
from app_contract import env_names, missing_paths, revision, tables

ROOT=pathlib.Path(__file__).resolve().parents[1]

def read(p): return p.read_text(encoding="utf-8")

def test_all_python_parse():
    for p in (ROOT/"backend").rglob("*.py"): ast.parse(read(p))

def test_v21_contracts():
    from app import remnawave
    from app.security import PERMISSIONS
    assert not missing_paths('/metrics', '/api/admin/payments/reconcile', '/api/admin/sessions/revoke-all', '/api/me/connection-qr', '/api/me/auto-renew')
    assert all(callable(getattr(shop, n)) for n in ('auto_renew_scheduler', 'reconciliation_scheduler', '_safe_extract_members'))
    assert {'payment_provider_events', 'referral_ledger', 'auto_renew_methods'} <= set(tables())
    assert issubclass(remnawave.RemnawaveCircuitOpen, Exception) and 'REMNAWAVE_CB_FAILURES' in env_names()
    assert {'security.stepup', 'payments.reconcile'} <= PERMISSIONS['admin']

def test_worker_is_separate():
    c=yaml.safe_load(read(ROOT/"docker-compose.yml"))
    assert 'worker' in c['services'] and c['services']['worker']['command']==['python','worker.py']

def test_compose_ports():
    c=yaml.safe_load(read(ROOT/"docker-compose.yml"))
    assert set(c['services']['caddy']['ports'])=={'80:80','443:443','443:443/udp'}
    for name in ['db','redis','backend','worker','bot','admin','miniapp']: assert not c['services'][name].get('ports')

def test_admin_ui_contracts():
    s=read(ROOT/"admin/src/main.tsx"); assert '/api/admin/payments/reconcile' in s; assert '/api/admin/sessions/revoke-all' in s; assert 'req("/health")' in s

def test_miniapp_contracts():
    from frontend_sources import miniapp_sources; s=miniapp_sources(); assert '/api/me/connection-qr' in s; assert 'Автопродление' in s; assert 'Реферальная программа' in s

def _tar(*names):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name in names:
            info = tarfile.TarInfo(name)
            info.size = 2
            tar.addfile(info, io.BytesIO(b"ok"))
    raw.seek(0)
    return tarfile.open(fileobj=raw, mode="r")


def test_restore_never_writes_outside_its_folder(tmp_path):
    for evil in ("../evil.sql", "/etc/cron.d/evil", "db/../../evil"):
        with pytest.raises(HTTPException) as refused:
            shop._validate_tar_safety(_tar("db.sql", evil))
        assert refused.value.status_code == 400, evil
    with pytest.raises(HTTPException):
        shop._validate_tar_safety(_tar("db.sql", "db.sql"))  # duplicates could hide a second payload
    shop._validate_tar_safety(_tar("db.sql", "media/logo.png"))
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(HTTPException):
        shop._safe_extract_members(_tar("../outside.txt"), {"../outside.txt"}, work)
    assert not (tmp_path / "outside.txt").exists()
    shop._safe_extract_members(_tar("db.sql", "skip.txt"), {"db.sql"}, work)
    assert (work / "db.sql").read_bytes() == b"ok" and not (work / "skip.txt").exists(), "only the named members"


def test_migration_chain():
    assert revision('0009_v20_v21').down_revision == '0008_v16_v19'
