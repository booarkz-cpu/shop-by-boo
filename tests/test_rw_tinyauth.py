"""v28.78.0 (stage 18): the installation wizard can put the panel's pages behind TinyAuth — a login portal on its own
domain (tinyauthapp/tinyauth, GPL-3.0, run as a separate container). The real container and Caddy are checked in CI
by tests/live/test_tinyauth_live.py; here — the plan, the files and the credentials."""
import json

import pytest
from pydantic import ValidationError

from app import rw_plan, rw_steps

SERVERS = {1: {"name": "s1", "host": "93.184.216.34"}}


def plan(**extra):
    return rw_plan.PlanIn(mode="panel", panel_server_id=1, panel_domain="panel.example.com", tls="internal",
                          panel_access="tinyauth", auth_domain="Auth.Example.com.", **extra)


def test_plan_needs_a_sibling_domain():
    assert plan().auth_domain == "auth.example.com"
    for bad in ({"auth_domain": None}, {"auth_domain": "panel.example.com"}, {"auth_domain": "auth.other.org"},
                {"auth_domain": "auth.com"}, {"auth_domain": "auth.example.com\n{"}):
        with pytest.raises(ValidationError):
            rw_plan.PlanIn(**{**dict(mode="panel", panel_server_id=1, panel_domain="panel.example.com", tls="internal",
                                     panel_access="tinyauth"), **bad})
    with pytest.raises(ValidationError):  # only for a panel the wizard installs
        rw_plan.PlanIn(mode="node", node_server_ids=[2], panel_access="tinyauth", auth_domain="auth.example.com")
    deep = rw_plan.PlanIn(mode="panel", panel_server_id=1, panel_domain="panel.vpn.example.com", tls="internal",
                          panel_access="tinyauth", auth_domain="auth.vpn.example.com")
    assert deep.auth_domain == "auth.vpn.example.com"
    assert rw_plan.PlanIn(mode="panel", panel_server_id=1, panel_domain="panel.example.com", tls="internal",
                          auth_domain="auth.example.com").auth_domain is None, "kept only with TinyAuth"
    built = rw_plan.build_plan(plan(), SERVERS, None)
    assert any("TinyAuth" in c and "auth.example.com" in c for c in built["servers"]["1"]["changes"])
    [preflight] = [s for s in built["steps"] if s["kind"] == "preflight"]
    assert "auth.example.com" in preflight["params"]["domains"], "DNS of the login domain is checked before installing"
    assert json.dumps(built)


def test_caddy_guards_the_panel_pages_but_not_the_api():
    caddy = rw_plan.caddyfile({"panel.example.com": 3000, "auth.example.com": rw_plan.TINYAUTH_PORT}, "acme", "a@example.com",
                              guard={"panel.example.com": rw_plan.TINYAUTH_PORT})
    panel = caddy.split("panel.example.com {", 1)[1].split("\n}\n", 1)[0]
    assert f"forward_auth @guarded 127.0.0.1:{rw_plan.TINYAUTH_PORT} {{" in panel and "uri /api/auth/caddy" in panel
    assert "not path /api/sub/*" in panel and 'header Authorization "Bearer *"' in panel
    assert panel.index("forward_auth") < panel.index("reverse_proxy 127.0.0.1:3000")
    portal = caddy.split("auth.example.com {", 1)[1].split("\n}\n", 1)[0]
    assert "forward_auth" not in portal and f"reverse_proxy 127.0.0.1:{rw_plan.TINYAUTH_PORT}" in portal


