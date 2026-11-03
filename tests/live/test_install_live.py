"""The installation wizard for real: «panel + node» on a clean server over SSH (scripts/ci/rw-install-live.sh).

The CI runner plays the VPS: sshd with a root key, Docker, nothing on ports 80/443/3000. The test goes through the
same API functions and runner as the admin panel — registry, check, plan, approval, the worker's runner — with the
pinned images of rw_plan.IMAGES, TLS from Caddy's internal CA (there is no public DNS name), then «update» and
«remove». Skipped unless RW_INSTALL_HOST, RW_INSTALL_KEY_FILE and RW_INSTALL_FINGERPRINT are set."""
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import rw_api, rw_jobs, rw_plan
from app.models import Base, RemnawaveInstallation

HOST = os.environ.get("RW_INSTALL_HOST")
KEY_FILE = os.environ.get("RW_INSTALL_KEY_FILE")
FINGERPRINT = os.environ.get("RW_INSTALL_FINGERPRINT")
pytestmark = pytest.mark.skipif(not (HOST and KEY_FILE and FINGERPRINT), reason="no test server for the installer")
ADMIN = SimpleNamespace(email="ci@corgi.test", role="admin")


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/install.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


async def run(db, installation_id):
    while await rw_jobs.run_next(db.bind, "ci-worker"):
        pass
    db.expire_all()
    out = await rw_api.get_installation(installation_id, db, ADMIN)
    for st in out["steps"]:
        print(f"--- {st['position']}. {st['title']}: {st['status']}\n{st['log'] or ''}")
    return out


def containers():
    names = subprocess.run(["sudo", "docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, check=True).stdout.split()
    return set(names)


@pytest.mark.asyncio
async def test_panel_and_node_on_a_clean_server(db):
    scanned = await rw_api.scan(rw_api.ScanIn(host=HOST, ssh_port=22), ADMIN)
    assert scanned["fingerprint"] == FINGERPRINT, "the host key read over SSH matches ssh-keygen's"
    server = await rw_api.create_server(rw_api.ServerIn(
        name="ci-vps", host=HOST, ssh_user="root", auth_method="key", private_key=Path(KEY_FILE).read_text(),
        host_key_fingerprint=FINGERPRINT, purpose=["panel", "node"]), db, ADMIN)
    checked = await rw_api.check_server(server["id"], db, ADMIN)
    print({c["key"]: (c["status"], c["detail"]) for c in checked["checks"]})
    assert checked["status"] == "ready" and checked["arch"] in ("x86_64", "aarch64")

    planned = await rw_api.plan_installation(rw_plan.PlanIn(mode="panel_node", panel_server_id=server["id"], panel_domain="panel.corgi.test",
                                                            tls="internal", firewall=False), db, ADMIN)
    await rw_api.approve(planned["id"], rw_api.ApproveIn(plan_sha256=planned["plan_sha256"]), db, ADMIN)
    out = await run(db, planned["id"])
    assert out["status"] == "succeeded", out["error"]
    assert {"remnawave", "remnawave-db", "remnawave-redis", "remnanode", "remnawave-caddy"} <= containers()
    row = await db.get(RemnawaveInstallation, planned["id"])
    state = row.result["state"]
    assert len(state["nodes"]) == 1, "the node was registered and the verify step saw it connected"
    images = subprocess.run(["sudo", "docker", "inspect", "-f", "{{.Config.Image}}", "remnawave", "remnanode"],
                            capture_output=True, text=True, check=True).stdout.split()
    assert images == [rw_plan.IMAGES["panel"], rw_plan.IMAGES["node"]], "the pinned images run"
    creds = await rw_api.credentials(planned["id"], db, ADMIN)
    assert creds["username"] == "corgi-admin"

    for action in ("diagnose", "update", "remove"):
        step = await rw_api.action(planned["id"], rw_api.ActionIn(action=action), db, ADMIN)
        await rw_api.approve(step["id"], rw_api.ApproveIn(plan_sha256=step["plan_sha256"]), db, ADMIN)
        done = await run(db, step["id"])
        assert done["status"] == "succeeded", (action, done["error"])
    assert not {"remnawave", "remnanode", "remnawave-caddy"} & containers(), "remove stopped the containers"
    volumes = subprocess.run(["sudo", "docker", "volume", "ls", "--format", "{{.Name}}"], capture_output=True, text=True, check=True).stdout
    assert "remnawave-db-data" in volumes, "the panel's data stays after removal"
