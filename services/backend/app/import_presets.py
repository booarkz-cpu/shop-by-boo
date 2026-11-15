"""Known layouts of other shops' databases for the customer and history imports.

The imports themselves are generic: the administrator names a table and says which column is what. For a database the
shop recognises, the column mapping is filled in by itself — the administrator still sees the preview, enters the
control totals and applies. Nothing is imported here; this module only answers «these columns look like … — use this
mapping».

``remnawave-shopbot`` keeps everything in one SQLite file ``users.db``: customers in ``users`` (the Telegram id is the
key everywhere), panel users in ``vpn_keys``, payments in ``transactions``; money is roubles as a decimal number.
"""

SHOPBOT = "remnawave-shopbot"
SHOPBOT_TITLE = "remnawave-shopbot (users.db)"
PAID = ["paid", "succeeded", "success", "completed"]
TABLES = {"profile": "users", "payments": "transactions", "subscriptions": "vpn_keys"}


def _first(columns, *names):
    return next((name for name in names if name in columns), None)


def _profile(columns):
    marks = {"registration_date", "trial_used", "referral_balance", "referred_by"}
    if "telegram_id" not in columns or not marks & set(columns):
        return None
    notes = []
    if "referral_balance" in columns:
        notes.append("Реферальный баланс (referral_balance) не переносится: импорт берёт одну колонку баланса.")
    if "is_banned" in columns:
        notes.append("Блокировки (is_banned) не переносятся — заблокируйте таких клиентов после импорта.")
    return {"mapping": {"table": "users", "telegram_id": "telegram_id", "source_id": "telegram_id",
                        "username": _first(columns, "username"), "balance": _first(columns, "balance"),
                        "balance_unit": "decimal", "currency": "RUB"}, "notes": notes}


def _payments(columns):
    amount = _first(columns, "amount_rub")
    if not amount or "user_id" not in columns or "transaction_id" not in columns:
        return None
    return {"mapping": {"table": "transactions", "id": "transaction_id", "user": "user_id", "amount": amount,
                        "amount_unit": "decimal", "status": _first(columns, "status"), "paid_values": PAID,
                        "paid_at": _first(columns, "created_date"), "description": _first(columns, "payment_method")},
            "notes": ["Сумма — в рублях (amount_rub). Платежи переносятся как история: они не выдаются повторно и не считаются выручкой."]}


def _subscriptions(columns):
    uuid = _first(columns, "remnawave_user_uuid")
    expires = _first(columns, "expire_at", "expiry_date")
    if not uuid or not expires or "user_id" not in columns:
        return None
    notes = ["Пользователи панели Remnawave не меняются: подписки привязываются к уже существующим UUID."]
    if "traffic_limit_bytes" in columns:
        notes.append("Лимит трафика (traffic_limit_bytes, в байтах) не переносится: импорт ждёт гигабайты. Лимит возьмётся из тарифа по умолчанию.")
    return {"mapping": {"table": "vpn_keys", "user": "user_id", "expires_at": expires, "remnawave_uuid": uuid,
                        "subscription_url": _first(columns, "subscription_url")}, "notes": notes}


_KINDS = {"profile": _profile, "payments": _payments, "subscriptions": _subscriptions}


def suggest(table, columns, kinds=("profile", "payments", "subscriptions")):
    """The mapping for a recognised table, or None. ``kinds`` limits what the caller can use."""
    columns = list(columns or [])
    for kind in kinds:
        if table != TABLES[kind]:
            continue
        found = _KINDS[kind](columns)
        if found:
            mapping = {key: value for key, value in found["mapping"].items() if value is not None}
            return {"preset": SHOPBOT, "title": SHOPBOT_TITLE, "kind": kind, "mapping": mapping, "notes": found["notes"],
                    "tables": dict(TABLES), "namespace": SHOPBOT}
    return None
