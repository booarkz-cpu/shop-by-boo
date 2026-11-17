"""REQ-SEC-0012: no configured secret reaches a log line of any process (console, JSON format, error journal)."""
import io
import asyncio
import json
import logging

import pytest

from app import log_format, log_redact
from app.config import Settings, settings

BOT = "123456789:AAH" + "x" * 32
REMNAWAVE = "rw-token-" + "q" * 40
METRICS = "metrics-" + "k" * 30
DB_PASSWORD = "Db-Pass-" + "z" * 12


@pytest.fixture
def secrets(monkeypatch):
    """A settings object with real-looking secrets, installed as this process's secrets for the test."""
    before = log_redact.snapshot()
    configured = Settings(BOT_TOKEN=BOT, REMNAWAVE_TOKEN=REMNAWAVE, METRICS_TOKEN=METRICS,
                          DATABASE_URL=f"postgresql+asyncpg://shop:{DB_PASSWORD}@db:5432/shop",
                          APP_SECRET="app-secret-" + "s" * 30, ANTILOPAY_PUBLIC_KEY="public-key-value-1234")
    log_redact.install(configured)
    yield configured
    log_redact.restore(before)
    log_redact.install(settings)


def capture(name="test.redact", formatter=None):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    if formatter:
        handler.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, stream, handler


def test_the_factory_is_installed_by_the_config_import():
    # Every process imports app.config first; the factory is the masking one from then on.
    assert log_redact._installed
    assert logging.getLogRecordFactory().__qualname__ == "install.<locals>.factory"


def test_secret_settings_are_found_by_name_and_inside_urls(secrets):
    values = log_redact.secret_values(secrets)
    for value in (BOT, REMNAWAVE, METRICS, DB_PASSWORD, secrets.app_secret):
        assert value in values
    assert "public-key-value-1234" not in values  # a public key is not a secret
    assert "change-me" not in values
    assert all(len(v) >= log_redact.MIN_LENGTH for v in values)


def test_values_never_reach_the_console(secrets):
    logger, stream, handler = capture()
    try:
        logger.info("panel answered with %s", REMNAWAVE)
        logger.warning(f"bot {BOT} and key {METRICS} in an f-string")
        logger.error("connect failed: %s", f"postgresql://shop:{DB_PASSWORD}@db/shop")
        logger.info("payload %s", {"secret": METRICS, "ok": 1})
        try:
            raise RuntimeError(f"gateway refused key {METRICS}")
        except RuntimeError:
            logger.exception("payment failed")
    finally:
        logger.removeHandler(handler)
    out = stream.getvalue()
    for value in (BOT, REMNAWAVE, METRICS, DB_PASSWORD):
        assert value not in out, value
    assert "panel answered with ***" in out
    assert "RuntimeError: gateway refused key ***" in out
    assert out.count("***") >= 6


def test_ordinary_lines_and_their_arguments_are_left_alone(secrets):
    logger, stream, handler = capture()
    try:
        logger.info("user %s paid %s RUB", 42, "199.00")
    finally:
        logger.removeHandler(handler)
    assert stream.getvalue() == "user 42 paid 199.00 RUB\n"
    record = logging.getLogRecordFactory()("x", logging.INFO, __file__, 1, "user %s paid %s", (42, "199.00"), None)
    assert record.args == (42, "199.00")  # untouched: formatters that read the arguments still work


