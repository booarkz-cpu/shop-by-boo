"""A remnawave-shopbot database (users.db) is recognised by both imports: the column mapping comes with the answer of
«inspect», passes the imports' own validation and reads the real rows of such a file."""
import io
import sqlite3

import pytest
from fastapi import UploadFile

from app import admin_customer_operations as profile_import
from app import history_import
from app.import_presets import SHOPBOT, suggest
from app.sqlite_import import MappingIn, extract, read_table

SCHEMA = """
CREATE TABLE users(telegram_id INTEGER PRIMARY KEY, username TEXT, total_spent REAL, balance REAL, referral_balance REAL,
                   referred_by INTEGER, registration_date TEXT, trial_used INTEGER, is_banned INTEGER);
CREATE TABLE vpn_keys(key_id INTEGER PRIMARY KEY, user_id INTEGER, host_name TEXT, remnawave_user_uuid TEXT, short_uuid TEXT,
                      key_email TEXT, expire_at TEXT, subscription_url TEXT, traffic_limit_bytes INTEGER, tag TEXT);
CREATE TABLE transactions(transaction_id INTEGER PRIMARY KEY, payment_id TEXT, user_id INTEGER, status TEXT, amount_rub REAL,
                          payment_method TEXT, metadata TEXT, created_date TEXT);
INSERT INTO users VALUES (9001, 'anna', 500, 120.5, 30, NULL, '2026-01-02 10:00:00', 1, 0), (9002, NULL, 0, 0, 0, 9001, '2026-02-03 11:00:00', 0, 1);
INSERT INTO vpn_keys VALUES (1, 9001, 'NL', '11111111-2222-4333-8444-555555555555', 'abc', 'u9001@x', '2027-01-01 00:00:00', 'https://sub.example/abc', 107374182400, 'nl');
INSERT INTO transactions VALUES (1, 'pay-1', 9001, 'paid', 299.0, 'YooKassa', '{}', '2026-03-01 12:00:00'), (2, NULL, 9002, 'pending', 99.0, 'CryptoBot', NULL, '2026-03-02 12:00:00');
"""


@pytest.fixture
def users_db(tmp_path):
    path = tmp_path / "users.db"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
    return path.read_bytes()


def upload(data):
    return UploadFile(file=io.BytesIO(data), filename="users.db")


@pytest.mark.asyncio
async def test_customers_table_is_recognised_and_its_mapping_reads_the_rows(users_db):
    answer = await profile_import.inspect(upload(users_db), "users", None)
    found = answer["suggestion"]
    assert found["preset"] == SHOPBOT and found["kind"] == "profile"
    assert found["tables"] == {"profile": "users", "payments": "transactions", "subscriptions": "vpn_keys"}
    assert any("referral_balance" in note for note in found["notes"]) and any("is_banned" in note for note in found["notes"])
    mapping = MappingIn(namespace=found["namespace"], **found["mapping"])   # the import's own validation
    rows = extract(users_db, "users", mapping)
    assert [(r["telegram_id"], r["source_id"], r["username"], r["balance"]) for r in rows] == [(9001, "9001", "anna", "120.50"), (9002, "9002", None, "0.00")]


@pytest.mark.asyncio
async def test_history_tables_are_recognised_and_validate(users_db):
    pay = (await history_import.inspect(upload(users_db), "transactions", None))["suggestion"]
    assert pay["kind"] == "payments"
    payments = history_import.PaymentMap(**pay["mapping"])
    assert (payments.id, payments.user, payments.amount, payments.amount_unit) == ("transaction_id", "user_id", "amount_rub", "decimal")
    assert "paid" in payments.paid_values and payments.paid_at == "created_date"
    _, rows = read_table(users_db, "transactions", [payments.id, payments.user, payments.amount, payments.status])
    assert [tuple(r) for r in rows] == [(1, 9001, 299.0, "paid"), (2, 9002, 99.0, "pending")]

    sub = (await history_import.inspect(upload(users_db), "vpn_keys", None))["suggestion"]
    assert sub["kind"] == "subscriptions"
    subscriptions = history_import.SubscriptionMap(**sub["mapping"])
    assert (subscriptions.user, subscriptions.expires_at, subscriptions.remnawave_uuid) == ("user_id", "expire_at", "remnawave_user_uuid")
    assert subscriptions.traffic_gb is None and any("traffic_limit_bytes" in note for note in sub["notes"])
    # the customer key of the history tables is the one the profile import stores (the Telegram id)
    assert payments.user == subscriptions.user == "user_id"


def test_older_shopbot_column_and_foreign_databases():
    old = suggest("vpn_keys", ["key_id", "user_id", "remnawave_user_uuid", "expiry_date"], ("subscriptions",))
    assert old["mapping"]["expires_at"] == "expiry_date" and "subscription_url" not in old["mapping"]
    # another shop's «users» is not taken for shopbot: the administrator maps it by hand as before
    assert suggest("users", ["id", "telegram_id", "username", "balance"]) is None
    assert suggest("transactions", ["id", "user_id", "amount"]) is None
    assert suggest("vpn_keys", ["user_id", "expire_at"]) is None
    assert suggest("users", ["telegram_id", "trial_used"], ("payments", "subscriptions")) is None   # not what this import reads
    assert suggest("anything", None) is None


@pytest.mark.asyncio
async def test_an_ordinary_database_gets_no_suggestion(tmp_path):
    path = tmp_path / "other.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE users(id INTEGER, telegram_id INTEGER, username TEXT, balance TEXT)")
    answer = await profile_import.inspect(upload(path.read_bytes()), "users", None)
    assert answer["suggestion"] is None and "telegram_id" in answer["columns"]
