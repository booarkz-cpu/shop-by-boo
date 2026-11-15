#!/bin/sh
# Restore drill in an isolated temporary database, never in POSTGRES_DB.
set -eu
umask 077
: "${POSTGRES_USER:?}"
: "${POSTGRES_PASSWORD:?}"
: "${1:?Usage: restore-check.sh /backups/snapshot-directory}"
export PGHOST="${PGHOST:-db}" PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD"
snapshot="$1"
(cd "$snapshot" && sha256sum -c SHA256SUMS)
drill_db="support_restore_check_$(date +%s)_$$"
createdb "$drill_db"
trap 'dropdb --if-exists "$drill_db"' EXIT INT TERM
pg_restore --exit-on-error --no-owner -d "$drill_db" "$snapshot/database.dump"
psql -v ON_ERROR_STOP=1 -d "$drill_db" -c 'SELECT count(*) FROM tickets; SELECT count(*) FROM messages; SELECT version_num FROM alembic_version;'
archive_index="$(mktemp)"
referenced_files="$(mktemp)"
trap 'dropdb --if-exists "$drill_db"; rm -f "$archive_index" "$referenced_files"' EXIT INT TERM
tar -tzf "$snapshot/uploads.tar.gz" > "$archive_index"
psql -v ON_ERROR_STOP=1 -At -d "$drill_db" -c "SELECT path FROM attachments WHERE state='ready' AND path<>''" > "$referenced_files"
while IFS= read -r attachment_path; do
  case "$attachment_path" in
    /data/uploads/*) relative="${attachment_path#/data/uploads/}" ;;
    *) printf 'Unexpected attachment path in restored DB\n' >&2; exit 1 ;;
  esac
  grep -Fx -- "./$relative" "$archive_index" >/dev/null || { printf 'Referenced attachment missing from backup\n' >&2; exit 1; }
done < "$referenced_files"
printf 'Restore drill passed: database restored and upload archive readable.\n'
