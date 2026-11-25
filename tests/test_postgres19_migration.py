"""PostgreSQL 18 -> 19 move: backup, refusal paths, and an untouched source volume."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/upgrade-postgres19.sh"


def test_drill_rejects_swapped_databases_and_corruption_with_unchanged_totals(tmp_path):
    import sys

    probe = ROOT / "scripts/ci/verify-pg-upgrade-fixture.py"
    rows = ["db\tsupport\t19", *(f"order\t{i}\tsupport order {i}\t{i}.00" for i in range(1, 1501)),
            *(f"user\t{i}" for i in range(1, 43))]
    fixture = tmp_path / "fixture"
    command = [sys.executable, str(probe), "support", "19", sys.executable, "-c",
               "import pathlib,sys; sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())", str(fixture)]
    for first_order, should_match in [
        ("order\t1\tsupport order 1\t1.00", True),
        ("order\t1\tvpnshop order 1\t1.00", False),
        ("order\t1\tchanged\t1.00", False),
    ]:
        rows[1] = first_order
        fixture.write_text("\n".join(rows) + "\n")
        result = subprocess.run(command, capture_output=True)
        assert (result.returncode == 0) == should_match, result.stderr


def test_password_reader_receives_the_service_as_an_argument():
    for name in ("scripts/upgrade-postgres.sh", "scripts/upgrade-postgres19.sh"):
        text = (ROOT / name).read_text()
        assert 'os.environ["PG_SVC"]' not in text
        assert "sys.argv[1]" in text
    proc = subprocess.run(
        ["python3", "-c", "import json,sys\nsvc=sys.argv[1]\nenv=(json.load(sys.stdin).get('services') or {}).get(svc,{}).get('environment') or {}\nprint(env.get('POSTGRES_PASSWORD',''))", "db"],
        input='{"services":{"db":{"environment":{"POSTGRES_PASSWORD":"secret"}}}}',
        text=True, capture_output=True, check=True,
    )
    assert proc.stdout.strip() == "secret"


def test_script_keeps_the_source_volume_and_checks_the_restore():
    text = SCRIPT.read_text()
    assert "docker volume rm" not in text
    assert "pg_dump" in text and "--exit-on-error" in text and "diff -u" in text
    assert "PG19_UPGRADE_FORCE" not in text and "PG19_MIN_FREE_BYTES" in text and "PG19_ROLLBACK" in text
    assert "restore failed; PostgreSQL 18 volume" in text
    assert "not enough free space" in text
    assert "--network none" in text
    assert 'docker exec -i "$dest" psql -U "$user" -d "$db" -At' in text
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def _fake(tmp_path, volumes=()):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "docker.log"
    listed = " ".join(volumes)
    (bindir / "docker").write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{log}"\n'
        'case "$*" in\n'
        '  "compose config --format json") echo \'{"name":"shop"}\';;\n'
        '  "compose config --services") printf "db\\nsupport_db\\n";;\n'
        '  "volume inspect "*)\n'
        f'    for v in {listed}; do [[ "$3" == "$v" ]] && exit 0; done; exit 1;;\n'
        '  *) exit 0;;\n'
        "esac\n"
    )
    (bindir / "docker").chmod(0o755)
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    return bindir, log


def _run(tmp_path, bindir, **env):
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={**os.environ, "APP_DIR": str(tmp_path), "PATH": f"{bindir}:{os.environ['PATH']}", **env},
        capture_output=True,
        text=True,
    )


def test_fresh_install_does_not_stop_the_stack(tmp_path):
    bindir, log = _fake(tmp_path)
    run = _run(tmp_path, bindir)
    assert run.returncode == 0, run.stderr
    assert "db: no PostgreSQL 18 volume" in run.stdout
    assert "compose down" not in log.read_text()


def test_refuses_when_free_space_is_below_the_requested_floor(tmp_path):
    bindir, log = _fake(tmp_path, ("shop_postgres18_data",))
    run = _run(tmp_path, bindir, PG19_MIN_FREE_BYTES=str(10**18))
    assert run.returncode == 1, run.stdout
    assert "not enough free space" in run.stderr
    assert "run -d" not in log.read_text()


def test_rejects_a_malformed_spec(tmp_path):
    bindir, _ = _fake(tmp_path)
    run = _run(tmp_path, bindir, PG19_UPGRADE_SPEC="db:old:new:bad user:db")
    assert run.returncode == 2
    assert "Bad PG19_UPGRADE_SPEC" in run.stderr


def test_rollback_flag_checks_the_18_baseline_without_deleting_it(tmp_path):
    bindir, log = _fake(tmp_path, ("shop_postgres18_data",))
    docker = bindir / "docker"
    docker.write_text(
        docker.read_text().replace(
            "  *) exit 0;;",
            '  "run --rm --entrypoint cat "*) echo 18;;\n  *) exit 0;;',
        )
    )
    run = _run(tmp_path, bindir, PG19_ROLLBACK="1")
    assert run.returncode == 0, run.stderr + run.stdout
    assert "intact for rollback" in run.stdout
    assert "volume rm" not in log.read_text()



def test_destination_guard_uses_catalog_not_estimated_row_statistics():
    text = SCRIPT.read_text()
    assert "n_live_tup" not in text
    assert "FROM pg_class c JOIN pg_namespace" in text
    assert "cannot establish destination state" in text
    assert "relname <> 'alembic_version'" not in text
    assert "DROP DATABASE" not in text
    assert text.index("cannot establish destination state") < text.index("pg_restore -U")
    assert "--single-transaction" in text
    assert "insufficient destination storage" in text


def test_rejects_identical_source_and_destination_volumes(tmp_path):
    bindir, log = _fake(tmp_path, ("shop_old",))
    run = _run(tmp_path, bindir, PG19_UPGRADE_SPEC="db:old:old:vpnshop:vpnshop")
    assert run.returncode == 2
    assert "source and destination volumes must differ" in run.stderr
    assert "compose down" not in log.read_text()
    assert "run -d" not in log.read_text()


def test_nonempty_destination_refuses_even_with_legacy_force(tmp_path):
    bindir, log = _fake(tmp_path, ("shop_postgres18_data",))
    docker = bindir / "docker"
    docker.write_text(docker.read_text().replace(
        '{"name":"shop"}',
        '{"name":"shop","services":{"db":{"environment":{"POSTGRES_PASSWORD":"test-only"}}}}',
    ).replace(
        "  *) exit 0;;",
        '  "run --rm --entrypoint cat "*) echo 18;;\n'
        '  "run --rm --entrypoint du "*) echo "1024 /old";;\n'
        '  "exec "*" df -Pk "*) printf "Filesystem 1024-blocks Used Available Capacity Mounted\\n/dev/test 100000 1 99999 1%% /var/lib/postgresql\\n";;\n'
        '  "exec "*"FROM pg_class c JOIN pg_namespace"*) echo 1;;\n'
        '  *) exit 0;;',
    ))
    run = _run(tmp_path, bindir, PG19_UPGRADE_FORCE="1")
    assert run.returncode == 1, run.stderr + run.stdout
    assert "Existing destination data will not be overwritten" in run.stderr
    commands = log.read_text()
    assert "pg_restore" not in commands
    assert "pg_dump" not in commands
    assert "DROP DATABASE" not in commands
    assert "volume rm" not in commands


def test_failed_restore_keeps_backup_and_does_not_mark_success(tmp_path):
    bindir, log = _fake(tmp_path, ("shop_postgres18_data",))
    docker = bindir / "docker"
    docker.write_text(docker.read_text().replace(
        '{"name":"shop"}',
        '{"name":"shop","services":{"db":{"environment":{"POSTGRES_PASSWORD":"test-only"}}}}',
    ).replace(
        "  *) exit 0;;",
        '  "run --rm --entrypoint cat "*) echo 18;;\n'
        '  "run --rm --entrypoint du "*) echo "1024 /old";;\n'
        '  "exec "*" df -Pk "*) printf "Filesystem Blocks Used Available Capacity Mounted\\n/dev/test 100000 1 99999 1%% /var/lib/postgresql\\n";;\n'
        '  "exec "*"FROM pg_class c JOIN pg_namespace"*) echo 0;;\n'
        '  "exec "*" pg_dump "*) echo "test dump";;\n'
        '  "exec "*" pg_restore "*) exit 1;;\n'
        '  *) exit 0;;',
    ))
    run = _run(tmp_path, bindir)
    assert run.returncode == 1, run.stderr + run.stdout
    assert "restore failed" in run.stderr
    backups = list((tmp_path / ".rollback").glob("postgres18-db-*.dump"))
    assert len(backups) == 1
    assert backups[0].read_text() == "test dump\n"
    commands = log.read_text()
    assert "--single-transaction" in commands
    assert "echo moved" not in commands
    assert "volume rm" not in commands


def test_completed_migration_is_not_repeated(tmp_path):
    bindir, log = _fake(tmp_path, ("shop_postgres18_data", "shop_postgres19_data"))
    docker = bindir / "docker"
    docker.write_text(docker.read_text().replace(
        "  *) exit 0;;",
        '  "run --rm --entrypoint cat "*"/new/19/docker/PG_VERSION") echo 19;;\n'
        '  "run --rm --entrypoint cat "*) echo 18;;\n  *) exit 0;;',
    ))
    run = _run(tmp_path, bindir)
    assert run.returncode == 0, run.stderr + run.stdout
    assert "already moved to PostgreSQL 19" in run.stdout
    assert "compose down" not in log.read_text()
    assert "pg_restore" not in log.read_text()


def test_completed_marker_with_wrong_version_is_rejected(tmp_path):
    bindir, log = _fake(tmp_path, ("shop_postgres18_data", "shop_postgres19_data"))
    docker = bindir / "docker"
    docker.write_text(docker.read_text().replace(
        "  *) exit 0;;",
        '  "run --rm --entrypoint cat "*) echo 18;;\n  *) exit 0;;',
    ))
    run = _run(tmp_path, bindir)
    assert run.returncode == 1, run.stderr + run.stdout
    assert "migration marker exists but destination PG_VERSION is not 19" in run.stderr
    assert "compose down" not in log.read_text()
    assert "pg_restore" not in log.read_text()
