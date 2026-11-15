"""v28.159.0 (REQ-SEC-0012): no configured secret reaches a log line.

Every process of the shop (API, worker, bot, CLI) imports ``app.config`` first, and that import installs a log record
factory: each record is formatted once when it is created, the message and the exception text are masked, and the
record then goes to every handler as it is — the console (``docker logs``), the JSON format, the error journal in the
database. A handler added later by uvicorn or aiogram gets the masked record too, because masking happens before any
handler sees it.

What is masked:

- the exact values of the secret settings (tokens, passwords, API keys, signing secrets, the database and Redis
  passwords inside their URLs) — the name of the setting decides, see ``SECRET_WORDS``; values shorter than 6
  characters and the defaults ``change-me`` are left alone, they cannot be told from ordinary words;
- the same patterns as the error journal (``token=…``, ``password: …``, ``Authorization: Bearer …``, Telegram bot tokens).
"""
from __future__ import annotations

import logging
import re

# The patterns of the error journal (error_log imports this module, not the other way round: config loads first).
# The scheme word of «Authorization: Bearer <token>» is not the secret: the token after it is (fixed in v28.159.0,
# before the journal masked «Bearer» and kept the token).
SCHEME = re.compile(r"(?i)\b(bearer|basic|token)(\s+)([A-Za-z0-9._~+/=-]{6,})")
SECRET = re.compile(r"""(?i)(token|secret|password|passwd|api[_-]?key|authorization)(["']?\s*[=:]\s*["']?)(?!(?:bearer|basic)\s)(?!\*\*\*)([^\s"',;]{4,})""")
BOT_TOKEN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")


def redact_patterns(text: str) -> str:
    text = BOT_TOKEN.sub(MASK, text or "")
    text = SCHEME.sub(lambda m: m.group(1) + m.group(2) + MASK, text)
    return SECRET.sub(lambda m: m.group(1) + m.group(2) + MASK, text)

MASK = "***"
SECRET_WORDS = ("secret", "token", "password", "passwd", "api_key", "private_key", "access_key", "secret_key", "_key")
NOT_SECRET = ("public_key", "key_id", "_key_id", "keys_dir")
MIN_LENGTH = 6
_installed = False
_values: list[str] = []
_URL_PASSWORD = re.compile(r"://[^:/@\s]+:([^@/\s]+)@")


def secret_values(settings) -> list[str]:
    """Values of the secret settings, longest first (a secret that contains another is masked whole)."""
    found: set[str] = set()
    for name, value in settings.model_dump().items():
        if not isinstance(value, str) or not value:
            continue
        lowered = name.lower()
        if any(word in lowered for word in SECRET_WORDS) and not any(word in lowered for word in NOT_SECRET):
            found.add(value)
        # Passwords written inside connection strings (DATABASE_URL, REDIS_URL…).
        for match in _URL_PASSWORD.finditer(value):
            found.add(match.group(1))
    return sorted((v for v in found if len(v) >= MIN_LENGTH and v != "change-me"), key=len, reverse=True)


def mask(text: str) -> str:
    if not text:
        return text
    for value in _values:
        if value in text:
            text = text.replace(value, MASK)
    return redact_patterns(text)


def install(settings) -> bool:
    """Puts the masking factory in front of logging once per process. Returns whether it was installed now."""
    global _installed, _values
    _values = secret_values(settings)
    if _installed:
        return False
    previous = logging.getLogRecordFactory()
    plain = logging.Formatter()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        try:
            message = record.getMessage()
            masked = mask(message)
            if masked != message:
                # Arguments are masked one by one first: uvicorn's access format reads them as fields.
                if isinstance(record.args, tuple):
                    record.args = tuple(mask(a) if isinstance(a, str) else a for a in record.args)
                if isinstance(record.msg, str):
                    record.msg = mask(record.msg)
                if mask(record.getMessage()) != record.getMessage():
                    record.msg, record.args = masked, None  # a secret split between the template and an argument
            if record.exc_text:
                record.exc_text = mask(record.exc_text)
            elif record.exc_info:
                record.exc_text = mask(plain.formatException(record.exc_info))
            if record.stack_info:
                record.stack_info = mask(record.stack_info)
        except Exception:  # noqa: BLE001 — malformed logging must not disclose the original arguments via handleError
            record.msg, record.args = "Log entry suppressed: formatting failed", ()
            record.exc_info, record.exc_text, record.stack_info = None, None, None
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
    return True
