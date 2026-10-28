"""v28.38 functions taken over from remnawave-subscription-middleware (own implementation): subscription proxy with
HWID stub, rules, extra keys and the request log, client versions, panel API stats, webhook forwarding and the change
journal, term from the first connection, grace squad, sessions and anomalies, traffic by day, WireGuard pool, keys."""
import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app import main as shop
from app.models import Plan, Subscription, User
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test")
SHORT = "AbCdEfGh12345678"
PANEL_BODY = base64.b64encode(b"vless://u@host1:443?security=reality#DE\nvless://u@host2:443#NL\n")


def req(path="/sub/x", headers=(), query=b""):
    raw = [(k.lower().encode(), v.encode()) for k, v in headers]
    return Request({"type": "http", "method": "GET", "path": path, "headers": raw, "client": ("203.0.113.5", 1), "query_string": query})


@pytest.fixture
def env(database, monkeypatch):  # noqa: F811
    from app import db as dbmod, sub_proxy
    monkeypatch.setattr(dbmod, "SessionLocal", lambda: AsyncSession(database.bind, expire_on_commit=False))
    monkeypatch.setattr(shop, "redis_client", None)
    sub_proxy._state.update(cfg=dict(sub_proxy.DEFAULT), at=0.0)
    sub_proxy._index.clear()
    return SimpleNamespace(db=database)


def panel_transport(seen):
    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.path.endswith("/missing0000000"):
            return httpx.Response(404, json={"message": "not found"})
        if "second" in request.url.host:
            return httpx.Response(200, content=base64.b64encode(b"vless://u@second:443#FI\n"))
        return httpx.Response(200, content=PANEL_BODY, headers={
            "content-type": "text/plain; charset=utf-8", "profile-title": "base64:UmVtbmF3YXZl", "subscription-userinfo": "upload=0; download=0",
            "profile-web-page-url": f"https://panel.example/api/sub/{SHORT}", "set-cookie": "a=b", "server": "nginx"})
    return httpx.MockTransport(handler)


@pytest.fixture
def mock_http(monkeypatch):
    seen = []
    real = httpx.AsyncClient

    def factory(*a, **k):
        k.pop("trust_env", None)
        return real(transport=panel_transport(seen), **{x: y for x, y in k.items() if x in {"timeout", "follow_redirects"}})
    from app import sub_proxy
    monkeypatch.setattr(sub_proxy.httpx, "AsyncClient", factory)
    return seen


async def _customer(db, *, squad="sq-main", active=True):
    db.add(User(id=901, telegram_id=901901, referral_code="SP901"))
    db.add(Plan(id=901, name="Месяц", price=199, duration_days=30))
    db.add(Subscription(id=901, user_id=901, plan_id=901, remnawave_uuid="42", subscription_url=f"https://panel.example/api/sub/{SHORT}",
                        remnawave_profile_id_snapshot=squad, expires_at=datetime.utcnow() + timedelta(days=10 if active else -1),
                        lifecycle_status="active" if active else "expired", device_limit_snapshot=2))
    await db.commit()


async def _enable(db, **extra):
    from app import sub_proxy
    payload = sub_proxy.ProxyIn(enabled=True, public_base="https://sub.corgi.ru", origin="http://remnawave:3000/api/sub", **extra)
    await sub_proxy.put_proxy(payload, db, ADMIN)


@pytest.mark.asyncio
async def test_proxy_fetches_from_the_panel_rewrites_links_and_logs(env, mock_http):
    from app import sub_proxy
    from app.models import SubRequest
    db = env.db
    await _customer(db)
    assert sub_proxy.client_url(f"https://panel.example/api/sub/{SHORT}") == f"https://panel.example/api/sub/{SHORT}", "off by default"
    with pytest.raises(Exception):
        await sub_proxy.serve(req(), SHORT, db)
    await _enable(db)
    assert sub_proxy.client_url(f"https://panel.example/api/sub/{SHORT}") == f"https://sub.corgi.ru/{SHORT}"
    assert sub_proxy.client_url("sandbox://local/1/1") == "sandbox://local/1/1"
    r = await sub_proxy.serve(req(headers=[("User-Agent", "v2rayNG/1.9.30"), ("x-hwid", "dev-1"), ("x-device-model", "Pixel 9")]), SHORT, db)
    assert r.status_code == 200 and r.body == PANEL_BODY
    assert "set-cookie" not in {k.lower() for k in r.headers} and r.headers["profile-web-page-url"] == f"https://sub.corgi.ru/{SHORT}"
    sent = mock_http[-1]
    assert str(sent.url).startswith(f"http://remnawave:3000/api/sub/{SHORT}") and sent.headers["x-hwid"] == "dev-1"
    assert sent.headers["x-forwarded-proto"] == "https", "an internal http panel needs the proxy headers"
    row = (await db.execute(select(SubRequest))).scalars().one()
    assert (row.app, row.app_version, row.model, row.decision, row.user_id) == ("v2rayNG", "1.9.30", "Pixel 9", "proxied", 901)
    # Prefix, suffix formats and the mask page.
    await _enable(db, prefix="s")
    r = await sub_proxy.serve(req(), f"s/{SHORT}/clash", db)
    assert r.status_code == 200 and str(mock_http[-1].url).split("?")[0].endswith(f"/{SHORT}/clash")
    page = await sub_proxy.serve(req(), "wp-login.php", db)
    assert page.status_code == 200 and b"<form" in page.body
    missing = await sub_proxy.serve(req(), "missing0000000", db)
    assert b"<form" in missing.body, "an unknown token looks like the same neutral page"


