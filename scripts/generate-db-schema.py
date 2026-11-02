#!/usr/bin/env python3
"""Generate docs/ru/new/DATABASE_SCHEMA.md from the SQLAlchemy models (v28.59.0, stage 5).

The models and the migrations describe one schema (tests/test_schema_matches_migrations.py), so the
document generated from the models is the schema of a migrated database. ``--check`` fails when the
document is stale; tests/test_database_schema_doc.py runs it in CI."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs/ru/new/DATABASE_SCHEMA.md"

# The entities of the master task and where each one lives. «—» means no table: stated honestly.
ENTITIES = [
    ("Users", "users", "клиенты; администраторы — `admin_users`"),
    ("Roles", "admin_users.role", "роль администратора: `viewer`, `operator` или `admin`"),
    ("Permissions", "—", "словарь `PERMISSIONS` в `backend/app/security.py`; проверка — `require_permission`"),
    ("Sessions", "user_sessions, admin_sessions", "отзываемые сессии по хэшу `jti`"),
    ("Subscriptions", "subscriptions", "`remnawave_uuid` (в коде `remnawave_user_id`) — числовой id пользователя Remnawave 3.x"),
    ("Tariffs", "plans, tariff_constructors, tariff_constructor_options, traffic_packages", ""),
    ("Devices", "user_devices, device_blacklist", "HWID-устройства подписки"),
    ("Servers", "—", "серверы и ноды хранятся в Remnawave; магазин хранит агентов нод"),
    ("Nodes", "node_agents, agent_actions", "агент на ноде: здоровье, команды, терминал"),
    ("Domains", "—", "домены задаются в `.env` и `deploy/Caddyfile`; таблица — этап 11"),
    ("Certificates", "—", "сертификаты выпускает Caddy; учёт в базе — этап 11"),
    ("Payments", "payments, payment_provider_events, refund_requests, payment_chargebacks", ""),
    ("Transactions", "financial_ledger, referral_ledger, payout_transactions", "журнал денег, одна запись на операцию"),
    ("Promo Codes", "promo_codes, promo_redemptions, promo_reservations", ""),
    ("Gifts", "gift_codes, gift_redemptions, gift_cards", ""),
    ("Referrals", "referral_rewards, referral_level_rewards, referral_contests, withdrawal_requests", ""),
    ("Notifications", "notifications, push_devices, push_campaigns, push_deliveries", ""),
    ("Support Tickets", "support_tickets, support_messages, support_attachments", "плюс отдельная база Support Pro"),
    ("Integrations", "platform_plugins, plugin_installs, outbound_webhooks, shop_api_keys", ""),
    ("Background Jobs", "jobs, worker_states, backup_jobs", ""),
    ("Audit Logs", "audit_logs", "все изменения администраторов"),
]


def render() -> str:
    os.environ.setdefault("APP_ENV", "test")
    sys.path.insert(0, str(ROOT / "backend"))
    from app.models import Base

    manifest = json.loads((ROOT / "release-manifest.template.json").read_text())
    classes = {mapper.local_table.name: mapper.class_.__name__ for mapper in Base.registry.mappers}
    lines = [
        f"# Схема базы данных — {manifest['distribution_tag']}",
        "",
        f"Сгенерировано из моделей `backend/app/models.py` командой `python scripts/generate-db-schema.py`. Head миграций: `{manifest['migration_head']}`. "
        "Модели и миграции описывают одну схему: это проверяет `tests/test_schema_matches_migrations.py`.",
        "",
        "## Сущности задания",
        "",
        "| Сущность | Таблицы | Примечание |",
        "| --- | --- | --- |",
    ]
    tables = Base.metadata.tables
    for name, where, note in ENTITIES:
        for table in where.split(", "):
            table = table.split(".")[0]
            if table != "—" and table not in tables:
                raise SystemExit(f"DATABASE_SCHEMA: unknown table {table} for {name}")
        lines.append(f"| {name} | {', '.join(f'`{t}`' for t in where.split(', ')) if where != '—' else '—'} | {note} |")
    fk_total = sum(len(t.foreign_keys) for t in tables.values())
    lines += [
        "",
        "## Таблицы",
        "",
        f"Всего таблиц: {len(tables)}, внешних ключей: {fk_total}. Связи без внешнего ключа держит код; "
        "записи без связи показывает «Аналитика → Запуск и оповещения → Целостность данных» (`GET /api/admin/integrity`).",
        "",
        "| Таблица | Модель | Колонок | Уникальные | Индексы | Внешние ключи |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name in sorted(tables):
        t = tables[name]
        unique = sorted({c.name for c in t.columns if c.unique} | {
            "+".join(c.name for c in con.columns) for con in t.constraints
            if con.__class__.__name__ == "UniqueConstraint"} | {
            "+".join(c.name for c in i.columns) for i in t.indexes if i.unique})
        indexes = sorted("+".join(c.name for c in i.columns) for i in t.indexes if not i.unique)
        fks = sorted(f"{fk.parent.name} → {fk.column.table.name}" for fk in t.foreign_keys)
        lines.append(f"| `{name}` | `{classes.get(name, '—')}` | {len(t.columns)} | {', '.join(unique) or '—'} | "
                     f"{', '.join(indexes) or '—'} | {', '.join(fks) or '—'} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != content:
            raise SystemExit("DATABASE_SCHEMA.md is stale: run scripts/generate-db-schema.py")
    else:
        TARGET.write_text(content)


if __name__ == "__main__":
    main()
