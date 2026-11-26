"""PostgreSQL 18: pinned images, matching pg_dump client and the one-time data move."""
import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/upgrade-postgres.sh"
POSTGRES_TAG = "postgres:19.0-alpine"
POSTGRES_DIGEST = "cac45fb483caee3668946088a1c0532db89d5285c28dbfeac889b4068296e06f"
POSTGRES_PIN = f"{POSTGRES_TAG}@sha256:{POSTGRES_DIGEST}"


def compose(path):
    return yaml.safe_load((ROOT / path).read_text())


def test_every_database_service_runs_postgres_19_and_keeps_the_old_volumes():
    main = compose("docker-compose.yml")
    for name, volume in (("db", "postgres19_data"), ("support_db", "support_postgres19_data")):
        service = main["services"][name]
        assert POSTGRES_PIN in service["image"], service["image"]
        # PostgreSQL 19 images store data under /var/lib/postgresql/19/docker.
        assert f"{volume}:/var/lib/postgresql" in service["volumes"]
    # PostgreSQL 16 and 18 volumes stay declared so the moves and a rollback can reach them.
    assert {"postgres_data", "support_postgres_data", "postgres18_data", "support_postgres18_data", "postgres19_data", "support_postgres19_data"} <= set(main["volumes"])
    support = compose("services/support-pro/docker-compose.yml")
    assert support["services"]["db"]["volumes"] == ["pgdata19:/var/lib/postgresql"]
    assert "pgdata18" in support["volumes"]
    assert support["services"]["backup"]["image"] == POSTGRES_PIN
    test = compose("docker-compose.test.yml")
    assert any(s.get("image") == POSTGRES_PIN for s in test["services"].values())
    for path in ("docker-compose.yml", "docker-compose.test.yml", "services/support-pro/docker-compose.yml", ".github/workflows/ci.yml", "scripts/pin-images.sh"):
        assert "postgres:16" not in (ROOT / path).read_text().replace("postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea", ""), path


def test_postgres_19_image_is_pinned_and_18_stays_available_for_rollback():
    active = (
        "docker-compose.yml",
        "docker-compose.test.yml",
        "services/support-pro/docker-compose.yml",
        ".github/workflows/ci.yml",
        ".github/workflows/resolve-image-digests.yml",
        ".github/workflows/mobile-screenshots.yml",
    )
    for path in active:
        text = (ROOT / path).read_text()
        assert "postgres:18.6-alpine" not in text, path
        assert POSTGRES_TAG in text, path
    assert "POSTGRES_IMAGE" in (ROOT / "scripts/pin-images.sh").read_text()
    docs = (ROOT / "docs/EXTERNAL_DEPENDENCIES.md").read_text()
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    assert POSTGRES_DIGEST in docs
    assert POSTGRES_DIGEST in docs and "PostgreSQL License" in notices
    assert "ff64c9e3bdf8e2120107d3559de8db314e8305f7e38c5105903c6295876738ff" in (ROOT / "scripts/upgrade-postgres19.sh").read_text()


def test_backend_image_ships_a_postgres_18_client_for_in_app_backups():
    docker = (ROOT / "services/backend/Dockerfile").read_text()
    assert "ARG PG_CLIENT_MAJOR=19" in docker
    assert 'postgresql-client-${PG_CLIENT_MAJOR}' in docker
    assert "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8" in docker
    assert "apt.postgresql.org" in docker


def test_update_moves_data_before_the_new_stack_starts():
    update = (ROOT / "scripts/update.sh").read_text()
    assert update.index("bash scripts/upgrade-postgres.sh") < update.index("bash scripts/upgrade-postgres19.sh") < update.index("bash infrastructure/deployment/build-production.sh")
    assert "scripts/upgrade-postgres.sh" in (ROOT / "scripts/preflight.sh").read_text()
    assert SCRIPT.stat().st_mode & 0o111
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_move_keeps_the_old_volume_and_verifies_row_counts():
    script = SCRIPT.read_text()
    assert "docker volume rm" not in script.replace("(docker volume rm <project>_postgres_data)", "")
    assert "diff -u" in script and "--exit-on-error" in script and "PG_UPGRADE_FORCE" in script
    assert 'docker exec -i "$dest" psql -U "$user" -d "$db" -At' in script
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
    (tmp_path / "docker-compose.yml").write_text((ROOT / "docker-compose.yml").read_text())
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


def test_installs_pinned_to_postgres_16_are_switched_to_18(tmp_path):
    bin_dir, _ = fake_docker(tmp_path)
    old = "postgres:16-alpine@sha256:" + "1" * 64
    (tmp_path / ".env").write_text(f"DB_PASSWORD=x\nPOSTGRES_IMAGE={old}\nREDIS_IMAGE=redis@sha256:{'2'*64}\n")
    (tmp_path / ".env.images").write_text(f"POSTGRES_IMAGE={old}\n")
    run = subprocess.run(["bash", str(SCRIPT)], env={**os.environ, "APP_DIR": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    default = re.search(r"\$\{POSTGRES_IMAGE:-([^}]+)\}", (ROOT / "docker-compose.yml").read_text()).group(1)
    for name in (".env", ".env.images"):
        text = (tmp_path / name).read_text()
        assert f"POSTGRES_IMAGE={default}" in text and "postgres:16" not in text
    assert "REDIS_IMAGE=redis@sha256:" in (tmp_path / ".env").read_text()
    assert ".env: POSTGRES_IMAGE postgres:16-alpine -> postgres:19.0-alpine" in run.stdout
