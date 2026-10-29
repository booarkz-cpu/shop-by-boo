"""v28.53: speed tests from the apps (blob, report, quality map, slow-server alert) and the node load forecast."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import node_forecast as nf
from app import speed_test as st
from app.models import SpeedTest
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@example.com")


def req(client="android-user"):
    return Request({"type": "http", "method": "POST", "path": "/api/me/speedtest", "headers": [(b"x-shop-client", client.encode())],
                    "query_string": b"", "client": ("203.0.113.9", 1)})


def test_blob_size_and_names():
    assert sum(len(c) for c in st.blob(150_000)) == 150_000
    assert st.server_name("Нидерланды 1") == "Нидерланды 1"
    assert st.server_name("185.12.33.4") == "node" and st.server_name("vless://x") == "node" and st.server_name("") == "auto"


@pytest.mark.asyncio
async def test_reports_quality_map_and_daily_alert(database):  # noqa: F811
    db = database
    for i, speed in enumerate([4, 5, 6, 3, 8]):
        await st.speed_report(st.SpeedIn(server="DE-1", download_mbps=speed, ping_ms=80 + i), req(), db)
    await st.speed_report(st.SpeedIn(server="NL-1", download_mbps=95, ping_ms=30), req("ios-user"), db)
    await st.speed_report(st.SpeedIn(server="direct", vpn=False, download_mbps=300), req(), db)  # VPN off: not in the map
    q = await st.quality(db)
    assert [x["server"] for x in q] == ["DE-1", "NL-1"]
    de = q[0]
    assert de["slow"] and de["median_mbps"] == 5 and de["median_ping_ms"] == 82 and de["platforms"] == ["android-user"]
    assert not q[1]["slow"]  # one run is not enough to judge
    sent = []

    async def send(text):
        sent.append(text)
        return True
    now = datetime.utcnow()
    assert await st.alert_pass(db, now, send) == ["DE-1"]
    assert await st.alert_pass(db, now, send) == []  # once a day
    assert "DE-1: 5.0 Мбит/с" in sent[0]
    old = SpeedTest(user_id=1, server="old", vpn=True, download_mbps=1, created_at=now - timedelta(days=40))
    db.add(old)
    await db.commit()
    await st.alert_pass(db, now + timedelta(days=1), send)
    assert await db.get(SpeedTest, old.id) is None  # kept 30 days


@pytest.mark.asyncio
async def test_blob_needs_switch_and_limit(database, monkeypatch):  # noqa: F811
    db = database
    response = await st.speed_blob(req(), 100, db)
    assert response.headers["content-length"] == str(10 * 1024 * 1024)  # capped by max_mb
    await st.admin_speed_config(st.SpeedConfigIn(enabled=False), db, ADMIN)
    with pytest.raises(HTTPException):
        await st.speed_blob(req(), 1, db)

    async def deny(user_id, per_hour):
        return False
    await st.admin_speed_config(st.SpeedConfigIn(enabled=True), db, ADMIN)
    monkeypatch.setattr(st, "_allow", deny)
    with pytest.raises(HTTPException) as exc:
        await st.speed_blob(req(), 1, db)
    assert exc.value.status_code == 429


def test_trend_and_days_left():
    assert nf.trend([(0, 10), (1, 12), (2, 14)]) == pytest.approx(2)
    series = {(datetime(2026, 10, 1) + timedelta(days=i)).date().isoformat(): 100 + 5 * i for i in range(14)}
    f = nf.forecast_node(series, 300, nf.DEFAULT, datetime(2026, 10, 15))
    assert f["peak"] == 165 and f["per_day"] == pytest.approx(5) and f["days_left"] == 27 and not f["flagged"]
    f = nf.forecast_node(series, 200, nf.DEFAULT, datetime(2026, 10, 15))
    assert f["days_left"] == 7 and f["flagged"]
    flat = nf.forecast_node({"2026-10-01": 50, "2026-10-02": 50}, 300, nf.DEFAULT, datetime(2026, 10, 3))
    assert flat["days_left"] is None and not flat["flagged"]


@pytest.mark.asyncio
async def test_forecast_samples_peaks_and_alerts_once(database):  # noqa: F811
    db = database
    now = datetime(2026, 10, 29, 9, 0)
    await nf.put_forecast(nf.ForecastIn(default_capacity=100, capacities={"n2": 1000}), db, ADMIN)
    sent = []

    async def send(text):
        sent.append(text)
        return True
    nodes = [{"uuid": "n1", "name": "DE-1", "status": "online", "users_online": 90}, {"uuid": "n2", "name": "NL-1", "status": "online", "users_online": 40},
             {"uuid": "n3", "name": "off", "status": "disabled", "users_online": 0}]
    assert await nf.tick(db, nodes, now, send) == ["n1"]  # 90 % of 100 is already busy
    nodes[0]["users_online"] = 70
    assert await nf.tick(db, nodes, now + timedelta(minutes=30), send) == []  # once a day; the peak stays 90
    r = await nf.report(db, now)
    de = next(n for n in r["nodes"] if n["uuid"] == "n1")
    assert de["peak"] == 90 and de["capacity"] == 100 and len(sent) == 1 and "DE-1: пик 90 из 100" in sent[0]
    assert {n["uuid"] for n in r["nodes"]} == {"n1", "n2"}
