"""v28.58.0 (SEC-05): every route that changes data checks who is calling.

Administrative routes declare ``require_permission`` as a dependency. Customer routes check the
session inside the handler (``user_from_token`` and its wrappers), which a new route could forget.
This test walks all routes of the application, including routers that FastAPI includes lazily, and
fails on a POST/PUT/PATCH/DELETE route that neither has an auth dependency, nor checks a session,
signature or token in its body, nor is in the short list of routes that are public by design."""
import inspect
import re

from fastapi.routing import APIRoute

from app import main as shop

# Public by design: sign-in, registration and recovery, payment-provider webhooks (signature checked
# inside), and the mobile integrity nonce.
PUBLIC = {
    "/api/mobile/integrity/challenge",  # a one-time nonce, nothing is stored for the caller
}
# Handlers that delegate to a function which checks the session first.
DELEGATES = {
    "/api/me/gifts/purchase": "gift_orders.purchase_gift",
    "/api/me/gifts/redeem": "gift_orders.redeem_gift",
}
AUTH_IN_BODY = re.compile(
    r"user_from_token|current_user|_user\(|\buser\(request|\b_?owner\(|\bcustomer\(request|owned_partner|_admin_of\("
    r"|_authenticated\(|_probe\(|_agent|reseller_from|verify|signature|compare_digest|hmac|secret|token|_auth\b|authorize|require_|guest|private",
    re.I,
)
# Long-poll that authenticates on its own short database session (node_terminal._admin: same check as
# require_permission), so the session is not held for the 20 seconds of the wait.
ADMIN_SELF_CHECKED = {"/api/admin/terminal/sessions/{sid}/output"}
ADMIN_SIGN_IN = {"/api/admin/auth/ticket", "/api/admin/auth/passkeys/login/options", "/api/admin/auth/passkeys/login/verify",
                 "/api/admin/auth/logout", "/api/admin/auth/telegram", "/api/admin/auth/login"}


def _routes():
    def walk(routes, prefix="", extra=()):
        for route in routes:
            if hasattr(route, "original_router"):
                ctx = route.include_context
                deps = tuple(getattr(d.dependency, "__qualname__", "") for d in ctx.dependencies)
                yield from walk(route.original_router.routes, prefix + ctx.prefix, extra + deps)
            elif isinstance(route, APIRoute):
                yield route, prefix + route.path, extra

    def deps(dependant, found):
        for d in dependant.dependencies:
            found.append(getattr(d.call, "__qualname__", str(d.call)))
            deps(d, found)
        return found

    for route, path, extra in walk(shop.app.routes):
        yield path, route.methods, list(extra) + deps(route.dependant, []), route.endpoint


def test_all_routes_are_seen_including_lazily_included_routers():
    paths = {path for path, *_ in _routes()}
    assert len(paths) > 600
    assert "/api/admin/info-pages" in paths and "/api/admin/customer-operations/history/inspect" in paths


def test_administrative_routes_require_a_permission():
    missing = [path for path, methods, deps, _ in _routes()
               if path.startswith("/api/admin/") and path not in ADMIN_SIGN_IN and path != "/api/admin/auth/web-ticket" and path not in ADMIN_SELF_CHECKED
               and not any("require_permission" in d for d in deps)]
    assert missing == []


def test_changing_routes_check_the_caller():
    unchecked = []
    for path, methods, deps, endpoint in _routes():
        if not methods & {"POST", "PUT", "PATCH", "DELETE"} or path.startswith("/api/admin/"):
            continue
        if path in PUBLIC or path in DELEGATES or path.startswith(("/api/auth/", "/api/webhooks/", "/api/payments/webhooks/")):
            continue
        if any(d != "get_db" for d in deps):
            continue
        body = "\n".join(inspect.getsource(endpoint).splitlines()[:40])
        if not AUTH_IN_BODY.search(body):
            unchecked.append(path)
    assert unchecked == [], "route changes data without checking the caller: " + ", ".join(unchecked)


def test_delegated_handlers_check_the_session_first():
    from app import gift_orders
    for target in DELEGATES.values():
        fn = getattr(gift_orders, target.split(".")[1])
        assert re.search(r"user_from_token|_user\(|owner\(", "\n".join(inspect.getsource(fn).splitlines()[:6])), target


def test_self_checked_admin_route_checks_the_permission():
    from app import node_terminal
    for path in ADMIN_SELF_CHECKED:
        endpoint = next(e for p, _, _, e in _routes() if p == path)
        assert "await _admin(request, db)" in inspect.getsource(endpoint)
    assert "PERMISSIONS.get(admin.role" in inspect.getsource(node_terminal._admin)

