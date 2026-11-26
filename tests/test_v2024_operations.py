"""Regression checks for first secret rotation and immutable image pinning."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def fake_docker(tmp_path, inspect_digest=""):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker = fakebin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        f"  *'image inspect'*) printf '%s\\n' '{inspect_digest}';;\n"
        "esac\n"
    )
    docker.chmod(0o755)
    return {**os.environ, "APP_DIR": str(tmp_path), "PATH": f"{fakebin}:{os.environ['PATH']}"}


def value(path, name):
    return next(line.split("=", 1)[1] for line in path.read_text().splitlines()
                if line.startswith(name + "="))


def test_first_and_second_secret_rotation_keep_only_previous_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"APP_SECRET='{'a' * 64}'\nMETRICS_TOKEN='metrics'\n")
    env_file.chmod(0o600)
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/doctor.sh", tmp_path / "scripts/doctor.sh")
    env = fake_docker(tmp_path)
    for _ in range(2):
        current = value(env_file, "APP_SECRET")
        run = subprocess.run(["bash", str(ROOT / "scripts/rotate-secrets.sh")], cwd=tmp_path,
                             env=env, capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        assert value(env_file, "APP_SECRET_PREVIOUS") == current
        assert value(env_file, "APP_SECRET") != current
        assert env_file.read_text().count("APP_SECRET_PREVIOUS=") == 1
        assert env_file.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("installed", ["", "redis@sha256:" + "1" * 64])
def test_missing_image_digest_does_not_replace_existing_env(tmp_path, installed):
    shutil.copyfile(ROOT / "docker-compose.yml", tmp_path / "docker-compose.yml")
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_TOKEN='preserved'\n")
    run = subprocess.run(["bash", str(ROOT / "scripts/pin-images.sh")], cwd=tmp_path,
                         env=fake_docker(tmp_path, installed), capture_output=True, text=True)
    assert run.returncode != 0
    assert "No immutable digest" in run.stderr
    assert env_file.read_text() == "BOT_TOKEN='preserved'\n"
    assert not (tmp_path / ".env.images").exists()
