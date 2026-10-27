import ast
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main as shop
from app_contract import columns, missing_routes, revision, tables
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def _abuse():
    spec = importlib.util.spec_from_file_location("abuse_v260", ROOT / "backend/app/abuse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_abuse_scoring_collapses_prefixes_and_can_block():
    abuse = _abuse()
    assert abuse.source_prefix("203.0.113.10") == "203.0.113.0/24"
    assert abuse.source_prefix("2001:db8:1:2::5") == "2001:db8:1:2::/64"
    assert abuse.source_prefix("not-an-ip") is None
    now = datetime(2026, 9, 22, 12, 0, 0)
    rows = [
        {
            "ip": f"198.51.{100 + index}.1",
            "seen_at": now,
            "asn": str(index),
            "asn_org": "home",
            "user_agent": f"client-{index}",
            "hwid": f"hw-{index}",
        }
        for index in range(1, 8)
    ]
    thresholds = {
        "analyzers": {name: True for name in abuse.ANALYZERS},
        "max_concurrent_ips": 0,
        "cgnat_buffer": 0,
        "max_travel_km": 50,
        "max_accounts_per_hwid": 2,
    }
    result = abuse.score_observations(rows, device_limit=1, thresholds=thresholds, hwid_accounts=3, torrent=True)
    assert result["score"] == 100
    assert result["recommendation"] == "block"
    assert result["sources"] == 7
    names = {hit["name"] for hit in result["analyzers"]}
    assert {"temporal", "asn", "devices", "hwid", "user_agent", "torrent"} <= names
    detail = next(hit["detail"] for hit in result["analyzers"] if hit["name"] == "temporal")
    assert detail == "7 источников (7 адресов)"


def test_cgnat_buffer_and_hosting_skip():
    abuse = _abuse()
    now = datetime(2026, 9, 22, 12, 0, 0)
    later = now + timedelta(minutes=10)
    mobile = [
        {"ip": f"203.0.113.{index}", "seen_at": now, "mobile": True, "asn_org": "mobile carrier"}
        for index in range(1, 5)
    ]
    quiet = abuse.score_observations(
        mobile,
        device_limit=1,
        thresholds={"analyzers": {"temporal": True}, "cgnat_buffer": 3, "max_concurrent_ips": 0, "max_travel_km": 50},
        hwid_accounts=1,
    )
    assert quiet["score"] == 0
    hosted = [
        {"ip": "203.0.113.1", "seen_at": now, "mobile": True, "asn_org": "Hetzner Online", "lat": 55.75, "lon": 37.62},
        {"ip": "198.51.100.1", "seen_at": later, "mobile": True, "asn_org": "Hetzner Online", "lat": 1.35, "lon": 103.82},
    ]
    far = abuse.score_observations(
        hosted,
        device_limit=1,
        thresholds={"analyzers": {"temporal": True, "geo": True}, "cgnat_buffer": 3, "max_concurrent_ips": 0, "max_travel_km": 50},
        hwid_accounts=1,
    )
    assert any(hit["name"] == "temporal" for hit in far["analyzers"])
    assert any(hit["name"] == "geo" for hit in far["analyzers"])


def test_platform_routes_and_schema():
    assert not missing_routes("GET /api/admin/platform/summary", "PUT /api/admin/platform/policy", "GET /api/v3/status")
    assert shop.RATE_LIMITS["/api/agent/heartbeat"] == 120
    assert revision("0038_v2_6_0_platform").down_revision == "0037_v2_5_0_tariff_constructor"
    assert "connection_observations" in tables() and "restricted_at" in columns("users")
    from app import platform_api
    assert platform_api.DEFAULT_POLICY["auto_hard_block"] is False, "hard blocking is the owner's decision"


@pytest.mark.asyncio
async def test_platform_summary_never_returns_secrets(database):
    from app.models import NodeAgent, OutboundWebhook, ShopApiKey
    from app.platform_api import platform_summary
    database.add_all([ShopApiKey(name="crm", prefix="sk_live", secret_hash="HASH-OF-KEY"),
                      OutboundWebhook(url="https://crm.example/hook", secret_encrypted="ENCRYPTED-SECRET"),
                      NodeAgent(name="de-1", token_hash="AGENT-TOKEN-HASH")])
    await database.commit()
    out = await platform_summary(database, SimpleNamespace(email="a@b.c"))
    text = str(out)
    assert out["api_keys"][0]["prefix"] == "sk_live" and out["agents"][0]["name"] == "de-1"
    for secret in ("HASH-OF-KEY", "ENCRYPTED-SECRET", "AGENT-TOKEN-HASH"):
        assert secret not in text


def test_a_restricted_customer_is_refused():
    from app.platform_api import reject_restricted
    reject_restricted(SimpleNamespace(restricted_at=None))
    with pytest.raises(HTTPException) as refused:
        reject_restricted(SimpleNamespace(restricted_at=datetime(2026, 1, 1)))
    assert (refused.value.status_code, refused.value.detail) == (403, "Доступ ограничен")


@pytest.mark.asyncio
async def test_a_blacklisted_device_cannot_be_registered(database):
    from app.models import DeviceBlacklist
    database.add(DeviceBlacklist(hwid="h" * 20, action="block"))
    await database.commit()
    with pytest.raises(HTTPException) as refused:
        await shop.register_device(shop.DeviceRegisterIn(device_key="h" * 20), None, database)
    assert (refused.value.status_code, refused.value.detail) == (403, "Устройство в чёрном списке")


def test_node_agent_runs_no_shell():
    tree = ast.parse((ROOT / "scripts/node-agent.py").read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert not any(k.arg == "shell" and getattr(k.value, "value", False) is True for c in calls for k in c.keywords)
    assert not any(isinstance(c.func, ast.Attribute) and c.func.attr == "system" for c in calls)
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert {"AGENT_APPLY_TC", "X-Agent-Token", "throttle", "clear"} <= strings


@pytest.mark.asyncio
async def test_ops_command_is_for_the_owner_only(monkeypatch):
    from app import bot
    monkeypatch.setattr(bot.settings, "admin_telegram_id", 111)
    answers = []

    async def answer(text, **kw):
        answers.append(text)
    stranger = SimpleNamespace(from_user=SimpleNamespace(id=222, language_code="ru"), answer=answer, text="/ops")
    await bot.ops(stranger)
    assert answers == [bot._tr("ru", "ops_denied")], "anyone but the owner gets a refusal and no figures"


def test_license_and_bilingual_platform_docs():
    license_text = (ROOT / "LICENSE").read_text()
    readme = (ROOT / "docs/archive/README_BEFORE_WORKSPACE.md").read_text()
    github = (ROOT / "docs/archive/README_GITHUB_BEFORE_ALPHA_6.md").read_text()
    instruction = (ROOT / "docs/archive/INSTRUCTION_BEFORE_ALPHA_6.md").read_text()
    security = (ROOT / "docs/archive/SECURITY_BEFORE_ALPHA_6.md").read_text()
    modules = (ROOT / "docs/archive/MODULES_BEFORE_ALPHA_6.md").read_text()
    notes = (ROOT / "docs/archive/root/RELEASE_NOTES_V2_6_0.md").read_text()
    index = (ROOT / "docs/archive/DOCUMENTATION_BEFORE_ALPHA_6.md").read_text()
    admin = (ROOT / "admin/src/main.tsx").read_text()
    i18n = (ROOT / "admin/src/i18n.tsx").read_text()
    cabinet = (ROOT / "cabinet/src/app/layout.tsx").read_text()
    assert "LicenseRef-CorgiLusi-Commercial-Use" in license_text
    assert "VPN Shop Source License" in license_text
    assert "Source License" in license_text
    assert "2.6.0" in readme and "2.5.0" in readme and "2.4.0" in readme
    assert "LICENSE" in readme
    assert "2.6.0" in github
    assert "## 9.5" in instruction
    assert "scripts/node-agent.py" in instruction
    assert "AGENT_APPLY_TC" in instruction
    assert "X-Agent-Token" in security
    assert "API-ключ" in security or "API key" in security
    assert "abuse.py" in modules
    assert "platform_api.py" in modules
    assert "Proprietary" in notes
    assert "2.6.0" in notes
    assert "V44" in index
    assert "Платформа" in admin
    assert '"Платформа": "Platform"' in i18n
    assert "manifest.webmanifest" in cabinet
    assert (ROOT / "deploy/grafana/vpnshop-platform.json").is_file()
    assert (ROOT / "cabinet/public/manifest.webmanifest").is_file()
