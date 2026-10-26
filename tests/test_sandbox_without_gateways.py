"""Contracts for gateway-free checkout and the production sandbox ban."""
from main_source import main_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sandbox_is_refused_in_production_and_works_without_gateways():
    mode = (ROOT / "backend/app/sandbox_mode.py").read_text()
    main = main_source()
    payments = (ROOT / "backend/app/payments.py").read_text()
    cabinet = (ROOT / "backend/app/cabinet_api.py").read_text()
    bot = (ROOT / "backend/app/bot.py").read_text()
    assert "SANDBOX_ENVS" in mode
    assert '"production"' not in mode.split("SANDBOX_ENVS", 1)[1].split(")", 1)[0]
    assert "PAYMENTS_SANDBOX is allowed only when APP_ENV is development, test, or staging" in main
    assert "sandbox_checkout_requested" in main
    assert "sandbox_local_vpn" in main
    assert "sandbox://local/" in main
    assert "Тестовый месяц" in main
    assert 'event_id = data.get("event")' not in payments
    assert "Invalid RollyPay signature or timestamp" in payments
    assert "payments_sandbox_allowed" in payments
    assert "payments_sandbox_allowed" in cabinet
    assert "Telegram polling stays idle outside production" in bot
    assert (ROOT / "docker-compose.test.yml").is_file()
    assert (ROOT / "scripts/test-up.sh").is_file()
    assert "PAYMENTS_SANDBOX=true" in (ROOT / ".env.test.example").read_text()
    assert "APP_ENV=development" in (ROOT / ".env.test.example").read_text()
    compose = (ROOT / "docker-compose.test.yml").read_text()
    opener = (ROOT / "scripts/open-ports.sh").read_text()
    installer = (ROOT / "deploy/install-vps.sh").read_text()
    assert '"127.0.0.1:18080:8000"' in compose
    assert '"127.0.0.1:18081:80"' in compose
    assert "--env-file .env.test" in (ROOT / "scripts/test-up.sh").read_text()
    assert "open-ports.sh" in installer
    assert "ufw allow 80/tcp" in installer
    assert "18080:18083/tcp" in opener
    assert "443/udp" in opener
    assert "8000/tcp" not in opener
    assert "8000/tcp" not in installer
