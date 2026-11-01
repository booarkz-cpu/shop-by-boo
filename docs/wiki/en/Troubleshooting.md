# Troubleshooting

Symptom → cause → how to check → how to fix.

## Interface

### `Cannot read properties of undefined (reading 'trim')`

**Cause:** a field the editor expects as a label object `{ru, en, uk}` arrived as a string or `undefined`.

**Check:** open the browser console (F12 → Console), find the failed request and inspect the field shape.

**Fix:** as of v28.57.0 the shape is enforced by a server-side test. On an older build, update:

```bash
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.57.0 bash scripts/update-from-github.sh
```

### `(s || []).map is not a function`

**Cause:** the API returned an object instead of a list.

**Check:** look at the endpoint response in the Network tab.

**Fix:** the panel normalises `items`, `results` and `data`. If the error persists, the request goes to the wrong
backend: check `NEXT_PUBLIC_API_URL` and `PUBLIC_BASE_URL`.

### Blank (black) admin or cabinet page

**Cause:** a React render failure without an error boundary unmounted the whole tree.

**Check:** the browser console shows the message before the fall.

**Fix:** as of v28.57.0 `app/error.tsx` and root boundaries are in place — an error screen with the reason and a
retry appears instead of an empty page.

### A section does not load

| Status | Meaning | What to do |
| --- | --- | --- |
| 401 | session expired | sign in again |
| 403 | the role has no permission | grant it under "Security" |
| 404 | the route is missing on the server | check the backend version |
| 422 | invalid form data | read the field name in the error text |
| 500 | server exception | `docker compose logs backend` |
| 503 | a dependency is down | check Remnawave, database, Redis |

## Services

### Docker Compose does not start

```bash
docker compose config          # prints syntax errors and unset variables
ls -la .env                    # the file must exist
```

### A container keeps restarting

```bash
docker compose ps                       # STATUS shows Restarting
docker compose logs --tail=100 backend  # the reason
free -h                                 # is memory enough
```

### API is unreachable

```bash
curl -s localhost:8000/health
docker compose logs backend | tail -50
```

Expected: `{"ok":true,"version":"21.5.1","redis":true,"database":true}`.

### No HTTPS certificate

```bash
dig +short admin.your-domain.com     # must return the server IP
docker compose logs caddy | tail -30
```

The usual cause is a domain that does not point at the server yet, or a closed port 80.

## Data

### Migration error

```bash
docker compose exec -T backend alembic current
docker compose exec -T backend alembic heads
```

If `current` is ahead of `heads`, the database belongs to a newer version. Restore a copy and update through the
normal path.

### A subscription is not created

```bash
docker compose logs backend | grep -i remnawave | tail -20
```

Check `REMNAWAVE_URL`, `REMNAWAVE_TOKEN`, and that the plan has an Internal Squad.

## Money

### The webhook never arrives

1. In the provider dashboard check the address: `https://your-domain/api/webhooks/<provider>`.
2. Check the domain is reachable from outside: `curl -I https://your-domain/health`.
3. Read the incoming event log under "Payments".

### A payment is not confirmed

Amount, currency and order number must match. Read `docker compose logs backend` — it names the reason: signature,
amount, or the provider being unreachable for verification.

## Updates

### An update does not go through

```bash
sudo bash scripts/auto-update.sh status     # stage, result, log
df -h                                       # free space
```

Causes: no root rights, little free space, checksum mismatch, an incompatible migration.

## Backups

### A backup is not created

```bash
df -h
ls -la "$BACKUP_DIR" 2>/dev/null || grep BACKUP_DIR .env
```

## Quick full check

```bash
bash scripts/doctor.sh
```

It checks the Compose configuration, the containers and `/health`. This is the first command for any problem.

[← Back to home](Home.md)