def test_uvicorn_access_lines_keep_their_fields(secrets):
    # uvicorn's access format reads (client, method, path, version, status) from the arguments.
    record = logging.getLogRecordFactory()("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                                          ("1.2.3.4:5", "GET", f"/hook?token={REMNAWAVE}", "1.1", 200), None)
    assert isinstance(record.args, tuple) and len(record.args) == 5
    assert REMNAWAVE not in record.getMessage()
    assert record.args[4] == 200


def test_json_format_and_error_journal_get_the_masked_record(secrets):
    logger, stream, handler = capture("test.redact.json", log_format.JsonFormatter())
    try:
        logger.error("token leaked? %s", BOT)
    finally:
        logger.removeHandler(handler)
    line = json.loads(stream.getvalue())
    assert BOT not in line["message"] and "***" in line["message"]
    from app import error_log
    assert BOT not in error_log.redact(f"bot {BOT}")


def test_patterns_mask_secrets_that_are_not_settings(secrets):
    assert log_redact.mask("Authorization: Bearer abcdef123456") == "Authorization: Bearer ***"
    assert log_redact.mask("password=hunter22 next") == "password=*** next"
    assert log_redact.mask("nothing secret here") == "nothing secret here"


def test_the_token_after_bearer_is_masked_not_the_word(secrets):
    from app import error_log
    for text in ("Authorization: Bearer abcdef123456", "authorization=Bearer abcdef123456", "header Bearer abcdef123456"):
        for out in (log_redact.mask(text), error_log.redact(text)):
            assert "abcdef123456" not in out, out
            assert "Bearer ***" in out, out
    assert log_redact.mask("token: abcdef123456") == "token: ***"
    assert log_redact.mask("api_key=abcd1234 and secret='zzzz9999'") == "api_key=*** and secret='***'"


def test_json_exception_cannot_recreate_the_unmasked_traceback(secrets):
    logger, stream, handler = capture("test.redact.json.exception", log_format.JsonFormatter())
    try:
        try:
            raise RuntimeError(f"service refused {METRICS}")
        except RuntimeError:
            logger.exception("operation failed")
    finally:
        logger.removeHandler(handler)
    out = json.loads(stream.getvalue())
    assert METRICS not in out["exception"]
    assert "RuntimeError: service refused ***" in out["exception"]


def test_error_database_masks_configured_values_without_a_secret_field_name(secrets, monkeypatch):
    from app import error_log
    queue = asyncio.Queue()
    monkeypatch.setattr(error_log, "_queue", queue)
    logger = logging.getLogger("test.redact.database")
    handler = error_log.DatabaseHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    try:
        try:
            raise RuntimeError(f"service refused {METRICS}")
        except RuntimeError:
            logger.exception("operation failed")
    finally:
        logger.removeHandler(handler)
    item = queue.get_nowait()
    assert METRICS not in item["traceback"]
    assert "RuntimeError: service refused ***" in item["traceback"]
    assert METRICS not in error_log.redact(f"service refused {METRICS}")


def test_stack_information_is_masked_before_plain_text_formatting(secrets):
    record = logging.getLogRecordFactory()("test.stack", logging.ERROR, __file__, 1, "failed", (), None,
                                          sinfo=f"Stack source contains {METRICS}")
    out = logging.Formatter().format(record)
    assert METRICS not in out
    assert "Stack source contains ***" in out


def test_a_database_only_secret_is_masked_after_it_is_decrypted(secrets):
    from app.security import decrypt_secret, encrypt_secret
    raw = "pay-secret-" + "m" * 24
    assert decrypt_secret(encrypt_secret(raw)) == raw
    logger, stream, handler = capture("test.redact.database-secret")
    try:
        logger.info("gateway returned %s", raw)
        try:
            raise RuntimeError(f"webhook body {raw}")
        except RuntimeError:
            logger.exception("payment notify failed")
    finally:
        logger.removeHandler(handler)
    out = stream.getvalue()
    assert raw not in out
    assert "gateway returned ***" in out
    assert "RuntimeError: webhook body ***" in out


def test_a_short_remembered_secret_is_a_whole_token_only(secrets):
    assert log_redact.remember("k9Qx")
    assert not log_redact.remember("ab")
    assert not log_redact.remember("change-me")
    logger, stream, handler = capture("test.redact.short")
    try:
        logger.info("paid k9Qx now, packagek9Qxextra, code ab")
    finally:
        logger.removeHandler(handler)
    out = stream.getvalue()
    assert "k9Qx" not in out.split("package")[0]
    assert "packagek9Qxextra" in out
    assert "code ab" in out
    assert "paid *** now" in out


def test_an_unlabelled_secret_stays_until_it_is_known(secrets):
    raw = "only-in-db-" + "q" * 20
    assert raw in log_redact.mask(f"seen {raw}")
    assert log_redact.remember(raw)
    assert raw not in log_redact.mask(f"seen {raw}")


def test_an_installer_placeholder_is_not_rewritten(secrets):
    text = "mtproto=on port=9443 domain=www.cloudflare.com secret=[скрыто]"
    assert log_redact.mask(text) == text
    assert "eeabcdef" not in log_redact.mask("secret=eeabcdef0123456789")


def test_private_keys_and_vpn_uris_are_masked_without_a_field_name(secrets):
    pem = "-----BEGIN PRIVATE KEY-----\nMII" + "A" * 40 + "\n-----END PRIVATE KEY-----"
    link = "vless://11111111-2222-3333-4444-555555555555@node.example:443"
    out = log_redact.mask(f"key {pem} link {link} PrivateKey=abcd1234")
    assert "MII" not in out
    assert "11111111-2222-3333-4444-555555555555" not in out
    assert "abcd1234" not in out
    assert "vless://***" in out
    assert "https://shop.example" == log_redact.mask("https://shop.example")


def test_malformed_format_does_not_expose_arguments_through_logging_errors(secrets, capsys):
    logger, stream, handler = capture("test.redact.badformat")
    try:
        logger.error("invalid %q", METRICS)
    finally:
        logger.removeHandler(handler)
    assert METRICS not in capsys.readouterr().err
    assert stream.getvalue() == "Log entry suppressed: formatting failed\n"
