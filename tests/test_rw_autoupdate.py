"""v28.74.0 (stage 15): automatic updates of Remnawave from the admin panel, against the fake servers of
test_rw_installer.

* a successful installation is «out of date» when the shop pins newer images than it runs;
* the nightly pass queues the same «update» plan an administrator would approve, once a night, then reports
  how it ended; «Обновить сейчас» does it for the chosen installations;
* a failed update puts back the previous files and the panel's database from the copy made at its start;
* new releases on GitHub are announced once and never installed before a shop release verifies them;
* the connected panel's version is compared with the version the shop's CI verified;
* Automation Center lists every automatic process with its state."""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app import automation_center, rw_autoupdate, rw_plan
from test_rw_installer import ADMIN, add_server, fleet, plan_and_approve, run_all  # noqa: F401
from test_subscription_commerce import database  # noqa: F401

NIGHT = datetime(2026, 11, 5, 1, 40, tzinfo=timezone.utc)  # 04:40 MSK


async def installed(db, hosts):
    server = await add_server(db, hosts, "panel-1", "198.51.100.10")
    from app import rw_api
    await rw_api.check_server(server["id"], db, ADMIN)
    approved = await plan_and_approve(db, rw_plan.PlanIn(mode="panel_node", panel_server_id=server["id"],
                                                         panel_domain="panel.example.com", tls="internal"))
    await run_all(db)
    return approved["id"], hosts["198.51.100.10"]


@pytest.fixture
def notes(monkeypatch):
    sent = []

    async def notify(text):
        sent.append(text)

    async def upstream():
        return {c: {"latest": v, "error": None} for c, v in rw_plan.VERSIONS.items()}
    monkeypatch.setattr(rw_autoupdate, "_notify", notify)
    monkeypatch.setattr(rw_autoupdate, "fetch_upstream", upstream)
    return sent


def test_versions_and_schedule_window():
    assert rw_autoupdate.newer("v3.5.0", "3.4.8") and not rw_autoupdate.newer("3.4.8", "3.4.8")
    assert not rw_autoupdate.newer("3.4.8-beta", "3.4.8") and not rw_autoupdate.newer(None, "3.4.8")
    cfg = {**rw_autoupdate.DEFAULT, "enabled": True, "time": "04:30"}
    assert rw_autoupdate.due(cfg, {}, NIGHT)
    assert not rw_autoupdate.due(cfg, {"last_run_date": "2026-11-05"}, NIGHT)  # once a night
    assert not rw_autoupdate.due(cfg, {}, datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc))  # 07:00 MSK: window is over
    assert not rw_autoupdate.due({**cfg, "enabled": False}, {}, NIGHT)
    with pytest.raises(ValueError):
        rw_autoupdate.SettingsIn(enabled=True, time="25:00")


@pytest.mark.asyncio
async def test_nightly_update_runs_once_and_reports(database, fleet, notes, monkeypatch):
    db = database
    iid, host = await installed(db, fleet)
    [item] = await rw_autoupdate.installations(db)
    assert item["id"] == iid and item["outdated"] == [] and {"panel", "node", "caddy"} <= set(item["components"])
    await rw_autoupdate.put_auto_update(rw_autoupdate.SettingsIn(enabled=True, time="04:30"), db, ADMIN)
    assert (await rw_autoupdate.tick(db, NIGHT))["queued"] == []  # nothing to update yet

    newer = {**rw_plan.IMAGES, "panel": "remnawave/backend:3@sha256:" + "b" * 64}
    monkeypatch.setattr(rw_plan, "IMAGES", newer)
    [item] = await rw_autoupdate.installations(db)
    assert item["outdated"] == ["panel"]
    state = await rw_autoupdate._load(db, rw_autoupdate.STATE_KEY, {})
    state["last_run_date"] = None
    await rw_autoupdate._save(db, rw_autoupdate.STATE_KEY, state)
    report = await rw_autoupdate.tick(db, NIGHT)
    assert len(report["queued"]) == 1 and any("запущено" in n for n in notes)
    assert (await rw_autoupdate.tick(db, NIGHT))["queued"] == []  # the same night is not queued twice
    await run_all(db)
    report = await rw_autoupdate.tick(db, NIGHT)
    assert len(report["finished"]) == 1
    assert any("обновлена" in n and "не обновлена" not in n for n in notes)
    [item] = await rw_autoupdate.installations(db)
    assert item["outdated"] == [] and item["last_update"]["automatic"] and item["last_update"]["status"] == "succeeded"
    assert newer["panel"] in host.files[("/opt/remnawave", "docker-compose.yml")]
    history = await rw_autoupdate.history(db)
    assert history[0]["created_by"] == rw_autoupdate.ACTOR and not history[0]["rolled_back"]
    [copy] = (await rw_autoupdate.overview(db, with_panel=False))["panel_copies"]
    got = await rw_autoupdate.download_panel_copy(copy["name"], db, ADMIN)
    assert got.body.startswith(b"PGDMP") and copy["name"].removesuffix(".enc") in got.headers["content-disposition"]
    with pytest.raises(HTTPException):
        await rw_autoupdate.download_panel_copy("../../etc/passwd", db, ADMIN)


