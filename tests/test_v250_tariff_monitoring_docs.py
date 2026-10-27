from pathlib import Path

import pytest
from fastapi import HTTPException

from app import main as shop
from app.models import TariffConstructor
from app_contract import missing_routes, revision, tables
from test_behaviour_payments_v2 import checkout
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_v250_constructor_and_server_routes_are_served():
    assert not missing_routes("GET /api/tariff-constructors", "GET /api/public/servers", "GET /api/me/servers",
                              "GET /api/admin/remnawave/monitoring")
    assert {"tariff_constructors", "tariff_constructor_options"} <= set(tables())
    rev = revision("0037_v2_5_0_tariff_constructor")
    assert rev.down_revision == "0036_v2_4_0_cabinet"
    assert shop.RATE_LIMITS["/api/public/servers"] == 30
    from app.cabinet_api import CabinetMenuIn
    assert CabinetMenuIn(title="Серверы", slug="servers", kind="servers").kind == "servers", "the cabinet can show a servers page"


def test_public_servers_never_show_node_addresses():
    from app.tariff_api import public_node
    node = {"name": "Frankfurt", "address": "203.0.113.7", "port": 443, "countryCode": "DE", "isConnected": True, "usersOnline": 4}
    shown = public_node(node)
    assert shown["status"] == "online" and shown["country"] == "DE" and shown["users_online"] == 4
    assert "203.0.113.7" not in str(shown) and "address" not in shown and "port" not in shown
    assert public_node({"name": "10.0.0.5", "isConnected": False})["name"] == "node", "a host-like name is hidden too"


@pytest.mark.asyncio
async def test_a_constructor_plan_is_not_sold_as_a_plain_plan(database, monkeypatch):
    database.add(TariffConstructor(name="Свой тариф", plan_id=1, enabled=True))
    await database.commit()

    async def yes(*a, **k):
        return True
    monkeypatch.setattr(shop, "production_payments_allowed", yes)
    monkeypatch.setattr(shop, "e2e_checkout_allowed", yes)
    with pytest.raises(HTTPException) as refused:
        await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout([(b"idempotency-key", b"k-constructor")]), database)
    assert (refused.value.status_code, refused.value.detail) == (400, "Этот тариф собирается в конструкторе")


def test_v250_frontends_expose_builder_and_servers():
    admin = (ROOT / "admin/src/main.tsx").read_text()
    cabinet = (ROOT / "cabinet/src/main.tsx").read_text()
    mini = __import__("frontend_sources").miniapp_sources()
    assert "Конструктор тарифов" in admin
    assert "Мониторинг Remnawave" in admin
    assert "TariffConstructorPanel" in admin
    assert "RemnawaveNodes" in admin
    assert "/api/admin/tariff-constructors" in admin
    assert "/api/admin/remnawave/monitoring" in admin
    assert "constructor_id" in cabinet
    assert "/api/public/servers" in cabinet
    assert "/api/me/servers" in cabinet
    assert 'kind: "servers"' in cabinet
    assert "Конструктор тарифов" in mini
    assert "/api/tariff-constructors" in mini


def test_v250_docs_are_bilingual_and_cover_sandbox():
    readme = (ROOT / "docs/archive/README_BEFORE_WORKSPACE.md").read_text()
    instruction = (ROOT / "docs/archive/INSTRUCTION_BEFORE_ALPHA_6.md").read_text()
    security = (ROOT / "docs/archive/SECURITY_BEFORE_ALPHA_6.md").read_text()
    modules = (ROOT / "docs/archive/MODULES_BEFORE_ALPHA_6.md").read_text()
    notes = (ROOT / "docs/archive/root/RELEASE_NOTES_V2_5_0.md").read_text()
    script = (ROOT / "scripts/sandbox-e2e.sh").read_text()
    assert "2.5.0" in readme
    assert "2.4.0" in readme
    assert "Конструктор тарифов" in readme
    assert "Plan builder" in readme or "tariff constructor" in readme.lower()
    assert "PAYMENTS_SANDBOX" in instruction
    assert "scripts/sandbox-e2e.sh" in instruction
    assert "9.3" in instruction
    assert "## English" in security or "# Security" in security
    assert "Конструктор" in security
    assert "не отдаёт адреса" in security or "does not return addresses" in security
    for name in ("main.py", "cabinet_api.py", "tariff_api.py", "payments.py", "remnawave.py", "worker.py"):
        assert name in modules
    assert "English" in modules
    assert "Bedolaga" in notes
    assert "/api/public/servers" in script
    assert "/api/tariff-constructors" in script
