"""v28.92.0 (stage 20, N7): «Установка» — the catalogue of operations on the servers.

Every card leads to something that works: an admin tab that exists, the installer, or a module of the installer.
For a server the catalogue knows the steps done and which installation a module would go to."""
import re
from pathlib import Path

import pytest

from app import install_catalogue, rw_plan
from test_rw_installer import ADMIN, add_server, fleet, plan_and_approve, run_all  # noqa: F401
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def admin_tabs() -> set[str]:
    source = (ROOT / "admin/src/main.tsx").read_text()
    return set(re.findall(r'"([A-Za-z0-9]+)"', re.search(r"type Tab=([^;]+);", source).group(1)))


def test_every_card_leads_to_a_working_place():
    ops = install_catalogue.catalogue()
    assert len(ops) >= 30 and len({o["id"] for o in ops}) == len(ops)
    tabs = admin_tabs()
    for op in ops:
        kind = op["action"]["kind"]
        assert op["group"] in install_catalogue.GROUPS and op["title"] and op["text"]
        if kind == "tab":
            assert op["action"]["tab"] in tabs, op["id"]
        elif kind == "module":
            assert op["action"]["module"] in rw_plan.MODULES and op["action"]["needs"] in ("node", "any"), op["id"]
        elif kind == "action":
            assert op["action"]["name"] in rw_plan.ACTIONS, op["id"]
        else:
            assert kind == "install"
    assert {o["id"] for o in ops if o["simple"]} >= {"install_panel", "add_node", "hardening", "node_port"}, "the basics in «Простой»"
    assert sum(1 for o in ops if o["ssh"]) and sum(1 for o in ops if not o["ssh"])


@pytest.mark.asyncio
async def test_server_state_and_ready_modules(database, fleet):
    db = database
    server = await add_server(db, fleet, "n1", "198.51.100.40")
    from app import rw_api
    await rw_api.check_server(server["id"], db, ADMIN)
    before = await install_catalogue.get_catalogue(server["id"], db, ADMIN)
    assert before["state"]["installation_id"] is None and before["state"]["steps"]["prepared"]
    assert not next(o for o in before["operations"] if o["id"] == "node_guard")["ready"]
    assert next(o for o in before["operations"] if o["id"] == "bot")["ready"], "tabs are always open"
    approved = await plan_and_approve(db, rw_plan.PlanIn(mode="panel_node", panel_server_id=server["id"], panel_domain="panel.example.com",
                                                         tls="internal"))
    await run_all(db)
    after = await install_catalogue.get_catalogue(server["id"], db, ADMIN)
    assert after["state"]["installation_id"] == approved["id"] and "node" in after["state"]["roles"]
    assert after["state"]["steps"]["panel"] and after["state"]["steps"]["domain"] and "panel" in after["state"]["roles"]
    assert next(o for o in after["operations"] if o["id"] == "node_guard")["ready"]
    with pytest.raises(Exception):
        await install_catalogue.get_catalogue(999, db, ADMIN)


