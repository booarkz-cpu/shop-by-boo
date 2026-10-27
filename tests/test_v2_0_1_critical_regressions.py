from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _route(path: str):
    from app import main as shop

    return next(r for r in shop.app.routes if getattr(r, "path", "") == path and "POST" in getattr(r, "methods", set()))


def test_telegram_login_declares_request_dependency():
    # FastAPI injects the Request (client IP and user agent of the session) into the handler.
    assert _route("/api/auth/telegram").dependant.request_param_name == "request"


def test_yandex_exchange_declares_request_dependency():
    assert _route("/api/auth/exchange").dependant.request_param_name == "request"


def test_release_scripts_are_executable():
    for rel in ("install.sh", "scripts/build-release.sh", "scripts/staging-e2e.sh"):
        assert (ROOT / rel).stat().st_mode & 0o111, rel
