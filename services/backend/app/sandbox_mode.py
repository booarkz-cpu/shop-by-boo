"""Checkout without a live payment gateway.

Sandbox grants a local subscription only when the process is explicitly
not production. A production process refuses the flag at startup.
"""
from __future__ import annotations

from .config import settings

SANDBOX_ENVS = frozenset({"development", "dev", "test", "testing", "staging", "sandbox"})


def payments_sandbox_allowed() -> bool:
    env = (settings.app_env or "").strip().lower()
    return bool(settings.payments_sandbox) and env in SANDBOX_ENVS


def live_checkout_configured() -> bool:
    return bool(
        (settings.yookassa_shop_id and settings.yookassa_secret_key)
        or (settings.platega_merchant_id and settings.platega_secret)
        or settings.rollypay_api_key
    )


def sandbox_checkout_requested(provider: object) -> bool:
    """True when this checkout must stay on the local sandbox provider.

    An empty provider selects sandbox only when no live gateway is configured.
    A named live provider is never rewritten into sandbox.
    """
    if not payments_sandbox_allowed():
        return False
    name = str(provider or "").strip().lower()
    if name == "sandbox":
        return True
    return name in {"", "none", "auto"} and not live_checkout_configured()


def sandbox_local_vpn() -> bool:
    """Issue a local subscription URL when Remnawave is not connected."""
    return payments_sandbox_allowed() and not (
        (settings.remnawave_url or "").strip() and (settings.remnawave_token or "").strip()
    )
