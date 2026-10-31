import pytest
from main_source import main_source
# The shop database fixture is shared by the behaviour tests; pytest picks it up from this module's namespace.
from test_subscription_commerce import database  # noqa: F401
from pathlib import Path
ROOT=Path(__file__).parents[1]

def test_support_rbac_is_separated():
    from app.security import PERMISSIONS
    from app_contract import all_routes, permissions
    needed = {perm for path, route in all_routes() for method in (getattr(route, "methods", None) or ()) for perm in permissions(method, path)}
    assert {"support.read", "support.write"} <= needed, "support routes have their own read and write rights"
    assert {"support.read", "support.write"} <= PERMISSIONS["operator"]

def test_traffic_endpoint_is_user_scoped():
    """One handler answers /api/me/traffic, it is owner-scoped, and it is not shadowed by a second one.

    The cabinet hero and the mobile apps read ``traffic_used_bytes``/``traffic_limit_bytes``/``devices``; the
    cabinet's «Моя статистика» reads ``days``/``nodes``. The path was once registered twice — panel_usage for the
    second contract, operations_api for the first — and the loser's clients got a shape without their fields.
    """
    from app_contract import all_routes
    hits = [route for path, route in all_routes() if path == "/api/me/traffic"]
    assert len(hits) == 1, f"the path is registered {len(hits)} times: {[r.endpoint.__module__ for r in hits]}"
    assert hits[0].endpoint.__module__ == "app.panel_usage", "the breakdown and the counters live in one handler"
    source = (ROOT / "backend/app/panel_usage.py").read_text(encoding="utf-8")
    block = source[source.index('@router.get("/api/me/traffic")'):]
    assert "user_from_token(request, db)" in block, "the customer comes from the session token"
    assert "user.id" in block, "the counters are read for that customer only"
    assert "SupportTicket" not in block


def test_no_path_answers_twice():
    """A path registered in two modules silently serves only the first one; the other module's client breaks."""
    from app_contract import all_routes
    seen = {}
    for path, route in all_routes():
        for method in getattr(route, "methods", None) or ():
            seen.setdefault((method, path), []).append(route.endpoint.__module__)
    shadowed = {key: modules for key, modules in seen.items() if len(modules) > 1}
    assert not shadowed, f"these routes are registered twice: {shadowed}"


def test_openapi_operation_ids_are_unique():
    """Generated clients key on ``operationId``: one path serving GET and POST must not reuse a single id."""
    import warnings

    from app import main as shop
    shop.app.openapi_schema = None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema = shop.app.openapi()
    duplicates = [str(w.message) for w in caught if "Duplicate Operation ID" in str(w.message)]
    assert not duplicates, duplicates
    ids = [op["operationId"] for ops in schema["paths"].values() for op in ops.values()]
    assert len(ids) == len(set(ids)), "every operation id is unique"

@pytest.mark.asyncio
async def test_me_traffic_answers_both_contracts(database, monkeypatch):
    """One request must satisfy the hero counters and the per-day breakdown at the same time.

    The cabinet crashes on ``data.days.length`` when ``days`` is missing, and the mobile apps read
    ``traffic_used_bytes``/``traffic_limit_bytes``; the answer carries both sets of fields.
    """
    from starlette.requests import Request as StarletteRequest
    from app import main as shop, panel_usage

    user = await database.get(shop.User, 1)

    async def who(request, db):
        return user
    monkeypatch.setattr(shop, "user_from_token", who)

    async def stats(panel_user, days, panel=None):
        assert panel_user == "remote-1", "the panel user comes from the customer's own subscription"
        return {"range_days": 7, "days": [{"day": "2026-10-01", "bytes": 1024}], "total_bytes": 1024,
                "per_day_bytes": 1024, "peak": {"day": "2026-10-01", "bytes": 1024},
                "nodes": [{"name": "DE", "country": "DE", "bytes": 1024, "share": 100.0}]}
    monkeypatch.setattr(panel_usage, "usage", stats)
    out = await panel_usage.my_traffic(StarletteRequest({"type": "http", "headers": []}), 7, database)
    assert out["traffic_limit_bytes"] == 100 * 1024**3, "the plan limit is answered from the subscription snapshot"
    assert out["devices"] is None and out["available"] is False, "no panel client is configured in the test"
    assert out["days"] == [{"day": "2026-10-01", "bytes": 1024}] and out["range_days"] == 7
    assert out["nodes"][0]["name"] == "DE" and "country" not in out["nodes"][0], "the cabinet hides the country code"


@pytest.mark.asyncio
async def test_me_traffic_still_answers_when_the_panel_has_no_statistics(database, monkeypatch):
    """A shop whose panel does not serve /api/bandwidth-stats keeps a working cabinet: ``days`` is an empty list."""
    from starlette.requests import Request as StarletteRequest
    from app import main as shop, panel_usage

    user = await database.get(shop.User, 1)

    async def who(request, db):
        return user
    monkeypatch.setattr(shop, "user_from_token", who)

    async def broken(panel_user, days, panel=None):
        raise RuntimeError("no statistics")
    monkeypatch.setattr(panel_usage, "usage", broken)
    out = await panel_usage.my_traffic(StarletteRequest({"type": "http", "headers": []}), 30, database)
    assert out["days"] == [] and out["nodes"] == [] and out["peak"] is None
    assert out["traffic_limit_bytes"] == 100 * 1024**3


def test_worker_health_uses_worker_state_not_role_heartbeat_key():
    m=main_source()
    start=m.index('@app.get("/api/admin/system/health")')
    end=m.index('@app.get("/api/admin/analytics")', start)
    block=m[start:end]
    assert 'WorkerState' in block
    assert 'last_seen_at>=cutoff' in block
    assert 'worker_count' in block
    assert 'worker:heartbeat:{settings.worker_role}' not in block

def test_no_v33_current_release_labels():
    for rel in ['admin/src/main.tsx','deploy/install-vps.sh','scripts/build-release.sh','release-manifest.template.json']:
        text=(ROOT/rel).read_text()
        assert 'V33' not in text and 'v33' not in text and '33.0.0-production' not in text