@pytest.mark.asyncio
async def test_snapshot_and_danger_zone(database, fleet, monkeypatch, tmp_path):
    from fastapi import HTTPException

    from app import rw_api
    db = database
    monkeypatch.setenv("RW_PANEL_COPIES_DIR", str(tmp_path / "copies"))
    server = await add_server(db, fleet, "p1", "198.51.100.41")
    await rw_api.check_server(server["id"], db, ADMIN)
    installed = await plan_and_approve(db, rw_plan.PlanIn(mode="panel_node", panel_server_id=server["id"], panel_domain="panel.example.com",
                                                          tls="internal"))
    await run_all(db)

    async def act(**kw):
        planned = await rw_api.action(installed["id"], rw_api.ActionIn(**kw), db, ADMIN)
        await rw_api.approve(planned["id"], rw_api.ApproveIn(plan_sha256=planned["plan_sha256"]), db, ADMIN)
        await run_all(db)
        return planned, await rw_api.get_installation(planned["id"], db, ADMIN)

    planned, done = await act(action="snapshot")
    assert [s["kind"] for s in planned["plan"]["steps"]] == ["backup_panel", "fetch_panel_backup", "fetch_configs"]
    assert done["status"] == "succeeded", done["error"]
    listed = (await install_catalogue.snapshots(ADMIN))["snapshots"]
    assert {s["kind"] for s in listed} == {"files", "database"}
    files = next(s for s in listed if s["kind"] == "files")
    got = await install_catalogue.download_snapshot(files["name"], db, ADMIN)
    import io
    import tarfile
    assert tarfile.open(fileobj=io.BytesIO(got.body), mode="r:gz").getnames() == ["opt/remnawave/docker-compose.yml"]
    assert (tmp_path / "copies" / files["name"]).read_bytes()[:20] != got.body[:20], "stored encrypted"
    with pytest.raises(HTTPException):
        await install_catalogue.download_snapshot("../etc/passwd", db, ADMIN)

    with pytest.raises(HTTPException):
        await rw_api.action(installed["id"], rw_api.ActionIn(action="remove_component"), db, ADMIN)
    with pytest.raises(HTTPException):
        await rw_api.action(installed["id"], rw_api.ActionIn(action="update", component="node"), db, ADMIN)
    with pytest.raises(HTTPException):
        await rw_api.action(installed["id"], rw_api.ActionIn(action="remove_component", component="selfsteal"), db, ADMIN)
    host = fleet["198.51.100.41"]
    assert "/opt/remnanode" in host.up
    planned, done = await act(action="remove_component", component="node")
    assert [s["kind"] for s in planned["plan"]["steps"]] == ["compose_down"] and done["status"] == "succeeded"
    assert "/opt/remnanode" not in host.up and "/opt/remnawave" in host.up, "only the node is taken off"
    # Emergency restore: the files of the snapshot back on the server, then every component restarts.
    with pytest.raises(HTTPException):
        await rw_api.action(installed["id"], rw_api.ActionIn(action="restore_files"), db, ADMIN)
    with pytest.raises(HTTPException):
        await rw_api.action(installed["id"], rw_api.ActionIn(action="update", snapshot=files["name"]), db, ADMIN)
    planned, done = await act(action="restore_files", snapshot=files["name"])
    kinds = [s["kind"] for s in planned["plan"]["steps"]]
    assert kinds[0] == "put_configs" and "compose_up" in kinds and done["status"] == "succeeded", done["error"]
    assert host.restored[-1][:2] == ("put", True), "the archive arrives whole (SHA-256)"
    planned, _ = await act(action="remove_component", component="panel")
    assert [s["kind"] for s in planned["plan"]["steps"]] == ["backup_panel", "fetch_panel_backup", "compose_down"]


@pytest.mark.asyncio
async def test_daily_snapshots_queue_and_go_to_telegram(database, fleet, monkeypatch, tmp_path):
    from datetime import datetime, timezone

    from app import rw_api, rw_snapshots, telegram_backup
    from app.config import settings
    db = database
    monkeypatch.setenv("RW_PANEL_COPIES_DIR", str(tmp_path / "copies"))
    server = await add_server(db, fleet, "p2", "198.51.100.42")
    await rw_api.check_server(server["id"], db, ADMIN)
    await plan_and_approve(db, rw_plan.PlanIn(mode="panel_node", panel_server_id=server["id"], panel_domain="panel.example.com", tls="internal"))
    await run_all(db)
    await rw_snapshots.put_schedule(rw_snapshots.ScheduleIn(enabled=True, time="04:00", telegram=True), db, ADMIN)
    morning = datetime(2026, 11, 8, 1, 10, tzinfo=timezone.utc)  # 04:10 MSK
    first = await rw_snapshots.tick(db, morning)
    assert len(first["queued"]) == 1
    assert (await rw_snapshots.tick(db, morning))["queued"] == [], "once a day"
    await run_all(db)
    sent = []

    class Client:
        async def post(self, url, data=None, files=None):
            sent.append((url.rsplit("/", 1)[1], data["chat_id"], files["document"][0]))
            return type("R", (), {"status_code": 200})()

    async def encrypt(source, target, password):
        target.write_bytes(b"ENC" + source.read_bytes())

    monkeypatch.setattr(telegram_backup, "encrypt", encrypt)
    monkeypatch.setattr(settings, "bot_token", "123:abc")
    without = await rw_snapshots.tick(db, morning, client=Client())
    assert without["sent"] == 0 and "пароль" in without["errors"][0], "nothing goes out without the backup password"
    rw_snapshots_state = await rw_snapshots._load(db, rw_snapshots.STATE_KEY, {})
    assert rw_snapshots_state["watch"] == []

    # The next morning with the backup password and the chat: the files go out encrypted.
    from app.main import set_setting
    from app.security import encrypt_secret
    await set_setting(db, "backup_password", encrypt_secret("backup-password-1"))
    await telegram_backup.save(db, {**telegram_backup.DEFAULT, "chat_id": "-1001234567"})
    await db.commit()
    next_day = datetime(2026, 11, 9, 1, 5, tzinfo=timezone.utc)
    assert len((await rw_snapshots.tick(db, next_day))["queued"]) == 1
    await run_all(db)
    done = await rw_snapshots.tick(db, next_day, client=Client())
    assert done["sent"] == 2 and not done["errors"], done
    assert {name.split("-")[0] for _, _, name in sent} == {"config", "panel"} and all(chat == "-1001234567" for _, chat, _ in sent)
    assert all(name.endswith(".enc") for _, _, name in sent)


