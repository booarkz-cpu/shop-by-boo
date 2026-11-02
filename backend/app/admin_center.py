"""Admin Control Center: the 30 modules of the master task mapped to the admin panel (v28.60.0, stage 6).

Each module names the panel sections (``tab`` of ``admin/src/sections.ts``) that manage it and the API
prefixes behind them. What the module can do is not written by hand: it is read from the routes of the
application — HTTP methods give read / create / update / delete, query parameters give search and
filters, the dependencies give the permissions, and the handlers show whether a change is written to
the audit log. A module without a section says so and names the stage that adds it, instead of showing
a switch that does nothing.

``GET /api/admin/control-center`` feeds «Система → Админ-центр»; ``scripts/generate-admin-matrix.py``
writes the same data to ``docs/ru/new/ADMIN_CONTROL_MATRIX.md``. ``GET /api/admin/roles`` shows which
role holds which permission (roles are defined in ``security.PERMISSIONS``).
"""
from __future__ import annotations

import inspect
import re
from functools import lru_cache

from fastapi import APIRouter, Depends

from .security import PERMISSIONS, require_permission

router = APIRouter()

# (number, module, panel sections, API prefixes under /api/admin/, stage that adds a missing module)
MODULES: tuple[tuple[int, str, tuple[str, ...], tuple[str, ...], str], ...] = (
    (1, "Dashboard", ("dashboard", "command360"), ("overview", "v6", "analytics"), ""),
    (2, "Users", ("crm", "customer360", "users"), ("users", "customers", "remnawave", "customer-operations"), ""),
    (3, "Subscriptions", ("subscriptionOperations",), ("subscription-operations", "freeze", "grace", "dunning", "first-connect"), ""),
    (4, "Tariffs", ("plans", "constructor", "trafficPackages"), ("plans", "tariff-constructors", "traffic-packages", "pricing"), ""),
    (5, "Devices", ("devices",), ("anti-sharing", "wg-pool"), ""),
    (6, "Payments", ("payments", "providers", "refunds", "staging"), ("payments", "refunds", "gateways", "payment", "staging-e2e"), ""),
    (7, "Finance", ("financial", "fiscal"), ("financial-ledger", "fiscal", "pnl", "daily-billing"), ""),
    (8, "Promo Codes", ("marketing", "offers"), ("promo-codes", "promotions", "promo-groups", "promo-audiences", "personal-offers"), ""),
    (9, "Gifts", ("gifts",), ("gifts", "gift-batches"), ""),
    (10, "Referrals", ("payouts",), ("referrals", "referral-contests", "payouts"), ""),
    (11, "Remnawave", ("remnawave", "nodes"), ("panel", "panel-guard", "panel-changes", "panel-api-stats", "remnawave"), ""),
    (12, "Installation", (), (), "этап 10: Installation Wizard"),
    (13, "Servers", ("nodes", "capacity", "orchestrator"), ("nodes", "provision-node"), ""),
    (14, "Nodes", ("nodes", "nodeTerminal", "torrents"), ("nodes", "terminal", "platform"), ""),
    (15, "Domains", (), (), "этап 11: менеджер доменов"),
    (16, "Certificates", (), (), "этап 11: сертификаты"),
    (17, "Reverse Proxy", (), (), "этап 11: Reverse Proxy (общий Caddy)"),
    (18, "Subscription Portal", ("subscriptionPortal",), ("sub-proxy",), ""),
    (19, "Node Extensions", (), (), "этап 12: менеджер расширений Remnawave"),
    (20, "Monitoring", ("monitoring", "health", "opsReadiness", "incidents", "availability"), ("monitoring", "ops", "block-monitor", "health", "integrity", "status"), ""),
    (21, "Backups", ("backups", "recovery"), ("backups", "recovery"), ""),
    (22, "Updates", ("releases", "deployments"), ("releases", "auto-update", "deployments"), ""),
    (23, "Automation", ("automation", "jobs", "workers"), ("automation", "jobs", "workers"), ""),
    (24, "Telegram", ("content", "menuTree", "botBanners", "documents"), ("bot", "menu", "info-pages", "broadcasts", "channels", "pinned-message"), ""),
    (25, "Integrations", ("integrations", "mailDomain"), ("webhooks", "mail", "ads", "ripe-atlas", "geoip"), ""),
    (26, "Plugins", ("plugins",), ("plugins",), ""),
    (27, "Security", ("security", "passkeys", "admins", "sessions", "fraud"), ("security", "admins", "sessions", "fraud", "roles"), ""),
    (28, "Logs", ("audit", "events"), ("audit", "errors"), ""),
    (29, "GitHub", ("releases",), ("github-update", "auto-update"), ""),
    (30, "Settings", ("runtimeSettings", "features", "branding"), ("runtime-settings", "settings", "branding"), ""),
)

