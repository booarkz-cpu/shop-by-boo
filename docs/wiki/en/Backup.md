# Backups

## What to back up

| What | Why |
| --- | --- |
| the shop database | customers, subscriptions, payments, orders |
| the Support Pro database | tickets and conversations |
| `.env` | secrets and settings; without it the install cannot be restored |
| uploaded files (`MEDIA_DIR`) | avatars, banners, attachments |

## Create a copy

```bash
bash scripts/backup.sh
```

It dumps the database into `BACKUP_DIR`. The "Backups" section of the admin panel lists copies with size, date and
integrity result. The check also runs on a schedule.

## Why one copy is not enough

A copy on the same server disappears with the server. Keep at least one copy off the host — object storage
(S3-compatible is supported) or another server.

Rule: **do not delete the only copy**, neither before a successful update nor after it, until the retention
window passes and another copy exists.

## Verify a copy

A copy you never restored is a hope, not a backup. Once a month:

```bash
# restore the copy on a test host, then run
docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -c "select count(*) from users;"
docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -c "select count(*) from payments;"
```

The numbers must match the production shop at the moment of the copy.

## Restore

```bash
bash scripts/backup.sh                                        # 1. copy the current state first
docker compose stop backend worker bot                        # 2. stop writes
docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" < backup.sql
docker compose start backend worker bot                       # 3. start again
bash scripts/doctor.sh                                        # 4. verify
```

The schema version in the dump must match the shop version. If the dump is from another version, restore that
version first and then update through the normal path.

## Rolling back a release

```bash
bash scripts/rollback.sh
```

The script restores the previous release from the snapshot taken before the update. That is why a copy is created
automatically before every update.

## Secrets in copies

`.env` holds passwords and tokens. Never put a copy of `.env` into git, public storage or open attachments. If a
copy leaked, consider the secrets compromised and rotate them:

```bash
bash scripts/rotate-secrets.sh
```

Documentation: [BACKUP_CURRENT.md](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/BACKUP_CURRENT.md),
[module 30](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/modules/30-backups-recovery.md).

[← Back to home](Home.md)
