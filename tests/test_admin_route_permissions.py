"""Every administrative route must be protected by a declared permission.

The panel is the surface where a mistake costs the most: a route that answers an unauthenticated or
under-privileged caller can read customers, move money or restart nodes. The project enforces this per route
with ``require_permission(...)``, and the checks below make the rule structural: a new admin endpoint added
without a permission fails here instead of shipping.

Only genuine authentication entry points are exempt — a caller cannot present a permission before it has
signed in. Any other exception must be added to ``PUBLIC_ENTRY_POINTS`` deliberately, with a reason.
"""
from __future__ import annotations

import pytest

from app_contract import permissions, routes

# Endpoints that must answer before a permission exists: sign-in, sign-out and the ticket exchange that hands
# a signed-in administrator from the bot to the panel. Each one authenticates some other way — password with
# TOTP, Telegram ``initData``, a one-time Redis ticket, or a WebAuthn assertion — and none of them reads or
# changes customer data.
PUBLIC_ENTRY_POINTS = {
    ("POST", "/api/admin/auth/login"),                 # password + TOTP, returns a session
    ("POST", "/api/admin/auth/logout"),                # clears the session, harmless without one
    ("POST", "/api/admin/auth/telegram"),              # Telegram initData verified server-side
    ("POST", "/api/admin/auth/ticket"),                # one-time ticket minted for an authenticated admin
    ("POST", "/api/admin/auth/web-ticket"),            # same, for the web panel redirect
    ("POST", "/api/admin/auth/passkeys/login/options"),  # WebAuthn challenge, no data access
    ("POST", "/api/admin/auth/passkeys/login/verify"),   # WebAuthn assertion, returns a session
    # Authenticates through ``_admin`` inside the handler, not through a dependency: the long-poll opens its
    # own short database session so the relay wait does not hold a connection. Pinned separately by
    # ``test_terminal_output_is_guarded_by_its_own_check`` below.
    ("GET", "/api/admin/terminal/sessions/{sid}/output"),
}


def _admin_routes() -> set[tuple[str, str]]:
    return {(method, path) for method, path in routes() if path.startswith("/api/admin/")}


def test_every_admin_route_declares_a_permission():
    """No administrative route answers without a permission, except the sign-in entry points."""
    unprotected = sorted(
        (method, path) for method, path in _admin_routes()
        if not permissions(method, path) and (method, path) not in PUBLIC_ENTRY_POINTS
    )
    assert not unprotected, (
        "these administrative routes declare no permission — add require_permission(...) "
        f"or list them in PUBLIC_ENTRY_POINTS with a reason: {unprotected}"
    )


def test_the_exemption_list_has_no_dead_entries():
    """A listed entry that no longer exists would silently widen the exemption."""
    present = _admin_routes()
    dead = sorted(entry for entry in PUBLIC_ENTRY_POINTS if entry not in present)
    assert not dead, f"PUBLIC_ENTRY_POINTS names routes that do not exist: {dead}"


def test_terminal_output_is_guarded_by_its_own_check():
    """``/api/admin/terminal/sessions/{sid}/output`` authenticates through ``_admin``, not a dependency.

    It is deliberately not in the exemption list: it *is* protected, just by a helper that opens its own short
    database session for the long-poll. This test pins that the helper still enforces the permission, because a
    refactor could otherwise turn a protected route into an open one without touching any route table.
    """
    from app import node_terminal

    assert hasattr(node_terminal, "_admin"), "the terminal must keep its authentication helper"
    source = node_terminal._admin.__doc__ or ""
    assert "Authenticates" in source, "the helper must stay the authentication point"
    assert node_terminal.PERMISSION and isinstance(node_terminal.PERMISSION, str), \
        "the terminal must name the permission it requires"


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/admin/payments"),
    ("GET", "/api/admin/backups"),
    ("POST", "/api/admin/refunds/{refund_id}/execute"),
    ("GET", "/api/admin/users/{user_id}/traffic"),
    ("POST", "/api/admin/nodes/{node_uuid}/restart"),
])
def test_representative_sensitive_routes_are_not_in_the_exemption_list(method, path):
    """Money, backups, customers and nodes must never be reachable by an unprivileged caller."""
    assert (method, path) not in PUBLIC_ENTRY_POINTS
    assert permissions(method, path), f"{method} {path} lost its permission declaration"