SEARCH_PARAMS = re.compile(r"^(q|query|search|status|kind|actor|action|target|since|until|provider|user_id|telegram_id|plan_id|from|to|days|state|filter)$")
SETTINGS_PATH = re.compile(r"config|settings|rules|threshold|schedule|style|layout")
DIAGNOSTIC_PATH = re.compile(r"test|check|health|diagnos|verify|probe|status|readiness|validate|preview")


def _walk(routes, prefix=""):
    from fastapi.routing import APIRoute
    for route in routes:
        if hasattr(route, "original_router"):
            yield from _walk(route.original_router.routes, prefix + route.include_context.prefix)
        elif isinstance(route, APIRoute):
            yield route, prefix + route.path


def _permissions(dependant):
    for dep in dependant.dependencies:
        name = getattr(dep.call, "required_permission", None)
        if name:
            yield name
        yield from _permissions(dep)


def _writes_audit(endpoint) -> bool:
    try:
        return "audit(" in inspect.getsource(endpoint)
    except (OSError, TypeError):
        return False


@lru_cache(maxsize=1)
def matrix() -> list[dict]:
    """The modules with the operations their API offers (computed once per process)."""
    from .main import app
    routes = [(route, path) for route, path in _walk(app.routes) if path.startswith("/api/admin/")]
    out = []
    for number, name, tabs, prefixes, missing in MODULES:
        mine = [(r, p) for r, p in routes if any(p == f"/api/admin/{x}" or p.startswith(f"/api/admin/{x}/") or p.startswith(f"/api/admin/{x}.")
                                               for x in prefixes)]
        methods = {m for r, _ in mine for m in r.methods}
        changing = [(r, p) for r, p in mine if r.methods & {"POST", "PUT", "PATCH", "DELETE"}]
        ops = {
            "read": "GET" in methods,
            "create": "POST" in methods,
            "update": bool(methods & {"PUT", "PATCH"}),
            "delete": "DELETE" in methods,
            "search": any(SEARCH_PARAMS.match(q.name) for r, _ in mine if "GET" in r.methods for q in r.dependant.query_params),
            "settings": any(SETTINGS_PATH.search(p) for _, p in mine),
            "diagnostics": any(DIAGNOSTIC_PATH.search(p) for _, p in mine),
            "audit": any(_writes_audit(r.endpoint) for r, _ in changing),
        }
        perms = sorted({x for r, _ in mine for x in _permissions(r.dependant)})
        status = "NOT_STARTED" if missing else "IMPLEMENTED"
        out.append({"number": number, "module": name, "tabs": list(tabs), "api_prefixes": list(prefixes), "routes": len(mine),
                    "operations": ops, "permissions": perms, "status": status, "missing": missing})
    return out


def outside_modules() -> dict[str, int]:
    """Administrative API prefixes that belong to none of the 30 modules (support, cabinet, apps, marketing…)."""
    from collections import Counter

    from .main import app
    prefixes = [x for *_, ps, _ in MODULES for x in ps]
    paths = {p for _, p in _walk(app.routes) if p.startswith("/api/admin/") and not p.startswith("/api/admin/auth")}
    rest = [p for p in paths if not any(p == f"/api/admin/{x}" or p.startswith(f"/api/admin/{x}/") or p.startswith(f"/api/admin/{x}.") for x in prefixes)]
    return dict(sorted(Counter(p.split("/")[3] for p in rest).items()))


@router.get("/api/admin/control-center")
async def control_center(admin=Depends(require_permission("read"))):
    return {"modules": matrix(), "note": "Операции взяты из маршрутов API; работа каждой кнопки проверяется на этапе 18."}


@router.get("/api/admin/roles")
async def roles(admin=Depends(require_permission("read"))):
    """Which role holds which permission. Roles are part of the code (``security.PERMISSIONS``); the role of
    an administrator is changed in «Роли и администраторы»."""
    from .security import PERMISSION_LABELS
    every = sorted(set().union(*PERMISSIONS.values()))
    return {"roles": [{"role": role, "permissions": sorted(perms)} for role, perms in PERMISSIONS.items()],
            "permissions": [{"key": key, "label": PERMISSION_LABELS.get(key, key)} for key in every],
            "your_role": admin.role}
