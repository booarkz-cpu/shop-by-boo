"""Exercise the published Redis volume procedure on two isolated Docker Compose projects."""

import json
import os
import re
import secrets
import subprocess
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("redis", "support_redis")
BEFORE = "redis:8.10-alpine@sha256:71885d8cc6e42f2bc0aa2eb853bfc4be200b5108a46ac50e117ae1df0531fb80"
CANDIDATE = "redis:8.12.0-alpine@sha256:5af80107c1eeecb484a2269b80a26d12bfa6521787da4663bd9f19f60a163483"


def run(*args, cwd=None, env=None, check=True):
    return subprocess.run(args, cwd=cwd, env=env, check=check, text=True, stdout=subprocess.PIPE)


def compose(directory, project, *args, check=True):
    return run("docker", "compose", "-p", project, *args, cwd=directory, check=check)


def configure(directory, image, passwords, external=None):
    volumes = {}
    services = {}
    for service in SERVICES:
        name = service + "_data"
        volumes[name] = {"external": True, "name": external[service]} if external else {}
        services[service] = {
            "image": image,
            "environment": {"REDISCLI_AUTH": passwords[service]},
            "command": ["sh", "-ec", 'exec redis-server --appendonly yes --requirepass "$$REDISCLI_AUTH"'],
            "healthcheck": {
                "test": ["CMD-SHELL", "redis-cli ping | grep -qx PONG"],
                "interval": "1s",
                "timeout": "2s",
                "retries": 30,
            },
            "volumes": [f"{name}:/data"],
        }
    directory.mkdir(exist_ok=True)
    (directory / "compose.yaml").write_text(json.dumps({"services": services, "volumes": volumes}))


def redis(directory, project, service, *args):
    return compose(directory, project, "exec", "-T", service, "redis-cli", "--raw", *args).stdout.strip()


def verify(directory, project, version, expect_new=False):
    for service in SERVICES:
        assert f"redis_version:{version}" in redis(directory, project, service, "INFO", "server").splitlines()
        assert redis(directory, project, service, "HGET", "ticket", "source") == service
        assert redis(directory, project, service, "LRANGE", "queue", "0", "-1").splitlines() == ["first", "second"]
        assert 0 < int(redis(directory, project, service, "TTL", "lease")) <= 3600
        assert redis(directory, project, service, "GET", "after-upgrade") == ("yes" if expect_new else "")
        unauth = compose(directory, project, "exec", "-T", "-e", "REDISCLI_AUTH=", service, "redis-cli", "ping", check=False)
        assert "NOAUTH" in unauth.stdout


def drill(root):
    guide = (ROOT / "docs/modules/redis_and_postgres.md").read_text()
    backup, restore = re.findall(r"^```bash\n(.*?)\n```", guide, re.M | re.S)
    marker = "corgi-redis-drill-" + uuid.uuid4().hex
    old = root / "source"
    project = marker + "-source"
    passwords = {service: secrets.token_hex(24) for service in SERVICES}
    backup_root = root / "backups"
    backup_root.mkdir()
    env = dict(os.environ, COMPOSE_PROJECT_NAME=project, REDIS_BACKUP_DIR=str(backup_root), REDIS_RESTORE_ID=marker)
    configure(old, BEFORE, passwords)
    targets = []
    try:
        compose(old, project, "up", "-d", "--wait")
        for service in SERVICES:
            redis(old, project, service, "HSET", "ticket", "source", service)
            redis(old, project, service, "RPUSH", "queue", "first", "second")
            redis(old, project, service, "SET", "lease", "holder", "EX", "3600")
            assert redis(old, project, service, "SAVE") == "OK"
        verify(old, project, "8.10.3")
        assert run("bash", "-c", backup, cwd=old, env=env, check=False).returncode != 0
        compose(old, project, "stop")
        run("bash", "-c", backup, cwd=old, env=env)
        (checksum,) = backup_root.glob("*/SHA256SUMS")
        original = checksum.read_bytes()
        checksum.write_bytes(original.splitlines(keepends=True)[0])
        try:
            assert run("bash", "-c", restore, cwd=checksum.parent, env=env, check=False).returncode != 0
            assert not run("docker", "volume", "ls", "-q", "--filter", f"label=corgi.redis.rollback={marker}").stdout.strip()
        finally:
            checksum.write_bytes(original)
        for phase, image, version in (("upgrade", CANDIDATE, "8.12.0"), ("rollback", BEFORE, "8.10.3")):
            copied = run("bash", "-c", restore, cwd=checksum.parent, env=env)
            mapped = dict(re.findall(r"^(redis|support_redis) ([0-9a-f]{64})$", copied.stdout, re.M))
            assert set(mapped) == set(SERVICES) and len(set(mapped.values())) == 2
            directory, name = root / phase, marker + "-" + phase
            configure(directory, image, passwords, external=mapped)
            targets.append((directory, name))
            compose(directory, name, "up", "-d", "--wait")
            verify(directory, name, version)
            if phase == "upgrade":
                for service in SERVICES:
                    assert redis(directory, name, service, "SET", "after-upgrade", "yes") == "OK"
                compose(directory, name, "stop")
                compose(directory, name, "up", "-d", "--wait")
                verify(directory, name, version, expect_new=True)
        compose(old, project, "up", "-d", "--wait")
        verify(old, project, "8.10.3")
        print("Redis volume rollback PASS: shop and Support Pro, authenticated AOF data, restart and independent rollback")
    finally:
        for directory, name in targets:
            compose(directory, name, "down", check=False)
        compose(old, project, "down", "--volumes", check=False)
        owned = run("docker", "volume", "ls", "-q", "--filter", f"label=corgi.redis.rollback={marker}").stdout.splitlines()
        for volume in owned:
            run("docker", "volume", "rm", volume, check=False)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="redis-volume-drill-") as directory:
        drill(Path(directory))
