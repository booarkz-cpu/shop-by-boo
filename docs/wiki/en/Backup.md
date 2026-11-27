# Backups

## What to back up

| What | Why |
| --- | --- |
| the shop database | customers, subscriptions, payments, orders |
| the Support Pro database | tickets and conversations |
| `.env` | secrets and settings; without it the install cannot be restored |
| uploaded files (`MEDIA_DIR`) | avatars, banners, attachments |

## Create a full backup

On a standard installation, schedule a maintenance window and run the command below. Enter a password of 12 to 1024 characters and keep it separately.

```bash
cd /opt/vpn-shop && sudo bash scripts/backup.sh
```

The script briefly stops running services that write data while it captures the databases and files. By default it writes `shop-*.vpb` and its `.sha256` file to `/var/backups/vpn-shop`. Set `BACKUP_DEST` to choose another directory. Keep both files off the server and retain the previous verified backup until you have checked the next one. Use the admin panel to restore its own `.enc` backups.

## Recover on a separate host

1. Prepare an isolated host with the same shop release and empty volumes. Keep services that write data stopped and retain the original databases and volumes. Rehearse the recovery monthly.
2. Verify the archive checksum. Decrypt the entire archive to a private file. If decryption fails, discard the incomplete file. After successful decryption, verify the recovered files against `backup-manifest.json`.
3. Restore the environment files before starting the databases. Check `shop.dump` and, if the backup contains Support Pro, `support.dump` with `pg_restore --list`. Restore each to its matching database with `pg_restore --exit-on-error`. Restore media, app packages and support uploads to their respective volumes.
4. Compare subscription and payment records with their values at backup time. Check admin sign-in, attachments and `bash scripts/doctor.sh` before switching traffic.

[Recovery commands (Russian)](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/BACKUP_CURRENT.md) · [Recovery after losing a server (Russian)](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/DISASTER_RECOVERY.md).

## Roll back an update

`scripts/rollback.sh` restores the files and main shop database captured before the update. Use the full backup to recover Support Pro and its files to the same point in time. [Updates and rollback](Updates.md).

## Secrets in copies

`.env` holds passwords and tokens. Never put a copy of `.env` into git, public storage or open attachments. If a
copy leaked, consider the secrets compromised and rotate them:

```bash
bash scripts/rotate-secrets.sh
```

Documentation: [BACKUP_CURRENT.md](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/BACKUP_CURRENT.md),
[module 30](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/modules/30-backups-recovery.md).

[← Back to home](Home.md)
