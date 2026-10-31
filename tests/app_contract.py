"""What the running application exposes, read from the application itself rather than from its source text.

Tests that used to search main.py for ``@app.get("/api/...")`` or ``class Model`` ask these helpers instead:
the route table of the assembled FastAPI app, the SQLAlchemy metadata and the Alembic revision graph.
Moving code between modules or reformatting it no longer breaks them; removing a route or a table does.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _flat(items, prefix=""):
    """Routes of the app with included routers opened up (FastAPI keeps them as ``_IncludedRouter``)."""
    for route in items:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            context = getattr(route, "include_context", None)
            yield from _flat(inner.routes, prefix + (getattr(context, "prefix", "") or ""))
        elif getattr(route, "path", None) is not None:
            yield prefix + route.path, route


def all_routes():
    from app import main

    return list(_flat(main.app.routes))


@lru_cache(maxsize=1)
def routes() -> frozenset[tuple[str, str]]:
    """Every (METHOD, path) the shop API serves, including routers mounted by modules."""
    out = set()
    for path, route in all_routes():
        for method in getattr(route, "methods", None) or ():
            out.add((method, path))
    return frozenset(out)


def has_route(method: str, path: str) -> bool:
    return (method.upper(), path) in routes()


def missing_routes(*pairs: str) -> list[str]:
    """``missing_routes("GET /api/me", "POST /api/x")`` -> the pairs the app does not serve."""
    return [p for p in pairs if not has_route(*p.split(" ", 1))]


def endpoint(method: str, path: str):
    """The function that serves a route (to call it directly or inspect its dependencies)."""
    for full, route in all_routes():
        if full == path and method.upper() in (getattr(route, "methods", None) or ()):
            return route.endpoint
    raise LookupError(f"{method} {path}")


def permissions(method: str, path: str) -> set[str]:
    """Permissions required by ``require_permission(...)`` dependencies of a route."""
    found: set[str] = set()
    for full, route in all_routes():
        if full != path or method.upper() not in (getattr(route, "methods", None) or ()):
            continue
        stack = list(route.dependant.dependencies)
        while stack:
            dep = stack.pop()
            perm = getattr(dep.call, "required_permission", None)
            if perm:
                found.add(perm)
            stack.extend(dep.dependencies)
    return found


def tables() -> dict:
    from app.models import Base

    return Base.metadata.tables


def columns(table: str) -> set[str]:
    return {c.name for c in tables()[table].columns}


@lru_cache(maxsize=1)
def _scripts():
    from alembic.script import ScriptDirectory

    return ScriptDirectory(str(ROOT / "backend/alembic"))


def revision(rev: str):
    """The Alembic revision object (``.revision``, ``.down_revision``)."""
    return _scripts().get_revision(rev)


def migration_head() -> str:
    return _scripts().get_current_head()


def env_names() -> set[str]:
    """Environment variables the shop settings read (field aliases of ``Settings``)."""
    from app.config import Settings

    return {f.alias or name.upper() for name, f in Settings.model_fields.items()}


def missing_paths(*paths: str) -> list[str]:
    """Paths the app serves under no method at all."""
    served = {p for _, p in routes()}
    return [p for p in paths if p not in served]


@lru_cache(maxsize=1)
def _path_matchers():
    """One regular expression per served path, with ``{param}`` turned into a single segment."""
    import re

    return tuple(re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "$") for path in {p for _, p in routes()})


def serves_path(path: str) -> bool:
    """True when *path* — a concrete URL a client would call — is answered by a route, parameter or not.

    ``serves_path("/api/admin/payments/42")`` is True because ``/api/admin/payments/{payment_id}`` exists.
    Frontend tests use it to prove that a URL the panel or the apps call is not a dead end.
    """
    path = path.split("?", 1)[0].split("#", 1)[0]
    return any(matcher.match(path) for matcher in _path_matchers())


def client_api_paths(*sources: str) -> set[str]:
    """``/api/…`` URLs that appear in frontend or app sources, with template holes removed.

    Client code interpolates ids (``/api/me/devices/${id}/revoke``); everything up to the first
    interpolation or query mark is kept, and the rest is matched by :func:`serves_path` against the
    route templates.
    """
    import re

    found: set[str] = set()
    for text in sources:
        # ``const ROOT = "/api/admin/x"`` is a base the client concatenates onto, not a request target.
        text = re.sub(r"\b(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*[\"'][^\"']*[\"']", "", text)
        for literal in re.findall(r"""["'`](/api/[^"'`]*)""", text):
            head = re.split(r"[$`?\"']", literal, maxsplit=1)[0]
            # A literal ending in ``/`` is a prefix the client completes at runtime (``/api/admin/`` + id);
            # there is no URL to check until the id is known, so it is skipped rather than reported.
            if not head.startswith("/api/") or head.endswith("/") or {"(", ")", "["}.intersection(head):
                continue
            found.add(head)
    return found
