"""Installer prices become starter plans (switched off) on a shop without plans."""
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import main
from app.config import settings
from app.models import Base, Plan


@pytest.mark.asyncio
async def test_starter_plans_follow_installer_prices(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(main, "payments_sandbox_allowed", lambda: False)
    monkeypatch.setattr(settings, "price_1", 250)
    monkeypatch.setattr(settings, "price_6", 0)  # an empty price is skipped
    async with AsyncSession(engine, expire_on_commit=False) as db:
        assert await main.seed_starter_plans(db) == 3
        await db.commit()
        plans = (await db.execute(select(Plan).order_by(Plan.duration_days))).scalars().all()
        assert [(p.name, int(p.price), p.duration_days, p.enabled) for p in plans] == [
            ("1 месяц", 250, 30, False), ("3 месяца", settings.price_3, 90, False), ("12 месяцев", settings.price_12, 365, False)]
        assert await main.seed_starter_plans(db) == 0  # never twice
    await engine.dispose()
