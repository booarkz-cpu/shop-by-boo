"""Internal Squads listing for the plans editor: tolerant parsing and safe failure."""
from types import SimpleNamespace

import pytest

from app import remnawave_shop_api as api
from app.config import settings


def test_parse_squads_accepts_wrapped_and_plain_answers():
    wrapped = {"response": {"total": 2, "internalSquads": [
        {"uuid": "a1", "name": "Default", "info": {"membersCount": 12, "inboundsCount": 3}},
        {"uuid": "b2", "name": "Premium"},
        {"name": "no id"},
        "junk",
    ]}}
    assert api.parse_squads(wrapped) == [
        {"uuid": "a1", "name": "Default", "members": 12, "inbounds": 3},
        {"uuid": "b2", "name": "Premium", "members": None, "inbounds": None},
    ]
    assert api.parse_squads([{"id": "c3", "name": "Plain", "inboundsCount": 1}])[0] == {"uuid": "c3", "name": "Plain", "members": None, "inbounds": 1}
    assert api.parse_squads({"response": None}) == [] and api.parse_squads(None) == []


@pytest.mark.asyncio
async def test_endpoint_reports_missing_configuration_and_panel_errors(monkeypatch):
    monkeypatch.setattr(settings, "remnawave_url", "")
    result = await api.remnawave_internal_squads(admin=SimpleNamespace())
    assert result["configured"] is False and result["squads"] == []

    monkeypatch.setattr(settings, "remnawave_url", "https://panel.example.test")
    monkeypatch.setattr(settings, "remnawave_token", "token")

    class Broken:
        async def list_internal_squads(self):
            raise RuntimeError("down")

    monkeypatch.setattr(api, "RemnawaveClient", Broken)
    result = await api.remnawave_internal_squads(admin=SimpleNamespace())
    assert result["configured"] is True and result["squads"] == [] and "Remnawave не ответил" in result["error"]

    class Working:
        async def list_internal_squads(self):
            return {"response": {"internalSquads": [{"uuid": "a1", "name": "Default"}]}}

    monkeypatch.setattr(api, "RemnawaveClient", Working)
    result = await api.remnawave_internal_squads(admin=SimpleNamespace())
    assert result == {"configured": True, "squads": [{"uuid": "a1", "name": "Default", "members": None, "inbounds": None}], "error": None}
