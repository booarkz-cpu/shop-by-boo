"""PostgreSQL 18: pinned images, matching pg_dump client and the one-time data move."""
import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/upgrade-postgres.sh"


def compose(path):
    return yaml.safe_load((ROOT / path).read_text())


def test_every_database_service_runs_postgres_18_on_the_new_volume_layout():
    main = compose("docker-compose.yml")
    for name, volume in (("db", "postgres18_data"), ("support_db", "support_postgres18_data")):
        service = main["services"][name]
        assert re.search(r"postgres:18\.\d+-alpine@sha256:[0-9a-f]{64}", service["image"]), service["image"]
        # PostgreSQL 18 images store data under /var/lib/postgresql/18/docker.
        assert f"{volume}:/var/lib/postgresql" in service["volumes"]
    # The PostgreSQL 16 volumes stay declared so the move and a rollback can reach them.
    assert {"postgres_data", "support_postgres_data", "postgres18_data", "support_postgres18_data"} <= set(main["volumes"])
    support = compose("support-pro/docker-compose.yml")
    assert support["services"]["db"]["volumes"] == ["pgdata18:/var/lib/postgresql"]
    assert re.search(r"postgres:18\.\d+-alpine@", support["services"]["backup"]["image"])
    test = compose("docker-compose.test.yml")
    assert any("postgres:18." in str(s.get("image", "")) for s in test["services"].values())
    for path in ("docker-compose.yml", "docker-compose.test.yml", "support-pro/docker-compose.yml", ".github/workflows/ci.yml", "scripts/pin-images.sh"):
        assert "postgres:16" not in (ROOT / path).read_text().replace("postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea", ""), path


def test_backend_image_ships_a_postgres_18_client_for_in_app_backups():
    docker = (ROOT / "backend/Dockerfile").read_text()
    assert "ARG PG_CLIENT_MAJOR=18" in docker
    assert 'postgresql-client-${PG_CLIENT_MAJOR}' in docker
    assert "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8" in docker
    assert "apt.postgresql.org" in docker


def test_update_moves_data_before_the_new_stack_starts():
    update = (ROOT / "scripts/update.sh").read_text()
    assert update.index("bash scripts/upgrade-postgres.sh") < update.index("bash deploy/build-production.sh")
    assert "scripts/upgrade-postgres.sh" in (ROOT / "scripts/preflight.sh").read_text()
    assert SCRIPT.stat().st_mode & 0o111
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_move_keeps_the_old_volume_and_verifies_row_counts():
    script = SCRIPT.read_text()
    assert "docker volume rm" not in script.replace("(docker volume rm <project>_postgres_data)", "")
    assert "diff -u" in script and "--exit-on-error" in script and "PG_UPGRADE_FORCE" in script
    assert "--network none" in script


def fake_docker(tmp_path, volumes=()):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    (bin_dir / "docker").write_text(f"""#!/usr/bin/env bash
echo "$*" >> {log}
case "$*" in
  "compose config --format json") echo '{{"name":"shop"}}';;
  "compose config --services") printf 'db\\nsupport_db\\nbackend\\n';;
  "volume inspect "*) for v in {' '.join(volumes)}; do [[ "$3" == "$v" ]] && exit 0; done; exit 1;;
  *) exit 0;;
esac
""")
    (bin_dir / "docker").chmod(0o755)
    return bin_dir, log


def test_fresh_install_has_nothing_to_move(tmp_path):
    bin_dir, log = fake_docker(tmp_path)
    run = subprocess.run(["bash", str(SCRIPT)], env={**os.environ, "APP_DIR": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "db: no PostgreSQL 16 volume (shop_postgres_data)" in run.stdout
    assert "support_db: no PostgreSQL 16 volume" in run.stdout
    assert "compose down" not in log.read_text()  # the running stack is not touched


def test_rejects_malformed_specs(tmp_path):
    bin_dir, _ = fake_docker(tmp_path)
    run = subprocess.run(["bash", str(SCRIPT)], env={**os.environ, "APP_DIR": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}",
                                                     "PG_UPGRADE_SPEC": "db:old;rm -rf /:new:u:d"}, capture_output=True, text=True)
    assert run.returncode == 2 and "Bad PG_UPGRADE_SPEC" in run.stderr
