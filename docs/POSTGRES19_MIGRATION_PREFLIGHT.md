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
`PG19_PREFLIGHT_SPEC=db:pgdata18:pgdata19` and point `APP_DIR` at the
directory containing its Compose file and `.env`. The upgrade itself needs
`PG19_UPGRADE_SPEC=db:pgdata18:pgdata19:support:support` with the supplied
environment defaults. Substitute the deployed `POSTGRES_USER` and
`POSTGRES_DB` for the final two fields when they have been customized.
Preserve the Compose project name used to create the original volume.

Before any future cutover, separately verify PG_VERSION=18 using a safe
read-only procedure, inventory extensions and roles, create and **restore-test**
a full backup, check client compatibility, rehearse migration and rollback
on disposable volumes, and compare schema, table counts and application
health. Keep PostgreSQL 18 volumes and backups until acceptance.

This preflight is a safety gate, **not** evidence that migration, restore,
rollback or live integration testing has passed. No requirement PASS is claimed.

References: https://www.postgresql.org/docs/current/pgupgrade.html
and https://www.postgresql.org/docs/current/upgrading.html

### Non-destructive migration safeguards

For a custom deployment, set `PG19_UPGRADE_SPEC` to a comma-separated list of
`service:source_volume:destination_volume:database_user:database_name` mappings.
The upgrade validates the whole list before inspecting volumes or stopping the
stack. Each service must exist in the selected Compose project and each volume
name can appear only once across the list. The default mappings refer to the
integrated shop's volume names and skip services absent from its Compose model.

The PostgreSQL 19 migration refuses identical source and destination volumes,
existing destination relations (including empty tables and migration metadata),
and insufficient or indeterminate storage capacity. The legacy
`PG19_UPGRADE_FORCE` option no longer permits overwriting data. The script does
not drop the destination database. Restore uses a single transaction.

Backup filenames are unique even for runs in the same second; the retained
copy is compared byte-for-byte with the temporary dump before restoration.
This comparison is not proof that the dump is recoverable. The rollback flag
checks only the PostgreSQL 18 version marker, not actual recovery. Do not
resume production traffic until data and application health are verified.
A failed restore must be investigated without deleting the source volume.
