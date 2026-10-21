"""Customer profile: editable display name, linked providers and spoofing guards."""
from datetime import datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app import customer_profile as profile
from app.models import AuditLog, CustomerPasskey, User
from test_subscription_commerce import database, request


@pytest.mark.asyncio
async def test_profile_lists_linked_sign_in_methods(database):
    user = await database.get(User, 1)
    user.email = "owner@example.test"
    user.email_password_hash = "hash"
    user.telegram_id = 42
    database.add(CustomerPasskey(user_id=1, credential_id="cred-1", public_key="pk", sign_count=0, name="Phone"))
    await database.commit()

    data = await profile.my_profile(request(), database)

    assert data["username"] == "Owner"
    assert data["email"] == "owner@example.test"
    assert data["email_verified"] is False
    assert data["providers"] == {"email": True, "telegram": True, "yandex": False, "vk": False, "passkey": True}


@pytest.mark.asyncio
async def test_display_name_is_normalised_saved_and_audited_once(database):
    data = await profile.update_profile(profile.ProfileIn(username="  Browser   Customer "), request(), database)
    assert data["username"] == "Browser Customer"
    assert (await database.get(User, 1)).username == "Browser Customer"

    await profile.update_profile(profile.ProfileIn(username="Browser Customer"), request(), database)
    events = (await database.execute(select(AuditLog).where(AuditLog.action == "customer.profile.updated"))).scalars().all()
    assert len(events) == 1
    assert "Browser" not in str(events[0].details)


@pytest.mark.parametrize("value", ["a", "   ", "evil\u202eadmin", "zero\u200bwidth", "bell\x07name", "x" * 65])
def test_display_name_rejects_short_spoofing_and_control_characters(value):
    with pytest.raises(ValidationError):
        profile.ProfileIn(username=value)


def test_profile_payload_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        profile.ProfileIn(username="Valid", email="other@example.test")


@pytest.mark.asyncio
async def test_restricted_customer_cannot_rename(database):
    user = await database.get(User, 1)
    user.restricted_at = datetime.utcnow()
    await database.commit()
    with pytest.raises(HTTPException) as error:
        await profile.update_profile(profile.ProfileIn(username="New name"), request(), database)
    assert error.value.status_code == 403
    assert (await database.get(User, 1)).username == "Owner"
