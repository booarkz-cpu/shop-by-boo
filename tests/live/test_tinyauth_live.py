"""v28.78.0 (stage 18): the wizard's files for «Доступ к панели → Вход через TinyAuth» with the real TinyAuth and Caddy
images (scripts/ci/tinyauth-live.sh, CI job «tinyauth»). A stub answers for the panel on 127.0.0.1:3000.

* the panel's pages send a browser without a session to the login page on the TinyAuth domain;
* requests with a bearer token to /api/ (the shop) and subscriptions /api/sub/ reach the panel without a login;
* after logging in with the generated password the same browser opens the panel's pages; a wrong password does not.

Caddy uses its internal CA (no public DNS in CI); curl resolves the names to 127.0.0.1. Skipped unless TINYAUTH_LIVE=1."""
import http.server
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from app import rw_plan, rw_steps

pytestmark = pytest.mark.skipif(os.environ.get("TINYAUTH_LIVE") != "1", reason="no Docker for the TinyAuth test")
PANEL, AUTH = "panel.corgi-ci.example.com", "auth.corgi-ci.example.com"


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


def curl(url, *extra):
    host = url.split("/")[2]
    out = subprocess.run(["curl", "-sk", "--max-time", "15", "--resolve", f"{host}:443:127.0.0.1", "-o", "/tmp/ta-body",
                          "-w", "%{http_code} %{redirect_url}", *extra, url], capture_output=True, text=True)
    code, _, location = out.stdout.partition(" ")
    body = Path("/tmp/ta-body").read_text(errors="replace") if Path("/tmp/ta-body").exists() else ""
    return code, location.strip(), body


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 3000), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    plan = rw_plan.PlanIn(mode="panel", panel_server_id=1, panel_domain=PANEL, tls="internal", panel_access="tinyauth", auth_domain=AUTH)
    ctx = rw_steps.Context(plan=plan, servers={1: {"name": "ci", "host": "127.0.0.1"}}, secrets=rw_steps.new_secrets(), state={})
    import asyncio
    files = asyncio.run(rw_steps.files_for(ctx, "proxy", 1))
    directory = tmp_path_factory.mktemp("caddy")
    for name, content in files.items():
        (directory / name).write_text(content)
    up = subprocess.run(["docker", "compose", "up", "-d", "--quiet-pull"], cwd=directory, capture_output=True, text=True)
    assert up.returncode == 0, up.stderr[-2000:]
    try:
        for _ in range(60):
            if curl(f"https://{AUTH}/api/healthz")[0] == "200":
                break
            time.sleep(2)
        digest = subprocess.run(["docker", "inspect", "--format", "{{index .RepoDigests 0}}", rw_plan.IMAGES["tinyauth"].split("@")[0]],
                                capture_output=True, text=True).stdout.strip()
        print(f"\nTinyAuth image: {digest}")
        yield ctx.secrets
    finally:
        logs = subprocess.run(["docker", "compose", "logs", "--no-color", "--tail", "60"], cwd=directory, capture_output=True, text=True)
        print(logs.stdout[-6000:])
        subprocess.run(["docker", "compose", "down", "-v"], cwd=directory, capture_output=True)
        server.shutdown()


def test_portal_answers(stack):
    assert curl(f"https://{AUTH}/api/healthz")[0] == "200"


def test_pages_need_a_login(stack):
    for path in ("/", "/api/auth/status", "/api/users"):
        code, location, body = curl(f"https://{PANEL}{path}")
        assert code in ("302", "307"), (path, code, body[:200])
        assert location.startswith(f"https://{AUTH}/"), location
        assert "PANEL" not in body


def test_shop_api_and_subscriptions_pass(stack):
    code, _, body = curl(f"https://{PANEL}/api/users", "-H", "Authorization: Bearer shop-token")
    assert (code, body) == ("200", "PANEL GET /api/users")
    code, _, body = curl(f"https://{PANEL}/api/sub/AbCdEf123456")
    assert (code, body) == ("200", "PANEL GET /api/sub/AbCdEf123456")


def test_login_opens_the_panel(stack, tmp_path):
    jar = str(tmp_path / "jar")
    wrong = json.dumps({"username": stack["tinyauth_username"], "password": "not-the-password"})
    code, _, _ = curl(f"https://{AUTH}/api/user/login", "-c", jar, "-H", "Content-Type: application/json", "-d", wrong)
    assert code in ("401", "403", "429"), code
    assert curl(f"https://{PANEL}/", "-b", jar)[0] in ("302", "307")
    good = json.dumps({"username": stack["tinyauth_username"], "password": stack["tinyauth_password"]})
    code, _, body = curl(f"https://{AUTH}/api/user/login", "-c", jar, "-H", "Content-Type: application/json", "-d", good)
    assert code == "200", body[:300]
    code, _, body = curl(f"https://{PANEL}/api/auth/status", "-b", jar)
    assert (code, body) == ("200", "PANEL GET /api/auth/status"), "the session cookie is set for the common parent domain"