@pytest.mark.asyncio
async def test_failed_update_restores_files_and_database(database, fleet, notes, monkeypatch):
    db = database
    iid, host = await installed(db, fleet)
    before = host.files[("/opt/remnawave", "docker-compose.yml")]
    monkeypatch.setattr(rw_plan, "IMAGES", {**rw_plan.IMAGES, "panel": "remnawave/backend:3@sha256:" + "c" * 64})
    host.fail.add("wait")  # the new panel never answers /health
    out = await rw_autoupdate.run_now(rw_autoupdate.RunIn(installation_ids=[iid]), db, ADMIN)
    with pytest.raises(HTTPException) as err:  # one run per server at a time
        await rw_autoupdate.run_now(rw_autoupdate.RunIn(installation_ids=[iid]), db, ADMIN)
    assert err.value.status_code == 409
    await run_all(db)
    from app.models import RemnawaveInstallation
    row = await db.get(RemnawaveInstallation, out["queued"][0])
    assert row.status == "failed" and "/health" in row.error
    assert host.files[("/opt/remnawave", "docker-compose.yml")] == before
    restores = [args for name, args in host.calls if name == "restore"]
    assert restores and restores[-1][0].startswith("/opt/remnawave/backups/panel-")  # the copy of this very update
    await rw_autoupdate.tick(db, NIGHT)
    assert any("не обновлена" in n for n in notes)
    assert (await rw_autoupdate.history(db))[0]["rolled_back"]
    with pytest.raises(HTTPException):
        await rw_autoupdate.put_auto_update(rw_autoupdate.SettingsIn(enabled=True, time="04:30", installation_ids=[999]), db, ADMIN)


@pytest.mark.asyncio
async def test_new_upstream_release_is_announced_once(database, notes, monkeypatch):
    db = database

    async def upstream():
        return {"panel": {"latest": "v9.0.0", "error": None}, "node": {"latest": rw_plan.VERSIONS["node"], "error": None},
                "subscription_page": {"latest": None, "error": "GitHub недоступен"}}
    monkeypatch.setattr(rw_autoupdate, "fetch_upstream", upstream)
    report = await rw_autoupdate.tick(db, NIGHT)
    assert report["announced"] == ["panel"] and "v9.0.0" in notes[-1]
    view = rw_autoupdate.upstream_view(await rw_autoupdate._load(db, rw_autoupdate.STATE_KEY, {}))
    assert view["components"]["panel"]["newer"] and not view["components"]["node"]["newer"]
    state = await rw_autoupdate._load(db, rw_autoupdate.STATE_KEY, {})
    state["checked_at"] = None
    await rw_autoupdate._save(db, rw_autoupdate.STATE_KEY, state)
    assert (await rw_autoupdate.tick(db, NIGHT))["announced"] == []  # the same release is announced once


@pytest.mark.asyncio
async def test_connected_panel_version(monkeypatch):
    import app.remnawave as remnawave

    def client(version):
        class Client:
            async def _request(self, method, path, **kw):
                assert path == "/api/system/metadata"
                return {"version": version}
        return Client
    for version, status in ((rw_plan.VERSIONS["panel"], "verified"), ("9.0.0", "newer"), ("1.0.0", "older"), ("dev", "unknown")):
        monkeypatch.setattr(remnawave, "RemnawaveClient", client(version))
        assert (await rw_autoupdate.panel_version())["status"] == status

    class Missing:
        async def _request(self, *a, **kw):
            raise remnawave.RemnawaveNotConfigured("no")
    monkeypatch.setattr(remnawave, "RemnawaveClient", Missing)
    assert (await rw_autoupdate.panel_version())["status"] == "not_connected"


@pytest.mark.asyncio
async def test_automation_center_lists_processes(database, notes, monkeypatch, tmp_path):
    db = database
    monkeypatch.setenv("AUTO_UPDATE_CONTROL_DIR", str(tmp_path / "missing"))

    async def version():
        return {"status": "not_connected", "version": None, "verified": rw_plan.VERSIONS["panel"]}
    monkeypatch.setattr(rw_autoupdate, "panel_version", version)
    items = {i["key"]: i for i in await automation_center.processes(db)}
    assert set(items) == {"shop_update", "rw_update", "rw_releases", "rw_panel", "backups", "workers", "alerts"}
    assert items["shop_update"]["status"] == "off" and "auto-update.sh install" in items["shop_update"]["detail"]
    assert items["rw_update"]["status"] == "off" and items["workers"]["status"] == "error"
    assert all(i["tab"] and i["status"] in ("ok", "warn", "error", "off") for i in items.values())