@pytest.mark.asyncio
async def test_blocked_device_gets_a_stub_and_hwid_from_user_agent(env, mock_http):
    from app import sub_proxy
    db = env.db
    await _customer(db)
    await _enable(db, block_text="Устройство отключено")
    await sub_proxy.block_device(sub_proxy.BlockIn(hwid="bad-phone", note="продал телефон"), db, ADMIN)
    assert sub_proxy.ua_fields("Clash/1.0 x-hwid=bad-phone x-device-os=Android") == {"x-hwid": "bad-phone", "x-device-os": "Android"}
    before = len(mock_http)
    r = await sub_proxy.serve(req(headers=[("User-Agent", "Clash/1.0 x-hwid=bad-phone")]), SHORT, db)
    assert len(mock_http) == before, "a blocked device never reaches the panel"
    body = base64.b64decode(r.body).decode()
    assert "0.0.0.0:1" in body and "%D0%A3%D1%81%D1%82%D1%80%D0%BE%D0%B9" in body and r.headers["announce"].startswith("base64:")
    await sub_proxy.unblock_device("bad-phone", db, ADMIN)
    r = await sub_proxy.serve(req(headers=[("User-Agent", "Clash/1.0 x-hwid=bad-phone")]), SHORT, db)
    assert r.body == PANEL_BODY and mock_http[-1].headers["x-hwid"] == "bad-phone", "the HWID from the User-Agent goes to the panel"


@pytest.mark.asyncio
async def test_rules_extra_keys_and_merge_only_for_active_uri_lists(env, mock_http):
    from app import sub_proxy
    db = env.db
    await _customer(db, squad="sq-main")
    await _enable(db, rules=[sub_proxy.RuleIn(name="Happ", ua="^happ", headers={"profile-title": "Корги Люси", "profile-update-interval": "2", "support-url": ""})],
                  extras=[sub_proxy.ExtraIn(name="WG", squad="sq-main", links=["wireguard://k@wg.corgi:51820#WG"]),
                          sub_proxy.ExtraIn(name="other", squad="sq-other", links=["vless://x@other:443#X"])],
                  merge_url="https://second.example/{short_uuid}")
    r = await sub_proxy.serve(req(headers=[("User-Agent", "Happ/3.1")]), SHORT, db)
    lines = base64.b64decode(r.body).decode().splitlines()
    assert lines[:2] == ["vless://u@host1:443?security=reality#DE", "vless://u@host2:443#NL"]
    assert "wireguard://k@wg.corgi:51820#WG" in lines and "vless://u@second:443#FI" in lines and not any("other" in x for x in lines)
    assert base64.b64decode(r.headers["profile-title"].removeprefix("base64:")).decode() == "Корги Люси" and r.headers["profile-update-interval"] == "2" and "support-url" not in r.headers
    assert sub_proxy.uri_list(b"proxies:\n - name: a") is None and sub_proxy.uri_list(b'{"outbounds": []}') is None
    # An expired subscription gets nothing extra.
    sub = await db.get(Subscription, 901)
    sub.expires_at = datetime.utcnow() - timedelta(hours=1)
    await db.commit()
    sub_proxy._index.clear()
    r = await sub_proxy.serve(req(headers=[("User-Agent", "Happ/3.1")]), SHORT, db)
    assert r.body == PANEL_BODY


