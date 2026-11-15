"""Upgrade a fresh DB, a versioned DB, or an exact unversioned 2.1 schema."""
import asyncio
import json
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from .db import engine


def schema_signature(connection):
    inspector = inspect(connection)
    result = {}
    for name in sorted(set(inspector.get_table_names()) - {'alembic_version'}):
        result[name] = {
            'columns': {c['name']: {'type': c['type']._type_affinity.__name__,
                                  'length': getattr(c['type'], 'length', None),
                                  'nullable': c['nullable']} for c in inspector.get_columns(name)},
            'pk': inspector.get_pk_constraint(name)['constrained_columns'],
            'foreign_keys': sorted([{'columns': f['constrained_columns'], 'table': f['referred_table'],
                                     'references': f['referred_columns']} for f in inspector.get_foreign_keys(name)], key=lambda x: str(x)),
            'unique': sorted([u['column_names'] for u in inspector.get_unique_constraints(name)]),
        }
    return result


async def needs_baseline():
    async with engine.connect() as connection:
        def check(sync):
            tables = inspect(sync).get_table_names()
            if 'alembic_version' in tables and sync.execute(text('SELECT version_num FROM alembic_version')).first():
                return False
            if not set(tables) - {'alembic_version'}:
                return False
            expected = json.loads(Path(__file__).with_name('schema_v2.json').read_text())
            actual = schema_signature(sync)
            if actual != expected:
                raise RuntimeError('Unversioned database differs from the original 2.1 schema. No changes made. Back up and inspect the schema before migrating.')
            return True
        result = await connection.run_sync(check)
    await engine.dispose()
    return result


def main():
    baseline = asyncio.run(needs_baseline())
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    if baseline:
        print('Verified original 2.1 schema without a migration version; stamping 0001.')
        command.stamp(config, '0001')
    command.upgrade(config, 'head')


if __name__ == '__main__':
    main()
