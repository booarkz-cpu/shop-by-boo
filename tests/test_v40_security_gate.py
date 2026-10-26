from main_source import main_source
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(rel): return (ROOT/rel).read_text(encoding="utf-8")

def test_admin_frontend_identifiers_are_valid_and_staging_secret_preservation_is_supported():
    s=read("admin/src/main.tsx")
    assert "function Workers(" in s and "function Jobs(" in s
    assert "<Рабочие процессы" not in s and "<Задачаs" not in s
    assert "сохранить текущий" in s

def test_real_payments_are_open_by_default_with_an_emergency_switch():
    s=main_source()
    assert 'PRODUCTION_PAYMENTS_CLOSED_KEY="payments.real.closed"' in s
    assert 'return await setting_value(db,PRODUCTION_PAYMENTS_CLOSED_KEY,"0") != "1"' in s
    assert "Приём платежей временно остановлен администратором" in s
    assert '@app.post("/api/admin/payments/production-gate")' in s

def test_staging_internal_endpoint_is_loopback_only():
    s=main_source()
    assert 'client_host not in {"127.0.0.1","::1"}' in s

def test_admin_sessions_have_idle_timeout_and_user_agent_binding():
    s=read("backend/app/security.py")
    assert "timedelta(minutes=15)" in s
    assert "Admin session device changed" in s

def test_admin_auth_has_rate_limits_for_both_login_paths():
    s=main_source()
    assert '"/api/admin/auth/login": 8' in s and '"/api/admin/auth/telegram": 8' in s
