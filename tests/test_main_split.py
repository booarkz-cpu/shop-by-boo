"""v28.28.0: sections moved out of main.py keep their routes and stay visible to source checks."""
import ast
import importlib

from main_source import APP, MODULES, main_source

from app import main as shop


def test_moved_sections_are_imported_by_main_and_keep_their_routes():
    assert MODULES == ["payments_api", "customer_ops_api", "notifications_status_api", "recovery_api", "operations_api", "admin_api", "staging_e2e_api",
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
    # v28.31.0: recovery, refunds and withdrawals moved to recovery_api.py;
    # v28.32.0: checkout, webhooks, fulfillment and provisioning moved to payments_api.py
    assert len((APP / "main.py").read_text().splitlines()) < 2000
