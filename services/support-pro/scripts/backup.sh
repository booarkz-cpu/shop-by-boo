#!/bin/sh
set -eu
umask 077
mkdir -p /backups
export PGDATABASE="$POSTGRES_DB" PGHOST=db PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD"
while true; do
  snapshot="/backups/support_$(date -u +%Y-%m-%d_%H-%M-%S)"
  mkdir "$snapshot.partial"
  # Files are immutable after upload. Dump first, then copy files; later files are harmless extras.
  if pg_dump -Fc -f "$snapshot.partial/database.dump" && tar -czf "$snapshot.partial/uploads.tar.gz" -C /data/uploads .; then
    (cd "$snapshot.partial" && sha256sum database.dump uploads.tar.gz > SHA256SUMS)
    if sh /restore-check.sh "$snapshot.partial"; then
      mv "$snapshot.partial" "$snapshot"
      date -u +%s > /backups/last_verified
    else
      printf 'Restore verification failed; snapshot retained as partial.\n' >&2
    fi
  else
    printf 'Backup failed; partial snapshot retained.\n' >&2
  fi
  sleep 86400
done
