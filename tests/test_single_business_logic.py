"""v28.59.0 (stage 5): purchase, payment, renewal and issuance of access each live in one place.

The admin panel, the cabinet, the Mini App, the bot and the Android/iOS apps call the same API, and
that API reaches Remnawave through a short, fixed list of modules. A new module that creates or
extends panel users on its own would be a second copy of the business logic; this test names it.

* every confirmed payment of every provider goes through ``payments_api._confirm_and_fulfill_payment``;
* a customer's own subscription is created/extended in ``payments_api`` (purchase, renewal),
  ``gift_orders`` (gift codes) and, for manual grants, ``admin_api`` and ``bonus_days``;
* seats in someone else's subscription (family, company) go through ``seat_access``."""
import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "backend" / "app"

ALLOWED = {
    "create_user": {"payments_api", "gift_orders", "seat_access"},
    "extend_idempotent": {"payments_api", "gift_orders", "admin_api", "bonus_days"},
    "extend_user": set(),  # only through extend_idempotent, which checks the expiry before and after
}
FULFILMENT = "_confirm_and_fulfill_payment"


def _calls() -> dict[str, set[str]]:
    found = defaultdict(set)
    for path in ROOT.rglob("*.py"):
        if path.name == "remnawave.py":
            continue  # the client itself
        module = path.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if name in ALLOWED or name == FULFILMENT:
                    found[name].add(module)
    return found


def test_remnawave_access_is_issued_only_by_the_shared_modules():
    calls = _calls()
    for name, allowed in ALLOWED.items():
        assert calls.get(name, set()) <= allowed, f"{name} called from {sorted(calls.get(name, set()) - allowed)}"


def test_every_payment_confirmation_uses_the_one_fulfilment():
    defined = [p.name for p in ROOT.rglob("*.py") if f"def {FULFILMENT}(" in p.read_text()]
    assert defined == ["payments_api.py"]
    callers = _calls()[FULFILMENT]
    # Webhooks of the built-in providers, the shared gateway helper, reconciliation, Stars, sandbox and recovery.
    assert {"payments_api", "gateways.common", "telegram_stars", "schedulers"} <= callers


def test_family_and_company_seats_share_one_implementation():
    for module in ("growth.py", "corporate.py"):
        source = (ROOT / module).read_text()
        assert "grant_seat(" in source and "end_seat(" in source, module
        assert "create_user(" not in source and "disable_user(" not in source, module
