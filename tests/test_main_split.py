"""v28.28.0: sections moved out of main.py keep their routes and stay visible to source checks."""
import ast
import importlib

from main_source import APP, MODULES, main_source

from app import main as shop


def test_moved_sections_are_imported_by_main_and_keep_their_routes():
    assert MODULES == ["auth_api", "admin_auth_api", "payments_api", "customer_ops_api", "notifications_status_api", "recovery_api", "operations_api", "admin_api", "staging_e2e_api",
                       "backups_api", "content_branding_api", "marketing_api", "enterprise_api", "payment_platform_api"]
    names = {getattr(r, "endpoint", None).__name__ for r in shop.app.routes if getattr(r, "endpoint", None)}
    for name in MODULES:
        module = importlib.import_module(f"app.{name}")
        assert module.__all__, name
        for exported in module.__all__:
            # main re-exports every moved name, so app.main.<name> and patches on it keep working
            assert getattr(shop, exported) is getattr(module, exported), (name, exported)
        endpoints = [n for n in module.__all__ if getattr(getattr(module, n), "__module__", "") == module.__name__ and n in names]
        assert endpoints, f"{name} registers no routes"
    assert len(shop.app.routes) >= 291  # 291 at the split; later releases add routers


def test_main_source_is_one_parseable_text_again():
    text = main_source()
    tree = ast.parse(text)
    defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    assert {"backup_scheduler", "monitor_checks_scheduler", "_validate_tar_safety", "fulfill"} <= defined
    assert "shop." not in text
    assert {"telegram_user_from_init_data", "user_from_token", "admin_login", "mfa_enable"} <= defined
    # v28.31.0: recovery, refunds and withdrawals moved to recovery_api.py;
    # v28.32.0: checkout, webhooks, fulfillment and provisioning moved to payments_api.py
    # v28.33.0: customer and admin sign-in moved to auth_api.py and admin_auth_api.py
    assert len((APP / "main.py").read_text().splitlines()) < 1800


def test_a_moved_module_imported_before_main_still_fills_main():
    """``from app import admin_auth_api`` as the very first import loads main from inside it;
    main's star import then sees a half-loaded module, so the module hands its names over."""
    import subprocess
    import sys

    code = ("import app.admin_auth_api, app.auth_api, app.main as shop;"
            "missing=[n for m in (app.admin_auth_api, app.auth_api) for n in m.__all__ if getattr(shop, n, None) is not getattr(m, n)];"
            "print(missing); raise SystemExit(1 if missing else 0)")
    done = subprocess.run([sys.executable, "-c", code], cwd=APP.parent, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr[-2000:]
