from main_source import main_source
"""Regressions for reseller privileges, backup member types and mobile proof."""
import io
import ast
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

def _validate_tar_safety(tar):
    # Extract the real function and its limits without importing app.main, whose
    # module initialization creates /data/media (unavailable on CI runners).
    root = Path(__file__).resolve().parents[1] / "backend/app/main.py"
    source = main_source()
    tree = ast.parse(source)
    nodes = [node for node in tree.body if isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id.startswith("MAX_BACKUP_") for target in node.targets)]
    nodes += [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_validate_tar_safety"]
    namespace = {"tarfile": tarfile, "HTTPException": HTTPException, "pathlib": __import__("pathlib")}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(root), "exec"), namespace)
    namespace["_validate_tar_safety"](tar)


@pytest.mark.parametrize("path,method", [
    ("/api/admin/marketplace/resellers", "POST"),
    ("/api/admin/marketplace/resellers/{reseller_id}", "PATCH"),
    ("/api/admin/marketplace/resellers/{reseller_id}/rotate-key", "POST"),
])
def test_reseller_mutations_reject_operator_permission(path, method):
    from app.marketplace_api import router
    from app.security import PERMISSIONS

    route = next(r for r in router.routes if r.path == path and method in r.methods)
    permissions = [dep.call for dep in route.dependant.dependencies]
    permission = next(fn for fn in permissions if fn.__name__ == "dependency")
    assert "referrals.read" in PERMISSIONS["operator"]
    assert "referrals.reconcile" not in PERMISSIONS["operator"]
    import asyncio
    with pytest.raises(HTTPException) as error:
        asyncio.run(permission(SimpleNamespace(role="operator")))
    assert error.value.status_code == 403
    assert asyncio.run(permission(SimpleNamespace(role="admin"))).role == "admin"


@pytest.mark.parametrize("kind", [tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_backup_rejects_special_tar_members(kind):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        member = tarfile.TarInfo("media/special")
        member.type = kind
        tar.addfile(member)
    stream.seek(0)
    with tarfile.open(fileobj=stream, mode="r:gz") as tar:
        with pytest.raises(HTTPException) as error:
            _validate_tar_safety(tar)
    assert error.value.status_code == 400


def test_backup_accepts_regular_file_and_directory():
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        folder = tarfile.TarInfo("media/")
        folder.type = tarfile.DIRTYPE
        tar.addfile(folder)
        data = b"SELECT 1;"
        member = tarfile.TarInfo("database.sql")
        member.size = len(data)
        tar.addfile(member, io.BytesIO(data))
    stream.seek(0)
    with tarfile.open(fileobj=stream, mode="r:gz") as tar:
        _validate_tar_safety(tar)


def test_backup_rejects_duplicate_sql_members():
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        for _ in range(2):
            member = tarfile.TarInfo("database.sql")
            member.size = 1
            tar.addfile(member, io.BytesIO(b"x"))
    stream.seek(0)
    with tarfile.open(fileobj=stream, mode="r:gz") as tar:
        with pytest.raises(HTTPException) as error:
            _validate_tar_safety(tar)
    assert error.value.status_code == 400


def test_missing_mobile_proof_key_is_fail_closed(monkeypatch):
    from app.config import settings
    from app.mobile_auth import require_mobile_proof

    monkeypatch.setattr(settings, "mobile_require_proof", True)
    monkeypatch.setattr(settings, "mobile_client_key", "")
    request = SimpleNamespace(headers={"x-shop-client": "android-user"}, method="GET", url=SimpleNamespace(path="/api/me", hostname=settings.api_domain))
    with pytest.raises(HTTPException) as error:
        require_mobile_proof(request)
    assert error.value.status_code == 503
