"""v28.86.0: the cabinet's «Приложения» block — not on the sign-in and registration pages, only for a signed-in
customer, and switched on or off in the admin panel («Приложения → Блок «Приложения» в личном кабинете»)."""
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import main as app_main
from app import mobile_catalog
from app.models import Base

ROOT = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    audits = []

    async def audit(db, action, actor, target=None, details=None):
        audits.append((action, details))
    monkeypatch.setattr(app_main, "audit", audit)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.audits = audits
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_switch_is_on_by_default_and_saved_from_the_admin_panel(db):
    admin = type("A", (), {"email": "boss@example.com"})()
    assert (await mobile_catalog.public_apps(db))["cabinet_visible"] is True
    cards = [mobile_catalog.AppCardIn(**{k: v for k, v in c.items() if k in mobile_catalog.AppCardIn.model_fields})
             for c in mobile_catalog.parse_catalog(None)]
    saved = await mobile_catalog.save_apps(mobile_catalog.AppsIn(apps=cards, cabinet_visible=False), db, admin)
    assert saved["cabinet_visible"] is False
    assert (await mobile_catalog.public_apps(db))["cabinet_visible"] is False
    assert db.audits[-1] == ("content.apps.updated", {"cabinet_visible": False})
    # Saving the cards without the switch keeps it as it was.
    await mobile_catalog.save_apps(mobile_catalog.AppsIn(apps=cards), db, admin)
    assert (await mobile_catalog.public_apps(db))["cabinet_visible"] is False
    await mobile_catalog.save_apps(mobile_catalog.AppsIn(apps=cards, cabinet_visible=True), db, admin)
    assert (await mobile_catalog.admin_apps(db, admin))["cabinet_visible"] is True


def test_cabinet_shows_the_block_only_after_sign_in_and_when_switched_on():
    cabinet = (ROOT / "cabinet/src/main.tsx").read_text()
    assert "{!authed && <AppsNotice" not in cabinet, "no «Приложения» block on the sign-in and registration pages"
    assert "{appsVisible && <AppsNotice apps={shopApps} lang={lang} />}" in cabinet
    assert "setAppsVisible(apps?.cabinet_visible !== false)" in cabinet
    admin = (ROOT / "admin/src/main.tsx").read_text()
    assert "cabinet_visible:cabinetVisible" in admin and "Показывать покупателю после входа" in admin