def test_put_configs_script_restores_and_goes_back(tmp_path):
    """rw_steps.PUT_CONFIGS itself (bash) in a scratch root: the files come back, the old ones are kept, «undo» returns
    them, and an archive with a path outside the wizard's directories changes nothing."""
    import hashlib
    import io
    import subprocess
    import tarfile

    from app import rw_steps
    root = tmp_path / "root"
    (root / "opt/remnawave").mkdir(parents=True)
    (root / "opt/remnawave/docker-compose.yml").write_text("old")
    script = rw_steps.PUT_CONFIGS.replace("before=/root/", f"before={tmp_path}/").replace("cd /\n", f"cd {root}\n") \
        .replace("-C /", f"-C {root}")

    def archive(entries: dict) -> bytes:
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as tar:
            for name, body in entries.items():
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
        return out.getvalue()

    def run(*args, data=b""):
        return subprocess.run(["bash", "-c", script, "p", *args], input=data, capture_output=True)

    good = archive({"opt/remnawave/docker-compose.yml": b"new"})
    assert run("put", hashlib.sha256(good).hexdigest(), "k1", data=good).returncode == 0
    assert (root / "opt/remnawave/docker-compose.yml").read_text() == "new"
    assert (tmp_path / "corgi-before-restore-k1.tar.gz").is_file()
    assert run("undo", "", "k1").returncode == 0
    assert (root / "opt/remnawave/docker-compose.yml").read_text() == "old", "«undo» brings the files before the restore back"
    bad = archive({"etc/cron.d/x": b"evil", "opt/remnawave/docker-compose.yml": b"new"})
    assert run("put", hashlib.sha256(bad).hexdigest(), "k2", data=bad).returncode == 4
    assert (root / "opt/remnawave/docker-compose.yml").read_text() == "old" and not (root / "etc").exists()
    assert run("put", "0" * 64, "k3", data=good).returncode == 3
    assert run("put", "abc", "k;rm", data=good).returncode == 2


@pytest.mark.asyncio
async def test_anti_censorship_checklist(database, fleet, monkeypatch):
    from app import rw_api, rw_selfsteal
    db = database
    server = await add_server(db, fleet, "n9", "198.51.100.49")
    await rw_api.check_server(server["id"], db, ADMIN)
    installed = await plan_and_approve(db, rw_plan.PlanIn(mode="panel_node", panel_server_id=server["id"], panel_domain="panel.example.com",
                                                          tls="internal", firewall=True))
    await run_all(db)
    report = (await install_catalogue.anti_censorship(db, ADMIN))["nodes"]
    assert len(report) == 1 and report[0]["total"] == len(install_catalogue.CHECKLIST)
    items = {i["key"]: i for i in report[0]["items"]}
    assert not items["selfsteal"]["ok"] and items["selfsteal"]["fix"] == "selfsteal"
    assert items["node_port"]["ok"], "the wizard closed the node's port"
    assert not items["guard"]["ok"] and not items["snapshots"]["ok"]
    # The node guard switched on through the module → the point turns green.
    planned = await rw_api.action(installed["id"], rw_api.ActionIn(action="module", module=rw_api.ModuleIn(name="node_guard", server_ids=[server["id"]])), db, ADMIN)
    await rw_api.approve(planned["id"], rw_api.ApproveIn(plan_sha256=planned["plan_sha256"]), db, ADMIN)
    await run_all(db)
    items = {i["key"]: i for i in (await install_catalogue.anti_censorship(db, ADMIN))["nodes"][0]["items"]}
    assert items["guard"]["ok"], items["guard"]
    assert {i["fix"] for i in items.values()} <= {o["id"] for o in install_catalogue.catalogue()}, "every fix is a card"


