"""Read-only PostgreSQL 19 preflight guards (no Docker daemon required)."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/postgres19-preflight.sh"


def _run(tmp_path, volumes=(), spec=None):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "docker.log"
    docker = bindir / "docker"
    docker.write_text(
        '#!/usr/bin/env bash\n'
        f'echo "$*" >> "{log}"\n'
        'case "$*" in\n'
        '  "compose config --format json") echo \'{"name":"shop"}\';;\n'
        '  "compose config --services") printf "db\\nsupport_db\\n";;\n'
        '  "volume inspect "*)\n'
        + "".join(f'    [[ "$3" == "{v}" ]] && exit 0\n' for v in volumes)
        + '    exit 1;;\n'
        '  *) exit 99;;\n'
        'esac\n'
    )
    docker.chmod(0o755)
    env = {**os.environ, "APP_DIR": str(tmp_path), "PATH": f"{bindir}:{os.environ['PATH']}"}
    if spec is not None:
        env["PG19_PREFLIGHT_SPEC"] = spec
    return subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True), log.read_text()


def test_preflight_reports_missing_source_without_mutating(tmp_path):
    run, calls = _run(tmp_path)
    assert run.returncode == 1
    assert "source volume shop_postgres18_data missing" in run.stdout
    assert "compose down" not in calls and "docker run" not in calls
    assert all(line.startswith(("compose config", "volume inspect")) for line in calls.splitlines())


def test_preflight_reports_existing_target_and_does_not_overwrite(tmp_path):
    run, calls = _run(tmp_path, ("shop_postgres18_data", "shop_support_postgres18_data", "shop_postgres19_data"))
    assert run.returncode == 1
    assert "target volume shop_postgres19_data already exists" in run.stdout
    assert "target volume shop_support_postgres19_data absent" in run.stdout
    assert all(line.startswith(("compose config", "volume inspect")) for line in calls.splitlines())


def test_preflight_rejects_invalid_spec(tmp_path):
    run, calls = _run(tmp_path, spec="db:old:old")
    assert run.returncode == 2
    assert "Invalid PG19_PREFLIGHT_SPEC" in run.stderr
    assert "volume inspect" not in calls


def test_preflight_script_syntax():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_preflight_rejects_duplicate_or_colliding_volumes(tmp_path):
    for spec in ("db:old:new,support_db:other:new", "db:old:new,support_db:new:other", "db:old:new,"):
        run, calls = _run(tmp_path, spec=spec)
        assert run.returncode == 2
        assert "Invalid PG19_PREFLIGHT_SPEC" in run.stderr
        assert "volume inspect" not in calls


def test_preflight_rejects_unavailable_compose_service(tmp_path):
    run, calls = _run(tmp_path, volumes=("shop_postgres18_data",), spec="unknown:postgres18_data:postgres19_data")
    assert run.returncode == 1
    assert "unknown: not present in this Compose profile" in run.stderr
    assert "volume inspect" not in calls
