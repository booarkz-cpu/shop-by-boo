# PostgreSQL 19 migration — read-only preflight

PostgreSQL 18.7 remains the production baseline. PostgreSQL 19 is a **major**
upgrade and cannot open PostgreSQL 18 data directories directly. Do not change
the active Compose image to 19 until a separately reviewed migration and
rollback procedure is implemented and tested.

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
