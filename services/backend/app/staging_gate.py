"""Fail-closed validation for a production payment gate backed by staging evidence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def staging_evidence_valid(status: dict, config: dict, now: datetime, max_age_hours: int = 24) -> bool:
    """Only a current v2 run of the *current* staging config can authorize payments."""
    if not isinstance(status, dict) or not isinstance(config, dict):
        return False
    revision = config.get("revision")
    if not revision or status.get("config_revision") != revision:
        return False
    if status.get("status") != "passed" or status.get("full_e2e") is not True or status.get("contract_version") != 2:
        return False
    try:
        finished = datetime.fromisoformat(str(status["finished_at"]))
    except (KeyError, ValueError, TypeError):
        return False
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    elapsed = now.astimezone(timezone.utc) - finished.astimezone(timezone.utc)
    return timedelta(0) <= elapsed <= timedelta(hours=max_age_hours)
