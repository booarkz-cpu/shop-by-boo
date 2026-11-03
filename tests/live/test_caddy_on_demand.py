"""The shop's real deploy/Caddyfile with the pinned Caddy image: a portal domain added in the Domain Manager gets a
certificate on demand, any other name does not (scripts/ci/caddy-on-demand-live.sh, CI job «caddy»).

The backend's /caddy/ask runs here from the same router as in production, over SQLite. The only change to the file
is ``local_certs`` in the global options: CI has no public DNS for ACME, so Caddy's internal CA signs instead.
Skipped unless CADDY_LIVE=1."""
import asyncio
import os
import socket
import ssl
import subprocess
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CADDY_LIVE") != "1", reason="no Docker Caddy for the on-demand test")
ROOT = Path(__file__).resolve().parents[2]
PORT = 18000


def serve_backend():
    import uvicorn
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app import rw_domains
    from app.db import get_db
    from app.models import Base, RemnawaveDomain

    engine = create_async_engine("sqlite+aiosqlite:////tmp/caddy-live.sqlite3")

    async def prepare():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine) as db:
            db.add(RemnawaveDomain(domain="sub.ci.test", purpose="subscription", served_by="shop", created_by="ci"))
            db.add(RemnawaveDomain(domain="off.ci.test", purpose="subscription", served_by="shop", created_by="ci", enabled=False))
            await db.commit()
    asyncio.run(prepare())
    app = FastAPI()
    app.include_router(rw_domains.router)

    async def database():
        async with AsyncSession(engine) as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.router.on_startup.clear()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def handshake(name: str) -> str:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection(("127.0.0.1", 443), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=name) as tls:
            from cryptography import x509
            cert = x509.load_der_x509_certificate(tls.getpeercert(binary_form=True))
            return ",".join(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName))


def test_portal_domain_gets_a_certificate_on_demand(tmp_path):
    threading.Thread(target=serve_backend, daemon=True).start()
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
            break
        except OSError:
            time.sleep(0.2)
    text = (ROOT / "deploy/Caddyfile").read_text()
    assert text.count("on_demand_tls {") == 1
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text(text.replace("    on_demand_tls {", "    local_certs\n    on_demand_tls {", 1))
    image = os.environ["CADDY_IMAGE"]
    env = {"CADDY_ASK_URL": f"http://127.0.0.1:{PORT}/caddy/ask", "BACKEND_UPSTREAM": f"127.0.0.1:{PORT}", "API_DOMAIN": "api.ci.test",
           "ADMIN_DOMAIN": "admin.ci.test", "APP_DOMAIN": "app.ci.test", "CABINET_DOMAIN": "cabinet.ci.test",
           "SUPPORT_PRO_DOMAIN": "support.ci.test", "SUPPORT_UPSTREAM": "127.0.0.1:1"}
    args = ["docker", "run", "-d", "--name", "caddy-live", "--network", "host", "-v", f"{caddyfile}:/etc/caddy/Caddyfile:ro"]
    for key, value in env.items():
        args += ["-e", f"{key}={value}"]
    subprocess.run([*args, image], check=True, capture_output=True)
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", 443), timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        names = ""
        for _ in range(20):
            try:
                names = handshake("sub.ci.test")
                break
            except (ssl.SSLError, OSError):
                time.sleep(1)
        assert "sub.ci.test" in names, "an enabled portal domain got its certificate on demand"
        for refused in ("other.ci.test", "off.ci.test"):
            with pytest.raises((ssl.SSLError, OSError)):
                handshake(refused)
        out = subprocess.run(["curl", "-sk", "--resolve", "sub.ci.test:443:127.0.0.1", "-o", "/dev/null", "-w", "%{http_code}",
                              "https://sub.ci.test/caddy/ask?domain=sub.ci.test"], capture_output=True, text=True).stdout
        assert out == "404", "the on-demand question is not reachable from outside"
    finally:
        logs = subprocess.run(["docker", "logs", "--tail", "30", "caddy-live"], capture_output=True, text=True)
        print(logs.stdout[-3000:], logs.stderr[-3000:])
        subprocess.run(["docker", "rm", "-f", "caddy-live"], capture_output=True)
