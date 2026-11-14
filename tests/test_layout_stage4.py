"""Layout stage 4: deploy/ and terraform/ live in infrastructure/. The old paths installed servers and
older instructions call keep working, the MX certificate of an updated server moves with its folder, and nothing
mounted by Docker Compose points at a path that is gone."""
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIMS = ("install-vps.sh", "install-docker.sh", "resume-vps-after-pin.sh", "build-production.sh")


def tree(tmp_path: Path) -> Path:
    app = tmp_path / "shop"
    (app / "deploy").mkdir(parents=True)
    (app / "infrastructure" / "deployment").mkdir(parents=True)
    for name in (*SHIMS, "install-status.sh"):
        shutil.copy(ROOT / "deploy" / name, app / "deploy" / name)
    return app


def test_old_script_paths_run_the_moved_scripts_with_their_arguments(tmp_path):
    app = tree(tmp_path)
    for name in SHIMS:
        (app / "infrastructure" / "deployment" / name).write_text(f'#!/bin/sh\necho "{name} got:$*"\n')
        run = subprocess.run(["bash", f"deploy/{name}", "--flag", "two words"], cwd=app, capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        assert run.stdout.strip() == f"{name} got:--flag two words"
        # called by absolute path from another directory, as an older scripts/update.sh or a cron line does
        run = subprocess.run(["bash", str(app / "deploy" / name)], cwd=tmp_path, capture_output=True, text=True)
        assert run.stdout.strip() == f"{name} got:"


def test_a_failing_moved_script_fails_the_old_path_too(tmp_path):
    app = tree(tmp_path)
    (app / "infrastructure" / "deployment" / "build-production.sh").write_text("#!/bin/sh\nexit 7\n")
    assert subprocess.run(["bash", "deploy/build-production.sh"], cwd=app).returncode == 7


def test_old_install_status_path_still_gives_the_functions():
    names = "stage_start stage_done stage_fail"
    out = {}
    for path in ("deploy/install-status.sh", "infrastructure/deployment/install-status.sh"):
        run = subprocess.run(["bash", "-c", f"source {ROOT / path}; declare -F | awk '{{print $3}}' | sort"],
                             capture_output=True, text=True, env={**os.environ, "INSTALL_STATUS": "/dev/null"})
        assert run.returncode == 0, run.stderr
        out[path] = run.stdout.split()
    assert out["deploy/install-status.sh"] == out["infrastructure/deployment/install-status.sh"]
    assert out["deploy/install-status.sh"], names


def build(app: Path, tmp_path: Path):
    """The real build script on a server without Docker: only the steps before the containers run."""
    (app / "scripts").mkdir(exist_ok=True)
    (app / ".env").write_text("APP_ENV=test\n")
    (app / "scripts" / "harden-env.py").write_text("")
    (app / "scripts" / "preflight.sh").write_text("exit 0\n")
    shutil.copy(ROOT / "infrastructure/deployment/build-production.sh", app / "infrastructure/deployment/build-production.sh")
    fakebin = tmp_path / "bin"   # every tool the script needs, and no docker
    fakebin.mkdir(exist_ok=True)
    for tool in ("bash", "python3", "basename", "dirname", "mkdir", "cp", "env", "sh"):
        link = fakebin / tool
        if not link.exists():
            link.symlink_to(shutil.which(tool))
    return subprocess.run(["bash", "deploy/build-production.sh"], cwd=app, capture_output=True, text=True,
                          env={"PATH": str(fakebin), "HOME": str(tmp_path)})


def test_update_from_an_older_release_keeps_the_mail_certificate(tmp_path):
    app = tree(tmp_path)
    old = app / "deploy" / "mail-tls"
    old.mkdir()
    (old / "README.txt").write_text("old readme")
    (old / "fullchain.pem").write_text("CERT")
    (old / "privkey.pem").write_text("KEY")
    (old / "privkey.pem").chmod(0o600)
    new = app / "infrastructure" / "deployment" / "mail-tls"
    new.mkdir()
    (new / "README.txt").write_text("new readme")
    run = build(app, tmp_path)
    assert run.returncode == 0, run.stderr + run.stdout
    assert (new / "fullchain.pem").read_text() == "CERT" and (new / "privkey.pem").read_text() == "KEY"
    assert (new / "privkey.pem").stat().st_mode & 0o777 == 0o600, "the key keeps its permissions"
    assert (new / "README.txt").read_text() == "new readme"
    assert (old / "privkey.pem").exists(), "the old files stay: a rollback finds them"

    # the second update does not overwrite a certificate renewed in the new folder
    (new / "fullchain.pem").write_text("RENEWED")
    run = build(app, tmp_path)
    assert run.returncode == 0, run.stderr
    assert (new / "fullchain.pem").read_text() == "RENEWED" and "moved" not in run.stdout


def test_a_fresh_install_without_the_old_folder_builds(tmp_path):
    app = tree(tmp_path)
    run = build(app, tmp_path)
    assert run.returncode == 0, run.stderr + run.stdout


def test_everything_docker_compose_mounts_or_builds_exists():
    for name in ("docker-compose.yml", "docker-compose.test.yml", "docker-compose.integration.yml", "support-pro/docker-compose.yml"):
        text = (ROOT / name).read_text()
        base = (ROOT / name).parent
        assert not re.search(r"\./deploy/|\./terraform/", text), name
        paths = re.findall(r"^\s*-\s+(\./[^:\s]+):", text, re.M) + re.findall(r"^\s*context:\s+(\./\S+)", text, re.M)
        tracked = [p for p in paths if p.startswith("./infrastructure/")]
        if name == "docker-compose.yml":
            assert len(tracked) >= 8, tracked
        for path in tracked:
            assert (base / path).exists(), f"{name}: {path}"


def test_no_live_file_points_at_a_moved_path():
    """Scripts, workflows, compose files and tests name the new paths; only the shims stay in deploy/."""
    assert sorted(p.name for p in (ROOT / "deploy").iterdir()) == sorted((*SHIMS, "install-status.sh"))
    assert not (ROOT / "terraform").exists()
    moved = re.compile(r"(?<![A-Za-z0-9_-])deploy/(Caddyfile|caddy/|nginx/|prometheus|grafana|wireguard|mail-tls)|(?<![A-Za-z0-9_/-])terraform/corgi")
    allowed = {"tests/test_layout_stage4.py", "infrastructure/deployment/build-production.sh"}
    listed = subprocess.run(["git", "ls-files", ".github/workflows", "scripts", "tests", "backend/app", "*.yml", "*.sh"],
                            cwd=ROOT, capture_output=True, text=True).stdout.split()
    bad = []
    for rel in listed:
        path = ROOT / rel
        if rel in allowed or not path.is_file() or path.suffix in {".png", ".jpg", ".webp", ".zip"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        bad += [f"{rel}: {m.group(0)}" for m in moved.finditer(text)]
    assert not bad, bad
