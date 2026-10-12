"""Exercise the release config writer and the destructive update boundary."""
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pin_images_can_run_from_non_executable_release_copy(tmp_path):
    script = (ROOT / "deploy/install-vps.sh").read_text()
    assert "bash scripts/pin-images.sh" in script
    for name in ("pin-images.sh", "preflight.sh"):
        assert (ROOT / "scripts" / name).stat().st_mode & 0o111

    (tmp_path / ".env").write_text("BOT_TOKEN='preserved-secret'\n")
    pin = tmp_path / "pin-images.sh"
    shutil.copyfile(ROOT / "scripts/pin-images.sh", pin)
    pin.chmod(0o644)  # Reproduce the mode in the failing v20.0.22 release.
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker = fakebin / "docker"
    docker.write_text("#!/bin/sh\ncase \"$*\" in *'image inspect'*) echo 'image@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';; esac\n")
    docker.chmod(0o755)
    run = subprocess.run(["bash", str(pin)], cwd=tmp_path,
                         env={**os.environ, "APP_DIR": str(tmp_path), "PATH": f"{fakebin}:{os.environ['PATH']}"},
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "BOT_TOKEN='preserved-secret'" in (tmp_path / ".env").read_text()
    assert "REDIS_IMAGE=image@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef" in (tmp_path / ".env.images").read_text()


def test_resume_after_pin_preserves_credentials_and_finishes(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "support-pro").mkdir()
    shutil.copyfile(ROOT / "scripts/pin-images.sh", tmp_path / "scripts/pin-images.sh")
    (tmp_path / "scripts/pin-images.sh").chmod(0o644)
    (tmp_path / ".env").write_text("APP_VERSION='20.0.22'\nBOT_TOKEN='preserved-secret'\n")
    (tmp_path / "support-pro/.env").write_text("ADMIN_PASSWORD='preserved-admin'\n")
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker = fakebin / "docker"
    docker.write_text("#!/bin/sh\ncase \"$*\" in *'image inspect'*) echo 'image@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';; esac\n")
    docker.chmod(0o755)
    resume = (ROOT / "deploy/resume-vps-after-pin.sh").read_text()
    # Run the production continuation body with a fake Docker CLI; its root-only
    # guard is checked separately by the actual script before this point.
    body = resume[resume.index("umask 077\n"):]
    command = f'''set -Eeuo pipefail
ROOT='{tmp_path}'
APP_DIR="$ROOT"
export APP_DIR
cd "$ROOT"
''' + body
    for _ in range(2):
        run = subprocess.run(["bash", "-c", command], cwd=tmp_path,
                             env={**os.environ, "PATH": f"{fakebin}:{os.environ['PATH']}"},
                             capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
    shop = (tmp_path / ".env").read_text()
    assert "BOT_TOKEN='preserved-secret'" in shop
    assert "ADMIN_PASSWORD='preserved-admin'" in (tmp_path / "support-pro/.env").read_text()
    for key in ("PYTHON_BASE_IMAGE", "NODE_BASE_IMAGE", "NGINX_BASE_IMAGE"):
        assert shop.count(key + "=") == 1
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600


def test_installer_produces_both_env_files_without_corrupting_secrets(tmp_path):
    script = (ROOT / "deploy/install-vps.sh").read_text()
    functions = script[script.index("env_line() {"):script.index("# Previous release contract:")]
    writer = script[script.index("umask 077\n{"):script.index("# Strict production firewall:")]
    # The writer runs in a disposable directory, before any apt, Docker, or UFW step.
    inputs = {name: "value" for name in (
        "APP_SECRET", "DB_PASSWORD", "SUPPORT_PRO_DB_PASSWORD", "SUPPORT_PRO_SSO_SECRET",
        "SUPPORT_PRO_SESSION_SECRET", "SUPPORT_PRO_ADMIN_PASSWORD", "API_DOMAIN",
        "ADMIN_DOMAIN", "APP_DOMAIN", "CABINET_DOMAIN", "SUPPORT_PRO_DOMAIN",
        "ADMIN_EMAIL", "ADMIN_PASSWORD", "BOT_TOKEN", "BOT_USERNAME", "ADMIN_TELEGRAM_ID",
        "REMNAWAVE_URL", "REMNAWAVE_TOKEN", "YOOKASSA_SHOP_ID", "YOOKASSA_SECRET_KEY",
        "PLATEGA_MERCHANT_ID", "PLATEGA_SECRET", "PLATEGA_REFUND_URL",
        "ROLLYPAY_API_KEY", "ROLLYPAY_SIGNING_SECRET", "ROLLYPAY_REFUND_URL",
        "DEFAULT_CURRENCY", "DEFAULT_LANGUAGE", "TZ_VALUE", "PRICE_1", "PRICE_3",
        "PRICE_6", "PRICE_12", "AUTO_RENEW_ENABLED", "AUTO_RENEW_LEAD_DAYS",
        "REQUIRED_TELEGRAM_CHANNEL", "ALERT_TELEGRAM_CHAT_ID", "REFERRAL_REWARD_PERCENT",
        "NOTIFICATION_EXPIRY_DAYS", "CADDY_EMAIL", "WEBHOOK_DOMAIN", "MINIAPP_DOMAIN",
        "BOT_DOMAIN", "PANEL_DOMAIN", "YANDEX_CLIENT_ID", "YANDEX_CLIENT_SECRET",
        "VK_CLIENT_ID", "VK_CLIENT_SECRET", "PAYMENTS_SANDBOX", "TRIAL_MAX_DAYS",
        "S3_ENDPOINT_URL", "S3_BUCKET", "S3_REGION", "S3_ACCESS_KEY", "S3_SECRET_KEY",
            "INSTALLER_VERSION", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM",
    )}
    inputs.update(API_DOMAIN="api.example.com", ADMIN_DOMAIN="admin.example.com",
                  CABINET_DOMAIN="cabinet.example.com", SUPPORT_PRO_DOMAIN="support.example.com",
                  BOT_TOKEN="a'long$token", YOOKASSA_SECRET_KEY="configured-key")
    (tmp_path / "support-pro").mkdir()
    env = {**os.environ, **inputs}
    env.pop("SUPPORT_REDIS_PASSWORD", None)
    generation = 'SUPPORT_REDIS_PASSWORD="$(openssl rand -hex 32)"\n'
    bridge_generation = 'SUPPORT_BRIDGE_TOKEN="$(openssl rand -hex 32)"\n'
    assert bridge_generation in script[:script.index("umask 077\n{")]
    assert generation in script[:script.index("umask 077\n{")]
    run = subprocess.run(["bash", "-c", "set -Eeuo pipefail\ndie(){ echo \"$*\" >&2; exit 1; }\n" + functions + generation + bridge_generation + writer],
                         cwd=tmp_path, env=env, text=True, capture_output=True)
    assert run.returncode == 0, run.stderr
    shop = (tmp_path / ".env").read_text()
    support = (tmp_path / "support-pro/.env").read_text()
    assert "SUPPORT_PRO_DB_PASSWORD='value'" in shop
    assert "SUPPORT_PRO_SSO_SECRET='value'" in shop
    assert "SUPPORT_PRO_DOMAIN='support.example.com'" in shop
    assert "ADMIN_CORS_ORIGINS='https://admin.example.com'" in shop
    assert "CABINET_CORS_ORIGINS='https://cabinet.example.com'" in shop
    assert "YOOKASSA_SECRET_KEY='configured-key'" in shop
    assert "BOT_TOKEN='a\\'long$token'" in shop
    assert "SESSION_SECRET='value'" in support
    assert "PUBLIC_ORIGIN='https://support.example.com'" in support
    support_redis = next(line.split("=", 1)[1] for line in shop.splitlines() if line.startswith("SUPPORT_REDIS_PASSWORD="))
    assert len(support_redis) == 66  # 64 hex digits enclosed in quotes
    assert f"REDIS_PASSWORD={support_redis}" in support.splitlines()
    bridge_token = next(line.split("=",1)[1] for line in shop.splitlines() if line.startswith("SUPPORT_BRIDGE_TOKEN="))
    assert len(bridge_token)==66 and f"SHOP_BRIDGE_TOKEN={bridge_token}" in support.splitlines()
    assert "SHOP_BRIDGE_URL='https://api.example.com'" in support
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "support-pro/.env").stat().st_mode & 0o777 == 0o600


def test_failed_database_dump_cancels_update_before_copy(tmp_path):
    (tmp_path / ".env").write_text("APP_ENV=production\n")
    (tmp_path / "marker").write_text("unchanged")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker = fakebin / "docker"
    docker.write_text("#!/bin/sh\ncase \"$*\" in *'up -d db'*) exit 0;; *'exec -T db pg_dump'*) exit 1;; esac\nexit 0\n")
    docker.chmod(0o755)
    run = subprocess.run(["bash", str(ROOT / "scripts/update.sh")], cwd=tmp_path,
                         env={**os.environ, "APP_DIR": str(tmp_path), "PATH": f"{fakebin}:{os.environ['PATH']}"},
                         text=True, capture_output=True)
    assert run.returncode != 0
    assert "dump failed" in run.stderr
    assert (tmp_path / "marker").read_text() == "unchanged"


def test_release_asset_names_match_distribution_manifest():
    import json
    manifest = json.loads((ROOT / "release-manifest.template.json").read_text())
    tag = manifest["distribution_tag"]
    name = f"remnawave_vpn_shop_{tag.replace('.', '_')}_full_release.zip"
    assert manifest["artifact"] == name
    assert manifest["detached_manifest"] == name.removesuffix(".zip") + "_manifest.json"
    workflow = (ROOT / ".github/workflows/publish-release.yml").read_text()
    assert "package-distribution.py" in workflow
    assert "publish-github-release.cjs" in workflow
    assert "remnawave_vpn_shop_v20_0_15_full_release.zip" not in workflow