@pytest.mark.asyncio
async def test_client_versions_mark_old_clients(env, monkeypatch):
    from app import client_versions as cv
    db = env.db
    assert cv.parse("v1.10.2") == (1, 10, 2)
    await cv.put_clients([cv.ClientIn(app="v2rayNG", repo="2dust/v2rayNG", latest="1.10.2")], db, ADMIN)
    assert await cv.is_outdated(db, "v2rayNG", "1.9.30") and not await cv.is_outdated(db, "v2rayNG", "1.10.2")
    assert not await cv.is_outdated(db, "Happ", "1.0"), "an app without a known version is never marked"

    async def latest(client, repo):
        return "1.11.0"
    monkeypatch.setattr(cv, "latest_release", latest)
    assert await cv.refresh(db, force=True) == 1
    assert (await cv.catalog(db))[0]["latest"] == "1.11.0"
    from app.sub_proxy import client_app
    assert client_app("Happ/3.2.1 (iPhone; iOS 18)") == ("Happ", "3.2.1") and client_app("clash-verge/v2.3.0") == ("Clash Verge", "2.3.0")


@pytest.mark.asyncio
async def test_panel_api_stats_and_write_journal(env):
    from app import panel_api_stats as st
    assert st.template("/api/users/42/actions/extend") == "/api/users/{x}/actions/extend"
    assert st.template("/api/connections/by-node/7c7ac3ff-8de8-4865-a0bf-e64882e5a861") == "/api/connections/by-node/{x}"
    assert st.source_for_path("/api/admin/users") == "admin" and st.source_for_path("/sub/abc") == "subscription"
    st._counts.clear()
    st.record("admin", "GET", "/api/users/42", 200, 30)
    st.record("admin", "GET", "/api/users/43", 500, 50)
    st.record("subscription", "GET", "/api/sub/{x}", 200, 20)
    await st.flush(env.db)
    rep = await st.report(env.db, 24)
    admin = next(s for s in rep["sources"] if s["source"] == "admin")
    assert rep["total"] == 3 and admin["calls"] == 2 and admin["errors"] == 1 and admin["paths"][0]["path"] == "GET /api/users/{x}"
    ref = st.user_ref("PATCH", "/api/users", {"json": {"id": "42", "expireAt": "x", "trafficLimitBytes": 1}})
    assert ref == ("42", ["expireAt", "trafficLimitBytes"])
    await st.remember_write(ref)
    assert await st.recent_writes("42") == {"expireAt", "trafficLimitBytes"}


@pytest.mark.asyncio
async def test_webhook_journal_marks_shop_and_external_changes_and_forwards(env, monkeypatch):
    from app import panel_api_stats as st, webhook_tee as tee
    from app.config import settings
    db = env.db
    await _customer(db)
    user = {"id": 42, "username": "user_1", "status": "ACTIVE", "expireAt": "2026-11-01T00:00:00Z", "trafficLimitBytes": 0,
            "activeInternalSquads": [{"uuid": "sq-main"}]}
    assert (await tee.journal(db, "user.created", {"user": user}, "42", 901))["source"] == "first"
    st._local_writes.clear()
    await st.remember_write(("42", ["expireAt"]))
    mine = await tee.journal(db, "user.modified", {"user": {**user, "expireAt": "2026-12-01T00:00:00Z"}}, "42", 901)
    assert mine == {"source": "shop", "changed": {"expireAt": ["2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z"]}}
    st._local_writes.clear()
    theirs = await tee.journal(db, "user.modified", {"user": {**user, "expireAt": "2026-12-01T00:00:00Z", "trafficLimitBytes": 5}}, "42", 901)
    assert theirs["source"] == "external" and list(theirs["changed"]) == ["trafficLimitBytes"]
    assert await tee.journal(db, "user.modified", {"user": {**user, "expireAt": "2026-12-01T00:00:00Z", "trafficLimitBytes": 5}}, "42", 901) is None
    csv = (await tee.changes_csv(anonymize=True, days=30, db=db, admin=ADMIN)).body.decode()
    assert "id1" in csv and "user_1" not in csv
    # Forwarding: re-signed per receiver.
    await tee.put_tee(tee.TeeIn(targets=[tee.TargetIn(name="bot", url="https://bot.example/hook", secret="s3cret")]), db, ADMIN)
    sent = []

    async def fake_send(url, raw, secret, headers):
        sent.append((url, tee.sign(raw, secret)))
        return True
    monkeypatch.setattr(tee, "_send", fake_send)
    raw = b'{"scope":"node","event":"node.created","data":{}}'
    assert tee.forward(await tee._config(db), raw, {}) == 1
    import asyncio
    await asyncio.sleep(0)
    assert sent == [("https://bot.example/hook", hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest())]
    assert settings is not None


