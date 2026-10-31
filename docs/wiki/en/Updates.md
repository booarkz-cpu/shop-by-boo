# Updates

The shop updates to published GitHub Releases. There is a manual run and a nightly automatic check.

## Architecture

There is no separate scheduler server. The scheduler is **systemd on the same host** that runs the shop. GitHub
is only the source of verified releases and has no access to the server filesystem.

| Where | What | File |
| --- | --- | --- |
| Host (root, systemd) | nightly timer and agent | `scripts/auto_update.py`, `scripts/auto-update.sh` |
| Host | fetch and verify the release (SHA-256, manifest) | `scripts/update-from-github.sh` |
| Backend | only writes a request and reads state | `backend/app/auto_update_api.py` |
| Panel | buttons and status | "Updates" section |

The exchange goes through two JSON files in `.control`: the panel writes a request, the agent writes state. The
agent accepts exactly three fields (`enabled`, `time`, `check_now`) and validates their format — the panel cannot
make the server do anything else.

## Schedule

Default **03:00 Europe/Moscow**, random delay up to 15 minutes (`RandomizedDelaySec=900`), `Persistent=true` — a
missed run executes once the host is back.

The time is changed in the "Updates" section: the agent rewrites the timer unit file.

```bash
sudo bash scripts/auto-update.sh status     # state and schedule
sudo bash scripts/auto-update.sh install    # enable the nightly check
sudo bash scripts/auto-update.sh disable    # disable
```

## What happens during an update

1. Source check — stable GitHub releases only.
2. Fetch version metadata and the manifest.
3. Check version and channel.
4. Check compatibility and required configuration.
5. Check migrations: an irreversible migration stops automatic installation.
6. Back up the database and snapshot the files.
7. Download the artefact and verify SHA-256.
8. Unpack, migrate, build.
9. Restart services.
10. Check `/health`, key APIs, the panel and the database.
11. Record the result and notify the administrator.

If any critical check fails, the artefact is **not** installed.

## Rollback

On a post-install failure a verified rollback to the snapshot taken before the update is triggered:

```bash
bash scripts/rollback.sh
```

If a safe rollback is impossible, the update stops, diagnostics are preserved and the administrator is notified.

## Manual update

```bash
bash scripts/backup.sh
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.56.0 bash /opt/vpn-shop/scripts/update-from-github.sh
```

## What the "Updates" section shows

Current and available version, source and channel, last check and last update time, schedule, automatic mode,
operation history, compatibility result, backup status, migration status, health checks and a GitHub Release link.

Buttons: "Check for updates", "Update now", "Enable auto-update", "Disable auto-update", "View log", "Check
system state", "Restore previous version".

## Documentation

- [AUTO_UPDATE.md](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/AUTO_UPDATE.md) — architecture and cycle
- [AUTO_UPDATE_SECURITY.md](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/AUTO_UPDATE_SECURITY.md) — threat model
- [AUTO_UPDATE_TROUBLESHOOTING.md](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/AUTO_UPDATE_TROUBLESHOOTING.md) — failures
- [AUTO_UPDATE_TESTING.md](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/AUTO_UPDATE_TESTING.md) — 19 scenarios

## Status

The mechanism is implemented and documented, local tests pass. The timer firing and a real install on a VPS have
not been verified: the project has no host with a deployed shop. That limit is recorded, not hidden.

[← Back to home](Home.md)
