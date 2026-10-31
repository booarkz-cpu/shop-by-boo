"""Every URL the clients call must be answered by a route.

A screen that asks for a path the backend does not serve is exactly the «мёртвый раздел» symptom: the
panel shows a spinner, then an error, and nothing explains that the URL simply does not exist. The checks
below read the real sources of the three clients and match each URL against the assembled route table,
so removing a route or mistyping a URL in a client fails here instead of in production.
"""
from pathlib import Path

import pytest

from app_contract import client_api_paths, serves_path

ROOT = Path(__file__).resolve().parents[1]


def _source(*relative: str) -> str:
    """Text of the given files, or of every TypeScript source under the given directories."""
    chunks: list[str] = []
    for entry in relative:
        target = ROOT / entry
        if target.is_dir():
            chunks.extend(path.read_text(encoding="utf-8") for path in sorted(target.rglob("*.ts*"))
                          if ".test." not in path.name)
        else:
            chunks.append(target.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _unserved(entry: str) -> list[str]:
    return sorted(url for url in client_api_paths(_source(entry)) if not serves_path(url))


def test_admin_panel_only_calls_routes_that_exist():
    """Every ``/api/…`` the admin panel requests is served, parameters included."""
    missing = _unserved("admin/src")
    assert not missing, "the panel calls these paths but the API does not serve them: " + ", ".join(missing)


def test_cabinet_only_calls_routes_that_exist():
    """The cabinet and the Telegram Mini App share these sources."""
    missing = _unserved("cabinet/src")
    assert not missing, "the cabinet calls these paths but the API does not serve them: " + ", ".join(missing)


@pytest.mark.parametrize("surface", ["mobile/android-admin", "mobile/android-user", "mobile/ios-admin", "mobile/ios-user"])
def test_mobile_apps_only_call_routes_that_exist(surface):
    """The Kotlin and Swift clients are held to the same contract as the web surfaces."""
    files = sorted(path for path in (ROOT / surface).rglob("*") if path.suffix in {".kt", ".swift"})
    assert files, f"{surface}: no sources found"
    missing = sorted({url for path in files for url in client_api_paths(path.read_text(encoding="utf-8"))
                      if not serves_path(url)})
    assert not missing, f"{surface} calls these paths but the API does not serve them: " + ", ".join(missing)


def test_the_contract_helper_recognises_parameters_and_rejects_unknown_paths():
    """Guard the guard: the matcher must accept a parameterised route and refuse an invented one."""
    assert serves_path("/api/admin/payments/42"), "a parameterised route answers a concrete id"
    assert serves_path("/api/admin/plans"), "a plain route answers itself"
    assert not serves_path("/api/admin/a-route-that-does-not-exist")
    assert client_api_paths('req("/api/admin/plans")', "req(`/api/me/devices/${id}/revoke`)") == {"/api/admin/plans"}, \
        "a plain URL is checked; a prefix the client completes at runtime is not a URL yet"
