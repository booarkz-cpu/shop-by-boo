"""PostgreSQL 18 -> 19 move: backup, refusal paths, and an untouched source volume."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/upgrade-postgres19.sh"


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
    assert "PG19_UPGRADE_FORCE" in text and "PG19_MIN_FREE_BYTES" in text and "PG19_ROLLBACK" in text
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
    assert text.index("cannot establish destination state") < text.index("DROP DATABASE")
