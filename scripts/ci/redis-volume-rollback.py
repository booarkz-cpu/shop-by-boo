"""Exercise the documented Redis recovery procedure for both shipped Compose configurations."""

import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = "redis:8.12.0-alpine@sha256:5af80107c1eeecb484a2269b80a26d12bfa6521787da4663bd9f19f60a163483"


def run(*args, cwd=None, env=None, check=True):
    return subprocess.run(args, cwd=cwd, env=env, check=check, text=True, stdout=subprocess.PIPE)


def compose(directory, project, *args, check=True):
    files = ["-f", "docker-compose.yml"]
    if (directory / "redis-restored.yml").exists():
        files.extend(["-f", "redis-restored.yml"])
    return run("docker", "compose", "-p", project, *files, *args, cwd=directory, check=check)


def configure(directory, source, passwords):
    directory.mkdir()
    shutil.copyfile(source / "docker-compose.yml", directory / "docker-compose.yml")
    settings = (source / ".env.example").read_text() + "\nREDIS_PASSWORD=" + passwords["redis"] + "\n"
    if "support_redis" in passwords:
        settings += "SUPPORT_REDIS_PASSWORD=" + passwords["support_redis"] + "\n"
        (directory / "support-pro").mkdir()
        shutil.copyfile(ROOT / "services/support-pro/.env.example", directory / "support-pro/.env")
    (directory / ".env").write_text(settings)


def redis(directory, project, service, *args):
    return compose(
        directory, project, "exec", "-T", service, "sh", "-ec",
        'export REDISCLI_AUTH="$REDIS_PASSWORD"; exec redis-cli --raw "$@"', "redis-cli", *args,
    ).stdout.strip()


def verify(directory, project, services, version, expect_new=False):
    for service in services:
        assert f"redis_version:{version}" in redis(directory, project, service, "INFO", "server").splitlines()
        assert redis(directory, project, service, "HGET", "ticket", "source") == service
        assert redis(directory, project, service, "LRANGE", "queue", "0", "-1").splitlines() == ["first", "second"]
        assert 0 < int(redis(directory, project, service, "TTL", "lease")) <= 3600
        assert redis(directory, project, service, "GET", "after-upgrade") == ("yes" if expect_new else "")
        unauth = compose(directory, project, "exec", "-T", service, "redis-cli", "ping", check=False)
        assert "NOAUTH" in unauth.stdout


def drill(root, source, services, scripts, overlay):
    backup, restore, start = scripts
    marker = "corgi-redis-drill-" + uuid.uuid4().hex
    old = root / "source"
    project = marker + "-source"
    passwords = {service: secrets.token_hex(24) for service in services}
    backup_root = root / "backups"
    backup_root.mkdir()
    env = dict(os.environ, COMPOSE_PROJECT_NAME=project, REDIS_BACKUP_DIR=str(backup_root),
               REDIS_RESTORE_ID=marker, REDIS_STANDALONE_SUPPORT=str(int(len(services) == 1)))
    configure(old, source, passwords)
    targets = []
    try:
        compose(old, project, "up", "-d", "--no-deps", "--wait", *services)
        for service in services:
            redis(old, project, service, "HSET", "ticket", "source", service)
            redis(old, project, service, "RPUSH", "queue", "first", "second")
            redis(old, project, service, "SET", "lease", "holder", "EX", "3600")
            assert redis(old, project, service, "SAVE") == "OK"
        verify(old, project, services, "8.10.3")
        assert run("bash", "-c", backup, cwd=old, env=env, check=False).returncode != 0
        compose(old, project, "stop", *services)
        run("bash", "-c", backup, cwd=old, env=env)
        (checksum,) = backup_root.glob("*/SHA256SUMS")
        original = checksum.read_bytes()
        checksum.write_bytes(original.splitlines(keepends=True)[0])
        try:
            assert run("bash", "-c", restore, cwd=checksum.parent, env=env, check=False).returncode != 0
            assert not run("docker", "volume", "ls", "-q", "--filter", f"label=corgi.redis.rollback={marker}").stdout.strip()
        finally:
            checksum.write_bytes(original)
        for phase, version in (("upgrade", "8.12.0"), ("rollback", "8.10.3")):
            copied = run("bash", "-c", restore, cwd=checksum.parent, env=env)
            mapped = dict(re.findall(r"^(redis|support_redis) ([0-9a-f]{64})$", copied.stdout, re.M))
            assert set(mapped) == set(services) and len(set(mapped.values())) == len(services)
            directory, name = root / phase, marker + "-" + phase
            configure(directory, source, passwords)
            with (directory / ".env").open("a") as settings:
                for service, volume in mapped.items():
                    settings.write(f"RESTORED_{service.upper()}_VOLUME={volume}\n")
            spec = overlay + "\n"
            if phase == "upgrade":
                spec += "services:\n" + "".join(f"  {s}:\n    image: {CANDIDATE}\n" for s in services)
            (directory / "redis-restored.yml").write_text(spec)
            targets.append((directory, name))
            model = json.loads(compose(directory, name, "config", "--format", "json", *services).stdout)
            for service in services:
                mount, = [m for m in model["services"][service]["volumes"] if m["target"] == "/data"]
                volume = model["volumes"][mount["source"]]
                assert mount["type"] == "volume" and volume["external"] and volume["name"] == mapped[service]
            run("bash", "-c", start, cwd=directory, env=dict(env, REDIS_RESTORE_PROJECT=name))
            verify(directory, name, services, version)
            if phase == "upgrade":
                for service in services:
                    assert redis(directory, name, service, "SET", "after-upgrade", "yes") == "OK"
                compose(directory, name, "stop", *services)
                compose(directory, name, "up", "-d", "--no-deps", "--wait", *services)
                verify(directory, name, services, version, expect_new=True)
        compose(old, project, "up", "-d", "--no-deps", "--wait", *services)
        verify(old, project, services, "8.10.3")
        print(f"Redis recovery PASS ({source.relative_to(ROOT)}): {', '.join(services)}, restart and rollback", flush=True)
    finally:
        for directory, name in targets:
            compose(directory, name, "down", check=False)
        compose(old, project, "down", "--volumes", check=False)
        owned = run("docker", "volume", "ls", "-q", "--filter", f"label=corgi.redis.rollback={marker}").stdout.splitlines()
        for volume in owned:
            run("docker", "volume", "rm", volume, check=False)


if __name__ == "__main__":
    guide = (ROOT / "docs/modules/redis_and_postgres.md").read_text()
    scripts = re.findall(r"^```bash\n(.*?)\n```", guide, re.M | re.S)
    integrated, standalone = re.findall(r"^```yaml\n(.*?)\n```", guide, re.M | re.S)
    for source, services, overlay in ((ROOT, ("redis", "support_redis"), integrated),
                                      (ROOT / "services/support-pro", ("redis",), standalone)):
        with tempfile.TemporaryDirectory(prefix="redis-volume-drill-") as directory:
            drill(Path(directory), source, services, scripts, overlay)
