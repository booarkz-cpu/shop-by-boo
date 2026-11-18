# Update the shop

## Manual update

Schedule a maintenance window. For a standard installation, run these commands as root from `/opt/vpn-shop`. If you installed elsewhere, set `APP_DIR` to that directory and use it in the commands below.

Create an encrypted backup before updating. The script prompts for a password and briefly stops the running services that write data. Keep the `.vpb` file, its checksum and the recovery password. Backups go to `/var/backups/vpn-shop` by default.

```bash
cd /opt/vpn-shop &&
  bash scripts/backup.sh &&
  RELEASE_TAG=v28.161.0 bash scripts/update-from-github.sh
```

This command selects the published `v28.161.0`. To install a later stable release, specify its exact tag. Omitting `RELEASE_TAG` selects the latest stable release. If the installed version is the same or newer, the script exits without replacing files.

## What the updater checks

The downloader checks the tag and archive SHA-256, extracts the archive to a temporary directory and verifies the version. It also checks the minimum starting version when the distribution specifies one. The distribution and API version numbers differ for `v28.161.0`, so the downloader also checks the manifest against the archive and the commit referenced by the tag.

Once the archive passes these checks, `update.sh` saves a file snapshot and a SQL dump of the shop database in `.rollback`, applies the update and runs `doctor.sh`.

## Nightly updates

The systemd timer runs on the shop server. The default time is 03:00 Moscow time, with a random delay of up to 15 minutes. `Persistent=true` allows a missed run to start after the server comes back online. Use the following command to check the schedule and the last result.

```bash
cd /opt/vpn-shop && sudo bash scripts/auto-update.sh status
```

Use `install` or `disable` in place of `status` to enable or disable the timer. The `run` command checks for an update and can install it immediately.

## If an update stops

A failure after file replacement begins can trigger an automatic rollback. Check the logs, service status and `.rollback/RECOVERY_MODE`. A manual `scripts/rollback.sh` restores files from `.rollback/latest.tar.gz` and the shop database from `.rollback/latest.sql` by default. Records written after the dump may be lost. To recover both databases and secrets, use the full encrypted backup.

These commands were checked against the v28.161.0 source. Verify installation and recovery on your VPS using that server’s own results.

## Related guides

- [AUTO_UPDATE.md](https://github.com/booarkz-cpu/shop-by-boo/blob/v28.161.0/docs/AUTO_UPDATE.md) — architecture and cycle
- [AUTO_UPDATE_SECURITY.md](https://github.com/booarkz-cpu/shop-by-boo/blob/v28.161.0/docs/AUTO_UPDATE_SECURITY.md) — threat model
- [AUTO_UPDATE_TROUBLESHOOTING.md](https://github.com/booarkz-cpu/shop-by-boo/blob/v28.161.0/docs/AUTO_UPDATE_TROUBLESHOOTING.md) — failures
- [AUTO_UPDATE_TESTING.md](https://github.com/booarkz-cpu/shop-by-boo/blob/v28.161.0/docs/AUTO_UPDATE_TESTING.md) — 19 scenarios

[Troubleshooting](Troubleshooting.md) · [Home](Home.md)
