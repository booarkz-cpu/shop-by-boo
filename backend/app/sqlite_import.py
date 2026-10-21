"""Bounded, read-only extraction from an administrator-supplied SQLite snapshot."""
import re
import sqlite3
import tempfile
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 1000


class MappingIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    namespace: str = Field(pattern=r'^[A-Za-z0-9_-]{3,64}$')
    table: str = Field(default='users', pattern=r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')
    telegram_id: str = Field(min_length=1, max_length=100)
    source_id: str | None = Field(default=None, max_length=100)
    username: str | None = Field(default=None, max_length=100)
    balance: str | None = Field(default=None, max_length=100)
    balance_unit: str = Field(default='decimal', pattern='^(decimal|minor)$')
    currency: str = Field(pattern='^[A-Z]{3}$')
    credit_balances: bool = False


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def read_table(data: bytes, table: str, selected: list[str] | None = None, max_rows: int = MAX_ROWS):
    """Read-only, time/size-bounded SELECT of `selected` columns (or schema only when None).

    Shared by the profile import and the versioned history adapters. The snapshot is
    opened immutable, untrusted schema is disabled and an authorizer limits the
    statement to plain reads of the named table and columns.
    """
    if len(data) > MAX_BYTES or not data.startswith(b'SQLite format 3\0'):
        raise HTTPException(422, 'Нужен SQLite snapshot до 5 МБ')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', table):
        raise HTTPException(422, 'Некорректное имя таблицы')
    try:
        with tempfile.TemporaryDirectory(prefix='shop-import-') as temporary:
            path = Path(temporary) / 'snapshot.db'
            path.write_bytes(data);path.chmod(0o600)
            connection = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
            try:
                connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 100000)
                connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 16000)
                connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 100)
                connection.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 20)
                if hasattr(connection, 'setconfig'):
                    connection.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
                    connection.setconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA, False)
                connection.execute('PRAGMA trusted_schema=OFF')
                connection.execute('PRAGMA query_only=ON')
                deadline = time.monotonic() + 2
                connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                schema = connection.execute('SELECT type,sql FROM sqlite_master WHERE name=?', (table,)).fetchone()
                if not schema or schema[0] != 'table' or not str(schema[1]).lstrip().upper().startswith('CREATE TABLE'):
                    raise HTTPException(422, 'Выберите обычную таблицу; views и virtual tables запрещены')
                fields = connection.execute(f'PRAGMA table_xinfo({quoted(table)})').fetchall()
                columns = [field[1] for field in fields if field[6] == 0]
                if selected is None:return columns, []
                if any(column not in columns for column in selected):
                    raise HTTPException(422, 'Поле отсутствует либо является вычисляемым')
                def authorize(action, arg1, arg2, database, trigger):
                    if action == sqlite3.SQLITE_SELECT:return sqlite3.SQLITE_OK
                    if action == sqlite3.SQLITE_READ and arg1 == table and arg2 in selected and database == 'main' and not trigger:
                        return sqlite3.SQLITE_OK
                    return sqlite3.SQLITE_DENY
                connection.set_authorizer(authorize)
                rows = connection.execute('SELECT ' + ','.join(map(quoted, selected)) + f' FROM {quoted(table)} LIMIT ?', (max_rows + 1,)).fetchall()
            finally:connection.close()
    except sqlite3.Error as error:
        raise HTTPException(422, 'Не удалось безопасно прочитать snapshot SQLite') from error
    return columns, rows


def extract(data: bytes, table: str, mapping: MappingIn | None = None):
    if not mapping:
        columns, _ = read_table(data, table)
        return {'table': table, 'columns': columns, 'max_rows': MAX_ROWS, 'max_bytes': MAX_BYTES}
    selected = [mapping.source_id or mapping.telegram_id, mapping.telegram_id]
    if mapping.username:selected.append(mapping.username)
    if mapping.balance:selected.append(mapping.balance)
    _, rows = read_table(data, table, selected)
    if not rows or len(rows) > MAX_ROWS:raise HTTPException(422, 'В snapshot должно быть 1–1000 клиентов')
    normalized = []
    source_ids, telegram_ids = set(), set()
    for index, row in enumerate(rows, 1):
        source_id = str(row[0]) if isinstance(row[0], (int, str)) and not isinstance(row[0], bool) else ''
        telegram = str(row[1]) if isinstance(row[1], (int, str)) and not isinstance(row[1], bool) else ''
        if not source_id.strip() or len(source_id) > 128 or not re.fullmatch(r'[1-9][0-9]{0,18}', telegram) or int(telegram) > 2**63-1:
            raise HTTPException(422, f'Строка {index}: неверный source ID / Telegram ID')
        if source_id in source_ids or int(telegram) in telegram_ids:
            raise HTTPException(422, f'Строка {index}: повтор source ID / Telegram ID')
        source_ids.add(source_id);telegram_ids.add(int(telegram))
        username = row[2] if mapping.username else None
        if username is not None and (not isinstance(username, str) or len(username) > 255):
            raise HTTPException(422, f'Строка {index}: неверное имя')
        amount = Decimal(0)
        if mapping.balance:
            raw = row[3 if mapping.username else 2]
            try:
                if raw is None or isinstance(raw, (bytes, bool)):raise ValueError()
                amount = Decimal(str(raw)) / (100 if mapping.balance_unit == 'minor' else 1)
                if not amount.is_finite() or not 0 <= amount <= 1000000 or amount != amount.quantize(Decimal('.01')):raise ValueError()
            except (ValueError, InvalidOperation):raise HTTPException(422, f'Строка {index}: баланс должен быть 0–1000000 с точностью до 0.01')
        normalized.append({'source_id': source_id, 'telegram_id': int(telegram), 'username': username, 'balance': str(amount.quantize(Decimal('.01')))})
    if sum(Decimal(row['balance']) for row in normalized) > 10000000:
        raise HTTPException(422, 'Общий исходный баланс превышает 10000000')
    return sorted(normalized, key=lambda row: row['telegram_id'])
