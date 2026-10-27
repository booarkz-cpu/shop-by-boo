from main_source import main_source
from pathlib import Path
ROOT=Path(__file__).parents[1]

def test_support_rbac_is_separated():
    from app.security import PERMISSIONS
    from app_contract import all_routes, permissions
    needed = {perm for path, route in all_routes() for method in (getattr(route, "methods", None) or ()) for perm in permissions(method, path)}
    assert {"support.read", "support.write"} <= needed, "support routes have their own read and write rights"
    assert {"support.read", "support.write"} <= PERMISSIONS["operator"]

def test_traffic_endpoint_is_user_scoped():
    m=main_source()
    start=m.index('@app.get("/api/me/traffic")')
    end=m.index('@app.get("/api/me/privacy/export")', start)
    block=m[start:end]
    assert 'user_from_token(request,db)' in block
    assert 'Subscription.user_id==user.id' in block
    assert 'SupportTicket' not in block

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