@pytest.mark.asyncio
async def test_term_starts_at_the_first_connection(env, monkeypatch):
    from app import first_connect as fc
    from app.models import FirstConnectWait
    db = env.db
    await _customer(db)
    assert await fc.wait_days(db, 901, 30) == 0, "off by default"
    await fc.put_cfg(fc.FirstConnectIn(enabled=True, plans=[901], max_wait_days=30), db, ADMIN)
    assert await fc.wait_days(db, 901, 30) == 30 and await fc.wait_days(db, 901, 7) == 7 and await fc.wait_days(db, 2, 30) == 0
    sub = await db.get(Subscription, 901)
    now = datetime(2026, 11, 1)
    sub.expires_at = now + timedelta(days=60 + 30)  # 30 wait + 30 term + 30 renewed during the wait
    await fc.start_waiting(db, sub, 30, now + timedelta(days=30))
    await db.commit()
    patched = []

    class Panel:
        async def patch_user(self, uid, body):
            patched.append((uid, body))
    monkeypatch.setattr("app.remnawave.RemnawaveClient", lambda: Panel())
    assert await fc.on_first_connect(db, sub, now=now + timedelta(days=10))
    assert sub.expires_at == now + timedelta(days=70), "20 unused wait days are taken off, the renewal stays"
    assert patched[0][0] == "42" and patched[0][1]["expireAt"].startswith("2027-01-10")
    assert not await fc.on_first_connect(db, sub, now=now + timedelta(days=11)), "only once"
    assert (await db.execute(select(FirstConnectWait))).scalar_one().started_at


@pytest.mark.asyncio
async def test_grace_squad_moves_and_restores(env, monkeypatch):
    from app import grace_access as g
    db = env.db
    await _customer(db)
    sub = await db.get(Subscription, 901)
    now = datetime.utcnow()
    sub.expires_at = now + timedelta(minutes=5)
    await db.commit()
    calls = []

    class Panel:
        async def patch_user(self, uid, body):
            calls.append(body)

    async def notify(*a):
        return None
    await g.put_grace(g.GraceIn(enabled=True, hours=12, mode="squad", squad="sq-grace"), db, SimpleNamespace(email="o"))
    monkeypatch.setattr(shop, "audit", notify)
    assert await g.tick(db, now=now, panel=Panel(), notify=notify) == [901]
    assert calls[0]["activeInternalSquads"] == ["sq-grace"] and "expireAt" in calls[0]
    assert await g.restore_squads(db, 901, panel=Panel()) and calls[-1] == {"activeInternalSquads": ["sq-main"]}


@pytest.mark.asyncio
async def test_sessions_glue_snapshots_and_open_anomalies(env, monkeypatch):
    from app import vpn_sessions as vs
    from app.models import VpnSession
    db = env.db
    await _customer(db)
    await vs.put_config(vs.SessionsIn(enabled=True, rules=[vs.RuleIn(name="Страны", metric="countries", value=1, level="red"),
                                                            vs.RuleIn(name="IP", metric="ips", value=1, per_device=True)]), db, ADMIN)
    snaps = [{"42": [("DE-1", "198.51.100.1"), ("NL-1", "203.0.113.9")]}, {"42": [("DE-1", "198.51.100.1")]}]

    async def snapshot(panel):
        return snaps.pop(0)
    geo = {"198.51.100.1": ("3216", "Beeline", "RU"), "203.0.113.9": ("12389", "Rostelecom", "KZ")}

    async def fake_geo(db, ip, budget):
        return geo[ip]
    monkeypatch.setattr(vs, "snapshot", snapshot)
    monkeypatch.setattr(vs, "_geo", fake_geo)
    now = datetime.utcnow()
    first = await vs.collect(db, panel=object(), now=now)
    assert first == {"users": 1, "anomalies": 1, "opened": 1, "closed": 0}
    anomaly = (await vs.get_anomalies(db, ADMIN))["anomalies"][0]
    assert anomaly["level"] == "red" and [h["name"] for h in anomaly["hits"]] == ["Страны"], "2 IPs ≤ 1 × device limit 2"
    second = await vs.collect(db, panel=object(), now=now + timedelta(minutes=5))
    assert second["closed"] == 1 and second["anomalies"] == 0
    rows = (await db.execute(select(VpnSession))).scalars().all()
    assert len(rows) == 2 and next(r for r in rows if r.ip == "198.51.100.1").last_seen == now + timedelta(minutes=5)
    view = await vs.user_sessions(901, 30, db, ADMIN)
    assert {g["isp"] for g in view["groups"]} == {"Beeline", "Rostelecom"} and view["week"]["countries"] == 2
    assert vs._ips([{"ip": "1.1.1.1", "lastSeen": "x"}, "2.2.2.2", 5]) == ["1.1.1.1", "2.2.2.2"]


