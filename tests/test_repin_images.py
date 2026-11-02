"""v28.64.0: an update moves REDIS_IMAGE and CADDY_IMAGE pinned in .env to the images of the release.

pin-images.sh writes digests into .env, which overrides docker-compose.yml; without scripts/repin-images.sh an
installed shop would keep Redis 7.4 and Caddy 2.10 after updating to a release built for Redis 8.10 / Caddy 2.11."""
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/repin-images.sh"
OLD_REDIS = "redis:7.4-alpine@sha256:" + "1" * 64
OLD_CADDY = "caddy:2.10-alpine@sha256:" + "2" * 64


def default(key):
    return re.search(r"\$\{" + key + r":-([^}]+)\}", (ROOT / "docker-compose.yml").read_text()).group(1)


def run(tmp_path, **env):
    (tmp_path / "docker-compose.yml").write_text((ROOT / "docker-compose.yml").read_text())
    return subprocess.run(["bash", str(SCRIPT)], env={**os.environ, "APP_DIR": str(tmp_path), **env}, capture_output=True, text=True)


def test_release_defaults_are_redis_8_and_caddy_2_11():
    assert default("REDIS_IMAGE").startswith("redis:8.10-alpine@sha256:")
    assert default("CADDY_IMAGE").startswith("caddy:2.11-alpine@sha256:")


def test_old_pins_follow_the_release(tmp_path):
    (tmp_path / ".env").write_text(f"DB_PASSWORD=x\nREDIS_IMAGE={OLD_REDIS}\nCADDY_IMAGE={OLD_CADDY}\nPOSTGRES_IMAGE=keep\n")
    (tmp_path / ".env.images").write_text(f"REDIS_IMAGE={OLD_REDIS}\n")
    out = run(tmp_path)
    assert out.returncode == 0, out.stderr
    env = (tmp_path / ".env").read_text()
    assert f"REDIS_IMAGE={default('REDIS_IMAGE')}" in env and f"CADDY_IMAGE={default('CADDY_IMAGE')}" in env
    assert "POSTGRES_IMAGE=keep" in env and "DB_PASSWORD=x" in env
    assert f"REDIS_IMAGE={default('REDIS_IMAGE')}" in (tmp_path / ".env.images").read_text()
    assert ".env: REDIS_IMAGE redis:7.4-alpine -> redis:8.10-alpine" in out.stdout


def test_current_pins_bare_digests_and_owner_choice_are_kept(tmp_path):
    same = default("REDIS_IMAGE").split("@")[0] + "@sha256:" + "3" * 64  # same tag, digest from this server
    (tmp_path / ".env").write_text(f"REDIS_IMAGE={same}\nCADDY_IMAGE=caddy@sha256:{'4' * 64}\n")
    out = run(tmp_path)
    assert out.returncode == 0, out.stderr
    env = (tmp_path / ".env").read_text()
    assert f"REDIS_IMAGE={same}" in env and f"CADDY_IMAGE=caddy@sha256:{'4' * 64}" in env and "has no tag" in out.stdout
    (tmp_path / ".env").write_text(f"REDIS_IMAGE={OLD_REDIS}\n")
    assert run(tmp_path, KEEP_PINNED_IMAGES="1").returncode == 0
    assert f"REDIS_IMAGE={OLD_REDIS}" in (tmp_path / ".env").read_text()


def test_update_runs_it_before_the_build():
    update = (ROOT / "scripts/update.sh").read_text()
    assert update.index("bash scripts/repin-images.sh") < update.index("bash deploy/build-production.sh")