@pytest.mark.asyncio
async def test_mtproto_links_follow_the_latest_run(database, fleet):
    """v28.94.0 (N7): the MTProto proxy on a node — its link for clients, gone after «off»."""
    db = database
    server = await add_server(db, fleet, "n1", "198.51.100.40")
    from app import rw_api
    await rw_api.check_server(server["id"], db, ADMIN)
    install = await plan_and_approve(db, rw_plan.PlanIn(mode="panel_node", panel_server_id=server["id"], panel_domain="panel.example.com",
                                                        tls="internal"))
    await run_all(db)

    async def module(enabled):
        planned = await rw_api.action(install["id"], rw_api.ActionIn(action="module", module=rw_api.ModuleIn(
            name="mtproto", enabled=enabled, server_ids=[server["id"]], mtproto_port=9443, mtproto_domain="www.cloudflare.com")), db, ADMIN)
        await rw_api.approve(planned["id"], rw_api.ApproveIn(plan_sha256=planned["plan_sha256"]), db, ADMIN)
        await run_all(db)
    await module(True)
    out = await install_catalogue.mtproto_links(db, ADMIN)
    assert out["proxies"] == [{"server_id": server["id"], "name": "n1", "port": 9443, "domain": "www.cloudflare.com",
                               "tg": f"tg://proxy?server=198.51.100.40&port=9443&secret=ee{'ab' * 16}",
                               "https": f"https://t.me/proxy?server=198.51.100.40&port=9443&secret=ee{'ab' * 16}"}]
    await module(False)
    assert (await install_catalogue.mtproto_links(db, ADMIN))["proxies"] == []


@pytest.mark.asyncio
async def test_geo_lists_go_into_the_node_compose_and_out_again(database, fleet, monkeypatch):
    """v28.95.0 (N7): «Российские списки» — the module fixes the release in the plan, the node's compose mounts the files."""
    from app import rw_api, rw_releases
    db = database
    files = {"geoip": {"url": "https://github.com/runetfreedom/russia-v2ray-rules-dat/releases/download/202611071200/geoip.dat", "sha256": "a" * 64},
             "geosite": {"url": "https://github.com/runetfreedom/russia-v2ray-rules-dat/releases/download/202611071200/geosite.dat", "sha256": "b" * 64}}

    async def lists():
        return "202611071200", files
    monkeypatch.setattr(rw_releases, "geo_lists", lists)
    server = await add_server(db, fleet, "n1", "198.51.100.40")
    await rw_api.check_server(server["id"], db, ADMIN)
    install = await plan_and_approve(db, rw_plan.PlanIn(mode="panel_node", panel_server_id=server["id"], panel_domain="panel.example.com",
                                                        tls="internal"))
    await run_all(db)
    host = fleet["198.51.100.40"]

    async def module(enabled):
        planned = await rw_api.action(install["id"], rw_api.ActionIn(action="module", module=rw_api.ModuleIn(name="geo_files", enabled=enabled)), db, ADMIN)
        await rw_api.approve(planned["id"], rw_api.ApproveIn(plan_sha256=planned["plan_sha256"]), db, ADMIN)
        await run_all(db)
        return planned
    planned = await module(True)
    assert planned["params"]["geo_files"] == "202611071200"
    compose = next(v for k, v in host.files.items() if len(k) == 2 and k[0] == "/opt/remnanode" and k[1] == "docker-compose.yml")
    assert "./geo/ru-geosite.dat:/usr/local/share/xray/ru-geosite.dat:ro" in compose
    assert ("geo", ("install", files["geoip"]["url"], "a" * 64, files["geosite"]["url"], "b" * 64)) in host.calls
    await module(False)
    compose = next(v for k, v in host.files.items() if len(k) == 2 and k[0] == "/opt/remnanode" and k[1] == "docker-compose.yml")
    assert "./geo/" not in compose
