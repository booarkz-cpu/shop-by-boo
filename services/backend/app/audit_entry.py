"""Result and a before/after list on an audit row (REQ-ADMIN-0011).

Callers that do not pass ``result``, ``before`` or ``after`` keep the old details text.
A secret-looking key is stored as ``unavailable``; the row still shows that the field changed.
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

SECRET_KEYS = {
    "error", "token", "secret", "password", "authorization", "passwd",
    "api_key", "apikey", "private_key", "privatekey",
}


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _secret(key) -> bool:
    return str(key).lower().replace("-", "_") in SECRET_KEYS


def redact(value):
    if isinstance(value, dict):
        return {key: ("unavailable" if _secret(key) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return _plain(value)


def changes(before, after) -> list[dict]:
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    rows = []
    for key in dict.fromkeys([*before, *after]):
        seen_before, seen_after = key in before, key in after
        if seen_before and seen_after and before[key] == after[key]:
            continue
        rows.append({
            "field": str(key),
            "before": "unavailable" if seen_before and _secret(key) else (redact(before[key]) if seen_before else None),
            "after": "unavailable" if seen_after and _secret(key) else (redact(after[key]) if seen_after else None),
        })
    return rows


def write(db, model, action, actor, target, details, result, before, after, request_id, dumps, fallback):
    if result is None and before is None and after is None:
        stored = dumps(details, ensure_ascii=False, default=fallback) if isinstance(details, dict) else details
    else:
        body = {}
        if isinstance(details, dict):
            body.update(details)
        elif details not in (None, ""):
            body["note"] = details
        body["result"] = result or "ok"
        body["changes"] = changes(before, after)
        stored = dumps(redact(body), ensure_ascii=False, default=fallback)
    db.add(model(
        action=action, actor=actor or "system", target=target, request_id=request_id, details=stored,
    ))


def audit_public(row, public_details):
    result, listed = None, []
    raw = row.details
    if isinstance(raw, str) and raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and "result" in parsed and isinstance(parsed.get("changes"), list):
            result = parsed.get("result")
            listed = parsed["changes"]
    return {
        "id": row.id, "action": row.action, "actor": row.actor, "target": row.target,
        "details": public_details(raw), "result": result, "changes": listed,
        "request_id": row.request_id, "created_at": str(row.created_at),
    }
