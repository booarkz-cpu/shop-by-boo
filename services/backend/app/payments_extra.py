"""Compatibility module: the extra gateways live in ``app.gateways`` since v28.45, one module per gateway.

Kept so existing imports (``from .payments_extra import CloudPaymentsProvider``) and the router registration in
``routers.py`` keep working; importing it registers every gateway's notification route on ``router``.
"""
from .config import settings  # noqa: F401
from .gateways import *  # noqa: F401,F403
from .gateways import GATEWAYS, common  # noqa: F401
from .gateways.common import _rsa_key, _rsa_verify, _settle, _sorted_values_hmac, _text_value, router  # noqa: F401
from .payments import PaymentError, SignatureVerificationError  # noqa: F401
