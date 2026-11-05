"""v28.78.0 (stage 18): «Доступ к панели → Вход через магазин» with the real Caddy image and the wizard's Caddyfile
(scripts/ci/panel-gate-live.sh, CI job «panel-gate»). The shop's panel_gate router runs here over SQLite on
127.0.0.1:18110 (the panel's Caddy calls it as it would call https://<API_DOMAIN>); a stub answers for the panel.

* a browser without the cookie is sent to the shop's admin panel, other clients get 401;
* the shop's bearer API calls and subscriptions reach the panel without a login;
* the one-time link sets the panel domain's cookie through the panel's own Caddy, and the panel opens;
* the link works once. Skipped unless GATE_LIVE=1."""
import asyncio
import http.server
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("GATE_LIVE") != "1", reason="no Docker Caddy for the panel gate test")
PANEL = "panel.corgi-ci.example.com"
PORT = 18110
BROWSER = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


class Stub(http.server.BaseHTTPRequestHandler):
    def answer(self):
        body = f"PANEL {self.command} {self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    do_GET = do_POST = answer

    def log_message(self, *a):
        pass


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def set(self, key, value, ex=None, nx=False):
        self.data[key] = value
        return True

    async def getdel(self, key):
        return self.data.pop(key, None)


def shop_app():
    import uvicorn
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app import main, panel_gate
    from app.db import get_db
    from app.models import AdminUser, Base, RemnawaveInstallation

    engine = create_async_engine("sqlite+aiosqlite:////tmp/panel-gate-live.sqlite3")
    main.redis_client = FakeRedis()
    panel_gate.settings.admin_domain = "admin.corgi-ci.example.com"

    async def prepare():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine) as db:
            db.add(AdminUser(id=1, email="ops@corgi.test", password_hash="x", role="admin"))
            db.add(RemnawaveInstallation(id=1, created_by="ci", action="install", mode="panel", server_ids=[1], status="succeeded", plan={}, plan_sha256="0" * 64,
                                         params={"panel_server_id": 1, "panel_domain": PANEL, "panel_access": "gate"}))
            await db.commit()
    asyncio.run(prepare())
    app = FastAPI()
    app.include_router(panel_gate.router)

    @app.post("/test/ticket")
    async def ticket():
        async with AsyncSession(engine) as db:
            admin = await db.get(AdminUser, 1)
            return await panel_gate.open_ticket(db, 1, admin)

    async def database():
        async with AsyncSession(engine) as db:
            yield db
    app.dependency_overrides[get_db] = database
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def curl(url, *extra):
    host = url.split("/")[2]
    out = subprocess.run(["curl", "-sk", "--max-time", "15", "-A", BROWSER, "--resolve", f"{host}:443:127.0.0.1", "-o", "/tmp/gate-body",
                          "-w", "%{http_code} %{redirect_url}", *extra, url], capture_output=True, text=True)
    code, _, location = out.stdout.partition(" ")
    body = Path("/tmp/gate-body").read_text(errors="replace") if Path("/tmp/gate-body").exists() else ""
    return code, location.strip(), body


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    from app import rw_plan
    panel = http.server.ThreadingHTTPServer(("127.0.0.1", 3000), Stub)
    threading.Thread(target=panel.serve_forever, daemon=True).start()
    threading.Thread(target=shop_app, daemon=True).start()
    directory = tmp_path_factory.mktemp("caddy")
    (directory / "Caddyfile").write_text(rw_plan.caddyfile({PANEL: 3000}, "internal", None, gate={PANEL: f"http://127.0.0.1:{PORT}"}))
    (directory / "docker-compose.yml").write_text(rw_plan.caddy_compose())
    up = subprocess.run(["docker", "compose", "up", "-d", "--quiet-pull"], cwd=directory, capture_output=True, text=True)
    assert up.returncode == 0, up.stderr[-2000:]
    try:
        for _ in range(60):
            if curl(f"https://{PANEL}/api/sub/x")[0] == "200":
                break
            time.sleep(2)
        yield
    finally:
        logs = subprocess.run(["docker", "compose", "logs", "--no-color", "--tail", "40"], cwd=directory, capture_output=True, text=True)
        print(logs.stdout[-5000:])
        subprocess.run(["docker", "compose", "down", "-v"], cwd=directory, capture_output=True)
        panel.shutdown()


def ticket_url():
    import json
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/test/ticket", method="POST")) as r:
        return json.loads(r.read())["url"]


def test_pages_ask_the_shop(stack):
    code, location, body = curl(f"https://{PANEL}/")
    assert (code, location) == ("302", "https://admin.corgi-ci.example.com/#rwInstaller") and "PANEL" not in body
    assert curl(f"https://{PANEL}/api/auth/status", "-A", "curl/8")[0] == "401"


def test_shop_api_and_subscriptions_pass(stack):
    assert curl(f"https://{PANEL}/api/users", "-H", "Authorization: Bearer shop-token")[2] == "PANEL GET /api/users"
    assert curl(f"https://{PANEL}/api/sub/AbCdEf123456")[2] == "PANEL GET /api/sub/AbCdEf123456"


def test_one_time_link_opens_the_panel(stack, tmp_path):
    jar = str(tmp_path / "jar")
    url = ticket_url()
    assert url.startswith(f"https://{PANEL}/__corgi_gate?t=")
    code, location, body = curl(url, "-c", jar)
    assert (code, location) == ("302", f"https://{PANEL}/"), body[:300]
    assert "corgi_gate" in Path(jar).read_text() and PANEL in Path(jar).read_text()
    code, _, body = curl(f"https://{PANEL}/api/auth/status", "-b", jar)
    assert (code, body) == ("200", "PANEL GET /api/auth/status")
    assert curl(url, "-c", str(tmp_path / "jar2"))[0] == "401", "the link works once"
