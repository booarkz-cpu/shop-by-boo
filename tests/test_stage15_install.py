"""v28.74.0 (stage 15): what the Docker, installer and update audit checks stay true.

* every long-running service of docker-compose.yml has a health check and a restart policy; one-shot and
  standby services are the only exceptions; only Caddy (80/443) and the mail receiver (25) publish ports;
* data lives in named volumes; the worker sees the backup volume (copies of the Remnawave panel's database);
* update and rollback keep .env and the auto-update agent's .control, snapshot the files and dump the database
  before they change anything;
* the installer turns the auto-update agent on itself, so nothing about it needs a terminal afterwards."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
ONE_SHOT = {"volume_init", "support_migrate"}


def test_services_have_health_checks_restart_and_few_published_ports():
    for name, svc in COMPOSE["services"].items():
        if name in ONE_SHOT:
            assert svc.get("restart") == "no", name
            continue
        if "standby" in (svc.get("profiles") or []):
            continue
        assert "healthcheck" in svc and svc.get("restart") == "unless-stopped", name
        if svc.get("ports"):
            assert name in {"caddy", "mail_receiver"}, name


def test_data_in_named_volumes_and_worker_sees_backups():
    named = set(COMPOSE["volumes"])
    for db in ("db", "redis", "support_db"):
        mounts = [m.split(":")[0] for m in COMPOSE["services"][db].get("volumes", []) if isinstance(m, str)]
        assert any(m in named for m in mounts), db
    assert "backup_data:/data/backups" in COMPOSE["services"]["worker"]["volumes"]
    assert "./.control:/data/control" in COMPOSE["services"]["backend"]["volumes"]


def test_update_and_rollback_keep_secrets_and_agent_state():
    update = (ROOT / "scripts/update.sh").read_text()
    rollback = (ROOT / "scripts/rollback.sh").read_text()
    assert "pg_dump" in update and "trap rollback ERR" in update and "RECOVERY_MODE" in update
    for script in (update, rollback):
        assert "--exclude='./.control'" in script and "--exclude='./.env'" in script
        assert "! -name '.control'" in script and "! -name '.env'" in script


def test_installer_enables_the_auto_update_agent():
    installer = (ROOT / "deploy/install-vps.sh").read_text()
    assert 'scripts/auto-update.sh" install' in installer