def test_traffic_shape_from_bandwidth_stats():
    from app.panel_usage import shape
    out = shape({"categories": ["2026-10-01", "2026-10-02", "2026-10-03"], "sparklineData": [100, 300, 0],
                 "topNodes": [{"name": "DE", "countryCode": "DE", "total": 300}, {"name": "NL", "total": 100}]})
    assert out["total_bytes"] == 400 and out["peak"] == {"day": "2026-10-02", "bytes": 300}
    assert [n["share"] for n in out["nodes"]] == [75.0, 25.0] and out["per_day_bytes"] == 133
    assert shape({})["days"] == [] and shape({})["peak"] is None


@pytest.mark.asyncio
async def test_wireguard_pool_hands_out_one_config_per_device(env, monkeypatch):
    from fastapi import HTTPException
    from app import wg_pool as wg
    db = env.db
    await _customer(db)
    conf = "[Interface]\nPrivateKey = {k}\nAddress = 10.0.0.{n}/32\n{extra}\n[Peer]\nPublicKey = P\nEndpoint = wg.corgi:51820\nAllowedIPs = 0.0.0.0/0\n"
    text = conf.format(k="A", n=2, extra="") + conf.format(k="B", n=3, extra="Jc = 4\nJmin = 40") + conf.format(k="C", n=4, extra="")
    assert (await wg.upload(wg.UploadIn(text=text), db, ADMIN)) == {"added": 3, "awg": 1}
    user = await db.get(User, 901)

    async def me(request, db):
        return user
    monkeypatch.setattr(shop, "user_from_token", me)
    with pytest.raises(HTTPException):
        await wg.my_wg(req(), "phone", db)
    await wg.put_pool(wg.PoolIn(enabled=True), db, ADMIN)
    first = await wg.my_wg(req(), "phone", db)
    assert "PrivateKey = A" in first["config"] and first["kind"] == "wg"
    assert (await wg.my_wg(req(), "phone", db))["config"] == first["config"], "the same device gets the same config"
    await wg.my_wg(req(), "laptop", db)
    with pytest.raises(HTTPException) as exc:
        await wg.my_wg(req(), "tablet", db)
    assert exc.value.status_code == 409, "device limit 2"
    stats = (await wg.get_pool(db, ADMIN))["stats"]
    assert stats["wg"]["assigned"] + stats.get("awg", {}).get("assigned", 0) == 2
    from app.models import WgConfig
    stored = (await db.execute(select(WgConfig))).scalars().first()
    assert "PrivateKey" not in stored.config, "configs are stored encrypted"


@pytest.mark.asyncio
async def test_subscription_keys_list(env, monkeypatch):
    from app import wg_pool as wg
    db = env.db
    await _customer(db)
    user = await db.get(User, 901)

    async def me(request, db):
        return user

    class Panel:
        async def _request(self, method, path, **kw):
            assert path == f"/api/subscriptions/by-short-uuid/{SHORT}"
            return {"links": ["vless://u@host1:443#%F0%9F%87%A9%F0%9F%87%AA%20DE", "vless://0@0.0.0.0:1#stub"]}
    monkeypatch.setattr(shop, "user_from_token", me)
    monkeypatch.setattr("app.remnawave.RemnawaveClient", lambda: Panel())
    out = await wg.my_keys(req(), db)
    assert out["keys"] == [{"name": "🇩🇪 DE", "link": "vless://u@host1:443#%F0%9F%87%A9%F0%9F%87%AA%20DE", "protocol": "vless"}]


def test_routers_and_main_stay_small():
    from pathlib import Path
    routers = Path("backend/app/routers.py").read_text()
    for name in ("sub_proxy", "client_versions", "panel_api_stats", "webhook_tee", "first_connect", "vpn_sessions", "panel_usage", "wg_pool"):
        assert f'"{name}"' in routers
    assert len(Path("backend/app/main.py").read_text().splitlines()) < 1000
    assert json.loads(json.dumps({"ok": True}))
