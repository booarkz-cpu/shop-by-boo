#!/usr/bin/env bash
# Create a consistent encrypted bundle of both databases, files and secrets.
set -Eeuo pipefail
umask 077
APP_DIR="${APP_DIR:-/opt/vpn-shop}"
BACKUP_DEST="${BACKUP_DEST:-/var/backups/vpn-shop}"
cd "$APP_DIR"
[[ -f .env ]] || { echo "Missing $APP_DIR/.env" >&2; exit 2; }
command -v flock >/dev/null || { echo 'flock is required' >&2; exit 2; }
exec 9>>"$APP_DIR/.backup.lock"
flock -n 9 || { echo 'A backup is already running' >&2; exit 2; }
if [[ -z "${BACKUP_BUNDLE_PASSWORD:-}" ]]; then
  read -rsp 'Пароль шифрования копии (не менее 12 символов): ' BACKUP_BUNDLE_PASSWORD
  printf '\n' >&2
fi
[[ ${#BACKUP_BUNDLE_PASSWORD} -ge 12 && ${#BACKUP_BUNDLE_PASSWORD} -le 1024 ]] || { echo 'Password must contain 12–1024 characters' >&2; exit 2; }
export BACKUP_BUNDLE_PASSWORD
configured="$(docker compose config --services)"
running="$(docker compose ps --services --status running)"
[[ $'\n'"$configured"$'\n' == *$'\n'db$'\n'* ]] || { echo 'Shop database service is missing' >&2; exit 2; }
writers=()
for service in backend worker bot support_pro support_worker; do
  [[ $'\n'"$running"$'\n' == *$'\n'"$service"$'\n'* ]] && writers+=("$service")
done
mkdir -p "$BACKUP_DEST"
work="$(mktemp -d)"
output="$(mktemp "$BACKUP_DEST/shop-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXXXX.vpb")"
stopped=0
cleanup(){
  code=$?
  trap - EXIT
  if (( stopped )); then
    if ! docker compose start "${writers[@]}"; then
      echo 'BACKUP: failed to restart services; inspect docker compose ps.' >&2
      code=1
    fi
  fi
  rm -rf "$work"
  unset BACKUP_BUNDLE_PASSWORD
  (( code == 0 )) || rm -f "$output" "$output.sha256"
  exit "$code"
}
trap cleanup EXIT
if (( ${#writers[@]} )); then
  stopped=1
  docker compose stop "${writers[@]}"
fi
docker compose exec -T db pg_dump -U vpnshop -d vpnshop -Fc > "$work/shop.dump"
test -s "$work/shop.dump"
docker compose exec -T db pg_restore --list < "$work/shop.dump" >/dev/null
docker compose run --rm --no-deps -T --entrypoint tar backend -czf - -C /data/media . > "$work/media.tar.gz"
docker compose run --rm --no-deps -T --entrypoint tar backend -czf - -C /data/app-packages . > "$work/app-packages.tar.gz"
if [[ $'\n'"$configured"$'\n' == *$'\n'support_db$'\n'* ]]; then
  docker compose exec -T support_db pg_dump -U support -d support -Fc > "$work/support.dump"
  test -s "$work/support.dump"
  docker compose exec -T support_db pg_restore --list < "$work/support.dump" >/dev/null
  docker compose run --rm --no-deps -T --entrypoint tar support_pro -czf - -C /data/uploads . > "$work/support-uploads.tar.gz"
fi
for archive in "$work"/*.tar.gz; do tar -tzf "$archive" >/dev/null; done
# Every environment file is sensitive. Include it only inside the encrypted
# bundle, with root-relative paths; never print its contents or source it.
python3 - "$work" <<'PY'
import hashlib,json,os,tarfile,sys
from pathlib import Path
folder=Path(sys.argv[1]); root=Path.cwd()
with tarfile.open(folder/'environment.tar.gz','w:gz') as archive:
    for base,dirs,files in os.walk(root):
        dirs[:]=[d for d in dirs if d not in {'.git','.rollback','node_modules','.venv','venv'}]
        for name in files:
            source=Path(base)/name
            if (name=='.env' or name.startswith('.env.')) and source.is_file() and not source.is_symlink():
                archive.add(source,source.relative_to(root).as_posix(),recursive=False)
files={}
for p in folder.iterdir():
    if p.is_file():
        with p.open('rb') as stream:files[p.name]=hashlib.file_digest(stream,'sha256').hexdigest()
version=json.loads((root/'release-manifest.template.json').read_text())['version']
(folder/'backup-manifest.json').write_text(json.dumps({'format':1,'source_version':version,'files':files},indent=2)+'\n')
PY
# Resume service before encryption. The captured databases/files are immutable.
if (( stopped )); then docker compose start "${writers[@]}"; stopped=0; fi
# A second backend container cannot start next to the running one: both want the fixed ingress address
# ("Address already in use"). Encrypt inside the running backend; a separate container only when it is down.
bundle(){
  if [[ $'\n'"$(docker compose ps --services --status running)"$'\n' == *$'\n'backend$'\n'* ]]; then
    docker compose exec -T -e BACKUP_BUNDLE_PASSWORD backend python /project/scripts/backup_bundle.py "$1"
  else
    docker compose run --rm --no-deps -T -e BACKUP_BUNDLE_PASSWORD --entrypoint python backend /project/scripts/backup_bundle.py "$1"
  fi
}
tar -C "$work" -cf - . | bundle encrypt > "$output"
bundle decrypt < "$output" | tar -tf - >/dev/null
(cd "$BACKUP_DEST" && sha256sum "$(basename "$output")") > "$output.sha256"
printf 'Зашифрованная копия: %s\nSHA256: %s.sha256\n' "$output" "$output"
