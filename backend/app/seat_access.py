"""Access of a seat in someone else's subscription: family members and company employees (v28.59.0).

Family plans (``growth.py``) and corporate seats (``corporate.py``) give a person their own Remnawave
user whose term, traffic, devices and squad follow the owner. Both modules carried the same two
blocks of panel calls; a fix in one (for example, entitlements following a plan change) had to be
copied to the other by hand. Here they are written once:

* :func:`end_seat` — the seat is lost: the panel user is switched off and the subscription ends now;
* :func:`grant_seat` — the seat is held: the panel user is created on first use, otherwise switched
  back on, moved to the owner's expiry and given the owner's entitlements when they changed.

Purchases, renewals and gifts of a customer's own subscription go through ``payments_api`` and
``gift_orders`` (``extend_idempotent``); seats never extend — they copy the owner's expiry.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Subscription, User


def seat_username(user_id: int, subscription_id: int) -> str:
    """Panel username of a seat: separate from the person's own ``user_<id>`` subscription."""
    return f"user_{user_id}_sub_{subscription_id}"


async def end_seat(rw, sub: Subscription, now: datetime) -> None:
    if sub.remnawave_user_id and sub.lifecycle_status != "expired":
        await rw.disable_user(sub.remnawave_user_id)
    sub.lifecycle_status, sub.expires_at = "expired", min(sub.expires_at or now, now)


async def grant_seat(db: AsyncSession, rw, sub: Subscription, *, user_id: int, plan_id: int, target: datetime,
                     traffic_gb: int | None, devices: int | None, profile: str | None) -> str:
    """Make the seat's panel user follow the owner. Returns ``created`` or ``updated``."""
    if not sub.remnawave_user_id:
        user = await db.get(User, user_id)
        data = await rw.create_user(seat_username(user_id, sub.id), target, int(traffic_gb) * 1024 ** 3 if traffic_gb else 0,
                                    active_internal_squads=[profile] if profile else None,
                                    telegram_id=user.telegram_id if user else None, device_limit=devices)
        if not data or not data.get("id"):
            raise RuntimeError("Remnawave returned no user id")
        # Remnawave 3.x addresses users by the numeric id (the column keeps its historical name).
        sub.remnawave_user_id = str(data["id"])
        sub.subscription_url = data.get("subscriptionUrl") or data.get("subscription_url")
        result = "created"
    else:
        if sub.lifecycle_status == "expired":
            await rw.enable_user(sub.remnawave_user_id)
        if not sub.expires_at or abs((sub.expires_at - target).total_seconds()) > 60:
            await rw.patch_user(sub.remnawave_user_id, {"expireAt": target.isoformat()})
        if (sub.traffic_limit_gb_snapshot, sub.device_limit_snapshot, sub.remnawave_profile_id_snapshot) != (traffic_gb, devices, profile):
            # The owner changed plan: traffic, devices and squad follow, not only the expiry.
            await rw.update_entitlements(sub.remnawave_user_id, traffic_gb, profile, device_limit=devices)
        result = "updated"
    sub.expires_at, sub.lifecycle_status, sub.plan_id = target, "active", plan_id
    sub.traffic_limit_gb_snapshot, sub.device_limit_snapshot, sub.remnawave_profile_id_snapshot = traffic_gb, devices, profile
    return result
