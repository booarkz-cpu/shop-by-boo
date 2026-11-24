# PostgreSQL 19 migration — read-only preflight

Compose now starts PostgreSQL 19.0. PostgreSQL 19 cannot open a PostgreSQL 18
data directory. `scripts/upgrade-postgres19.sh` copies an existing 18 volume
into a new 19 volume with `pg_dump -Fc`, checks row counts, runs `ANALYZE`,
and keeps both the dump and the 18 volume. It does not delete volumes.
`PG19_ROLLBACK=1` only checks that the 18 volume is still a PostgreSQL 18
cluster. A live server was not migrated by this change, and no requirement
PASS is claimed. The read-only preflight below remains available before cutover.

From the deployment directory, run:

```bash
APP_DIR=/opt/vpn-shop bash scripts/postgres19-preflight.sh
```

The preflight only runs `docker compose config` and `docker volume inspect`.
It checks whether the existing PostgreSQL 18 source volumes are present and
whether proposed PostgreSQL 19 destination volumes already exist. It does **not**
inspect PG_VERSION, take a backup, start or stop containers, or migrate data.
A missing source or existing destination produces a nonzero exit code.

Default pairs: `db:postgres18_data:postgres19_data` and
`support_db:support_postgres18_data:support_postgres19_data`.
For a standalone Support Pro deployment set
`PG19_PREFLIGHT_SPEC=db:pgdata18:pgdata19` and the matching `APP_DIR`.

Before any future cutover, separately verify PG_VERSION=18 using a safe
read-only procedure, inventory extensions and roles, create and **restore-test**
a full backup, check client compatibility, rehearse migration and rollback
on disposable volumes, and compare schema, table counts and application
health. Keep PostgreSQL 18 volumes and backups until acceptance.

This preflight is a safety gate, **not** evidence that migration, restore,
rollback or live integration testing has passed. No requirement PASS is claimed.

References: https://www.postgresql.org/docs/current/pgupgrade.html
and https://www.postgresql.org/docs/current/upgrading.html