def test_compose_and_env():
    compose = rw_plan.caddy_compose(tinyauth=True)
    assert rw_plan.IMAGES["tinyauth"] in compose and f"127.0.0.1:{rw_plan.TINYAUTH_PORT}:3000" in compose
    assert "tinyauth-data:" in compose.split("volumes:\n  caddy-data")[1]
    assert "tinyauth" not in rw_plan.caddy_compose()
    good = "$2b$12$" + "a" * 53
    env = rw_plan.tinyauth_env("auth.example.com", "corgi", good)
    assert "TINYAUTH_APPURL=https://auth.example.com\n" in env and f"TINYAUTH_AUTH_USERS='corgi:{good}'\n" in env
    assert "TINYAUTH_AUTH_SECURECOOKIE=true" in env
    for args in (("auth.example.com\n", "corgi", good), ("auth.example.com", "Bad User", good), ("auth.example.com", "corgi", "plain")):
        with pytest.raises(ValueError):
            rw_plan.tinyauth_env(*args)


@pytest.mark.asyncio
async def test_files_and_credentials_are_stable():
    import bcrypt
    ctx = rw_steps.Context(plan=plan(), servers=SERVERS, secrets=rw_steps.new_secrets(), state={})
    first = await rw_steps.files_for(ctx, "proxy", 1)
    assert set(first) == {"Caddyfile", "docker-compose.yml", ".env"}
    assert "auth.example.com {" in first["Caddyfile"] and "forward_auth @guarded" in first["Caddyfile"]
    user, digest = ctx.secrets["tinyauth_username"], ctx.secrets["tinyauth_password_hash"]
    assert bcrypt.checkpw(ctx.secrets["tinyauth_password"].encode(), digest.encode())
    assert ctx.secrets["tinyauth_password"] not in first[".env"] and f"{user}:{digest}" in first[".env"]
    assert await rw_steps.files_for(ctx, "proxy", 1) == first, "an update writes the same files (same login)"
    assert ctx.secrets["tinyauth_password"] in ctx.secret_values(), "masked in the step journal"
    other = rw_steps.Context(plan=plan(), servers=SERVERS, secrets=rw_steps.new_secrets(), state={})
    await rw_steps.files_for(other, "proxy", 1)
    assert other.secrets["tinyauth_password"] != ctx.secrets["tinyauth_password"]
    plain = rw_steps.Context(plan=rw_plan.PlanIn(mode="panel", panel_server_id=1, panel_domain="panel.example.com", tls="internal"),
                             servers=SERVERS, secrets=rw_steps.new_secrets(), state={})
    files = await rw_steps.files_for(plain, "proxy", 1)
    assert ".env" not in files and "forward_auth" not in files["Caddyfile"] and "tinyauth_password" not in plain.secrets


@pytest.mark.asyncio
async def test_verify_expects_the_login_redirect(monkeypatch):
    ctx = rw_steps.Context(plan=plan(), servers=SERVERS, secrets=rw_steps.new_secrets(), state={})
    seen = []

    async def run(ctx_, sid, script, *args, **kw):
        seen.append(args[:3])
        code = {"panel.example.com": "302", "auth.example.com": "200"}[args[0]]
        return type("R", (), {"out": code + "\n", "err": "", "code": 0})()
    monkeypatch.setattr(rw_steps, "_run", run)
    await rw_steps.run_verify(ctx, {})
    assert ("auth.example.com", "corgi-verify", "api/healthz") in seen
    assert ("panel.example.com", rw_steps.BROWSER_AGENT, "api/auth/status") in seen, "TinyAuth redirects only browsers"

    async def open_panel(ctx_, sid, script, *args, **kw):
        return type("R", (), {"out": "200\n", "err": "", "code": 0})()

    async def no_sleep(_):
        pass
    monkeypatch.setattr(rw_steps, "_run", open_panel)
    monkeypatch.setattr(rw_steps, "_sleep", no_sleep)
    with pytest.raises(rw_steps.StepError, match="без входа"):
        await rw_steps.run_verify(ctx, {})


def test_names_with_a_trailing_newline_never_reach_a_caddyfile():
    with pytest.raises(ValueError):
        rw_plan.caddyfile({"panel.example.com\n": 3000}, "internal", None)
    with pytest.raises(ValueError):
        rw_plan.caddyfile({"panel.example.com": 3000}, "internal", None, {"panel.example.com": ("rwabc123\n", "0123456789abcdef")})
