"""Customer profile: display name and the list of linked sign-in methods.

Only the display name is editable here. E-mail, password and provider links keep
their dedicated verified flows (account recovery, OAuth, passkeys, merge).
"""
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import CustomerPasskey, User

router = APIRouter(tags=["customer-profile"])


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=2, max_length=64)

    @field_validator("username")
    @classmethod
    def clean(cls, value: str) -> str:
        value = unicodedata.normalize("NFC", value).strip()
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Имя должно содержать минимум 2 символа")
        # Control, format (bidi overrides, zero-width) and private-use characters can spoof names in the admin desk.
        if any(unicodedata.category(ch) in {"Cc", "Cf", "Co", "Cs"} for ch in value):
            raise ValueError("Имя содержит недопустимые символы")
        return value


async def _payload(db: AsyncSession, user: User) -> dict:
    passkeys = int(await db.scalar(select(func.count()).select_from(CustomerPasskey).where(CustomerPasskey.user_id == user.id)) or 0)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "email_verified": user.email_verified_at is not None,
        "referral_code": user.referral_code,
        "created_at": user.created_at,
        "providers": {
            "email": bool(user.email and user.email_password_hash),
            "telegram": user.telegram_id is not None,
            "yandex": bool(user.yandex_id),
            "vk": bool(user.vk_id),
            "passkey": passkeys > 0,
        },
    }


@router.get("/api/me/profile")
async def my_profile(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token

    user = await user_from_token(request, db)
    return await _payload(db, user)


@router.patch("/api/me/profile")
async def update_profile(payload: ProfileIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import audit, user_from_token

    user = await user_from_token(request, db)
    if user.restricted_at is not None:
        raise HTTPException(403, "Доступ к изменению профиля ограничен")
    before = user.username
    if before != payload.username:
        user.username = payload.username
        await audit(db, "customer.profile.updated", f"user:{user.id}", str(user.id), {"field": "username"})
        await db.commit()
        await db.refresh(user)
    return await _payload(db, user)
