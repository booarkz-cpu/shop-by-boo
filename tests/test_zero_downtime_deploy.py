"""Zero-downtime backend update: the old backend is replaced only after the new release answers 200.

scripts/zero-downtime-backend.sh is run against a fake `docker` that records every call and answers the
health checks as scripted; Caddy and Compose are checked for the failover the script relies on."""
import os
import re
import stat
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/zero-downtime-backend.sh"

FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "$*" >> "$LOG"
args="$*"
case "$args" in
  *"ps --status running --services"*) [ "${RUNNING:-1}" = 1 ] && echo backend; exit 0 ;;
  *"exec -T backend_standby"*) [ "${STANDBY_OK:-1}" = 1 ] && exit 0 || exit 1 ;;
  *"exec -T backend "*) [ "${BACKEND_OK:-1}" = 1 ] && exit 0 || exit 1 ;;
esac
exit 0
"""


def run(tmp_path, **env):
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    docker = fake / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "docker.log"
    log.write_text("")
    environment = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "LOG": str(log), "ZERO_DOWNTIME_TIMEOUT": "3",
                   **{k: str(v) for k, v in env.items()}}
    # sleep is shortened so a failing health check ends quickly.
    (fake / "sleep").write_text("#!/bin/sh\nexit 0\n")
    (fake / "sleep").chmod(0o755)
    done = subprocess.run(["bash", str(SCRIPT)], env=environment, capture_output=True, text=True)
    return done, log.read_text().splitlines()


def index(calls, needle):
    return next(i for i, call in enumerate(calls) if needle in call)


def test_the_old_backend_is_recreated_only_after_the_standby_answers(tmp_path):
    done, calls = run(tmp_path)
    assert done.returncode == 0, done.stderr
    started = index(calls, "up -d --no-deps --force-recreate backend_standby")
    checked = index(calls, "exec -T backend_standby")
    replaced = index(calls, "up -d --no-deps backend")
    removed = index(calls, "rm -fsv backend_standby")
    assert started < checked < replaced < removed


def test_a_broken_release_never_touches_the_running_backend(tmp_path):
    done, calls = run(tmp_path, STANDBY_OK=0)
    assert done.returncode == 1 and "was not touched" in done.stderr
    assert not any(re.search(r"up -d --no-deps backend$", c) for c in calls)
    assert any("rm -fsv backend_standby" in c for c in calls)


def test_if_the_new_backend_fails_the_standby_keeps_serving(tmp_path):
    done, calls = run(tmp_path, BACKEND_OK=0)
    assert done.returncode == 1 and "standby keeps serving" in done.stderr
    assert not any("rm -fsv backend_standby" in c for c in calls)


def test_a_first_install_starts_normally(tmp_path):
    done, calls = run(tmp_path, RUNNING=0)
    assert done.returncode == 0 and not any("backend_standby" in c for c in calls)


def test_caddy_prefers_the_backend_and_falls_back_to_the_standby():
    caddy = (ROOT / "deploy/Caddyfile").read_text()
    blocks = re.findall(r"reverse_proxy \{\$BACKEND_UPSTREAM:backend:8000\} \{\n(.*?)\n\s*\}", caddy, re.S)
    assert blocks and len(blocks) == caddy.count("reverse_proxy {$BACKEND_UPSTREAM")
    assert all("import backend_lb" in b for b in blocks)
    snippet = caddy.split("(backend_lb) {", 1)[1].split("}", 1)[0]
    assert "lb_policy first" in snippet and "health_uri /health/live" in snippet and "lb_try_duration" in snippet


def test_compose_defines_the_standby_on_its_own_ingress_address():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    standby = compose["services"]["backend_standby"]
    assert standby["extends"] == {"service": "backend"} and standby["profiles"] == ["standby"]
    assert "BACKEND_STANDBY_INGRESS_IP" in standby["networks"]["ingress"]["ipv4_address"]
    upstream = compose["services"]["caddy"]["environment"]["BACKEND_UPSTREAM"]
    assert "BACKEND_INGRESS_IP" in upstream.split()[0] and "BACKEND_STANDBY_INGRESS_IP" in upstream.split()[1]
    build = (ROOT / "deploy/build-production.sh").read_text()
    assert build.index("zero-downtime-backend.sh") < build.index("docker compose up -d --remove-orphans")
    assert "--profile standby down" in (ROOT / "scripts/update.sh").read_text()
