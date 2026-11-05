#!/usr/bin/env bash
# Restore an encrypted bundle made by scripts/backup.sh into an EMPTY installation:
# a new server after a loss, or an isolated contour for a recovery check.
# It never overwrites a database that already has tables and never touches a running shop.
#
#   sudo env APP_DIR=/opt/vpn-shop bash scripts/restore.sh /var/backups/vpn-shop/shop-….vpb
#
# Before: install the same release, keep only the databases running
# (docker compose up -d --wait db support_db). After: docker compose up -d.
set -Eeuo pipefail
umask 077
APP_DIR="${APP_DIR:-/opt/vpn-shop}"
bundle="${1:-}"
[[ -n "$bundle" && -f "$bundle" ]] || { echo 'usage: restore.sh /path/to/shop-….vpb' >&2; exit 2; }
bundle="$(realpath "$bundle")"
cd "$APP_DIR"
[[ -f .env ]] || { echo "Missing $APP_DIR/.env" >&2; exit 2; }
[[ -f "$bundle.sha256" ]] || { echo "Missing $bundle.sha256 next to the copy" >&2; exit 2; }
(cd "$(dirname "$bundle")" && sha256sum --check --quiet --status "$(basename "$bundle").sha256") \
  || { echo 'RESTORE: the copy does not match its SHA256 file; it is damaged or was changed.' >&2; exit 3; }

configured="$(docker compose config --services)"
has(){ [[ $'\n'"$configured"$'\n' == *$'\n'"$1"$'\n'* ]]; }
running="$(docker compose ps --services --status running)"
for service in backend backend_standby worker mail_receiver bot support_pro support_worker; do
  if [[ $'\n'"$running"$'\n' == *$'\n'"$service"$'\n'* ]]; then
    echo "RESTORE: $service is running. Stop the shop first: docker compose stop (keep db and support_db)." >&2
    exit 4
  fi
done

if [[ -z "${BACKUP_BUNDLE_PASSWORD:-}" ]]; then
  read -rsp 'Пароль шифрования копии: ' BACKUP_BUNDLE_PASSWORD
  printf '\n' >&2
fi
export BACKUP_BUNDLE_PASSWORD

databases=(db)
has support_db && databases+=(support_db)
docker compose up -d --wait "${databases[@]}"
tables(){ docker compose exec -T "$1" psql -U "$2" -d "$3" -Atc "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')"; }
[[ "$(tables db vpnshop vpnshop)" == 0 ]] \
  || { echo 'RESTORE: the shop database is not empty. Restore only into a new installation.' >&2; exit 5; }
if has support_db; then
  [[ "$(tables support_db support support)" == 0 ]] \
    || { echo 'RESTORE: the Support Pro database is not empty. Restore only into a new installation.' >&2; exit 5; }
fi

work="$(mktemp -d)"
cleanup(){ code=$?; trap - EXIT; rm -rf "$work"; unset BACKUP_BUNDLE_PASSWORD; exit "$code"; }
trap cleanup EXIT
docker compose run --rm --no-deps -T -e BACKUP_BUNDLE_PASSWORD --entrypoint python backend /project/scripts/backup_bundle.py decrypt \
  < "$bundle" | tar -C "$work" -xf - \
  || { echo 'RESTORE: could not decrypt the copy (wrong password or damaged file).' >&2; exit 3; }

# Every file must match the copy's own manifest; nothing missing, nothing extra.
python3 - "$work" "$APP_DIR" <<'PY'
import hashlib, json, sys
from pathlib import Path
folder, root = Path(sys.argv[1]), Path(sys.argv[2])
manifest = json.loads((folder / 'backup-manifest.json').read_text())
listed = manifest['files']
present = {p.name for p in folder.iterdir() if p.is_file() and p.name != 'backup-manifest.json'}
if set(listed) != present:
    sys.exit(f'RESTORE: files differ from the manifest: missing {sorted(set(listed) - present)}, extra {sorted(present - set(listed))}')
for name, digest in listed.items():
    with (folder / name).open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
            sys.exit(f'RESTORE: {name} does not match the manifest')
current = json.loads((root / 'release-manifest.template.json').read_text())['version']
print(f"Copy made on runtime {manifest['source_version']}; installed runtime {current}.")
if manifest['source_version'] != current:
    print('Versions differ: the shop applies migrations of the installed release on start.')
PY

docker compose exec -T db pg_restore --list < "$work/shop.dump" >/dev/null
docker compose exec -T db pg_restore --no-owner --no-privileges --exit-on-error -U vpnshop -d vpnshop < "$work/shop.dump"
echo 'Shop database restored.'
if [[ -f "$work/support.dump" ]]; then
  if has support_db; then
    docker compose exec -T support_db pg_restore --list < "$work/support.dump" >/dev/null
    docker compose exec -T support_db pg_restore --no-owner --no-privileges --exit-on-error -U support -d support < "$work/support.dump"
    echo 'Support Pro database restored.'
  else
    echo 'The copy has a Support Pro database, but this installation has no support_db; skipped.' >&2
  fi
fi

# Files go into the volumes as the service user (volume_init gives the volumes to it first).
docker compose run --rm --no-deps volume_init >/dev/null
docker compose run --rm --no-deps -T --entrypoint tar backend -xzf - -C /data/media < "$work/media.tar.gz"
docker compose run --rm --no-deps -T --entrypoint tar backend -xzf - -C /data/app-packages < "$work/app-packages.tar.gz"
if [[ -f "$work/support-uploads.tar.gz" ]] && has support_pro; then
  docker compose run --rm --no-deps -T --entrypoint tar support_pro -xzf - -C /data/uploads < "$work/support-uploads.tar.gz"
fi
echo 'Files restored.'

# Secrets are not applied automatically. Encrypted columns need the keys of the original .env.
saved="$(dirname "$bundle")/restored-env-$(date -u +%Y%m%dT%H%M%SZ)"  # next to the copy, not in the project
mkdir -m 700 "$saved"
tar -C "$saved" -xzf "$work/environment.tar.gz"
python3 - "$saved" "$APP_DIR" <<'PY'
import sys
from pathlib import Path
saved, root = Path(sys.argv[1]), Path(sys.argv[2])
def keys(path):
    out = {}
    for line in path.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            out[key.strip()] = value.strip()
    return out
differ = []
for env in sorted(saved.rglob('.env*')):
    target = root / env.relative_to(saved)
    if not target.is_file():
        differ.append(f'{env.relative_to(saved)} (absent here)')
        continue
    old, new = keys(env), keys(target)
    names = [k for k in old if k.endswith(('SECRET', 'KEY', 'PASSWORD', 'TOKEN')) and old.get(k) != new.get(k)]
    if names:
        differ.append(f"{env.relative_to(saved)}: {', '.join(sorted(names))}")
if differ:
    print('WARNING: secrets of the copy differ from this installation (values are not printed):')
    for line in differ:
        print('  ' + line)
    print(f'The original files are in {saved} (mode 0700). Move the needed values into .env before starting the shop.')
else:
    print(f'Secrets match this installation. The original files are kept in {saved} (mode 0700); delete it when done.')
PY
echo 'RESTORE: done. Start the shop: docker compose up -d'
