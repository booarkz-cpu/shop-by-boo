"""v28.58.0 (BUG-A6): services without an HTTP port have a container healthcheck.

Before, worker, bot, mail_receiver and support_worker had none: Docker showed a hung worker as running.
Now each touches a liveness file and compose checks its age."""
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from app import heartbeat

ROOT = Path(__file__).resolve().parents[1]


def test_fresh_beat_passes_and_a_stale_or_missing_one_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARTBEAT_DIR", str(tmp_path))
    assert not heartbeat.fresh("worker", 120)
    heartbeat.beat("worker")
    assert heartbeat.fresh("worker", 120)
    old = time.time() - 600
    os.utime(tmp_path / "worker.alive", (old, old))
    assert not heartbeat.fresh("worker", 120)


def test_command_line_exit_code_is_what_docker_reads(tmp_path):
    env = {**os.environ, "HEARTBEAT_DIR": str(tmp_path), "PYTHONPATH": str(ROOT / "backend")}
    run = lambda: subprocess.run([sys.executable, "-m", "app.heartbeat", "bot", "120"], env=env, cwd=tmp_path).returncode  # noqa: E731
    assert run() == 1
    (tmp_path / "bot.alive").write_text("1")
    assert run() == 0


@pytest.mark.asyncio
async def test_worker_beats_only_after_redis_and_the_database_answer(tmp_path, monkeypatch):
    import worker

    monkeypatch.setenv("HEARTBEAT_DIR", str(tmp_path))

    class Stop(Exception):
        pass

    async def stop(_seconds):
        raise Stop

    class BrokenRedis:
        async def set(self, *a, **k):
            raise ConnectionError("redis is down")

    monkeypatch.setattr(worker.asyncio, "sleep", stop)
    monkeypatch.setattr(worker.main, "redis_client", BrokenRedis())
    with pytest.raises(Stop):
        await worker.worker_heartbeat()
    assert not (tmp_path / "worker.alive").exists(), "no beat while Redis fails"


def test_every_long_running_service_has_a_healthcheck():
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    one_shot = {"volume_init", "support_migrate"}
    missing = [name for name, svc in services.items()
               if name not in one_shot and "healthcheck" not in svc and "extends" not in svc]
    assert missing == []
    for name in ("worker", "bot", "mail_receiver"):
        assert services[name]["healthcheck"]["test"][:4] == ["CMD", "python", "-m", "app.heartbeat"]
        assert "/tmp" in services[name]["tmpfs"]


def test_keep_beating_touches_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARTBEAT_DIR", str(tmp_path))

    async def run():
        task = asyncio.create_task(heartbeat.keep_beating("mail_receiver", interval=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
    asyncio.run(run())
    assert heartbeat.fresh("mail_receiver", 5)
