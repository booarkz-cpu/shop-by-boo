#!/usr/bin/env bash
# Disaster-recovery drill for CI (stage 19, C2). Runs in the «containers» job on the full compose stack:
# put known data in both databases and all file volumes, make a copy with scripts/backup.sh, destroy every
# volume, restore with scripts/restore.sh into the empty stack and check that everything came back.
# Also checks that a changed copy and a restore over a live database are refused.
set -Eeuo pipefail
cd "$(dirname "$0")/../.."
APP_DIR="$PWD"
DEST="${RUNNER_TEMP:-/tmp}/dr-drill"
SERVICES=(backend admin miniapp cabinet support_pro support_worker)
WRITERS=(backend support_pro support_worker)
BACKUP_BUNDLE_PASSWORD="drill-$(openssl rand -hex 12)"
export APP_DIR BACKUP_BUNDLE_PASSWORD
rm -rf "$DEST"; mkdir -p "$DEST"
fail(){ echo "::error title=DR drill::$*"; exit 1; }
step(){ echo "::group::$*"; }
done_step(){ echo "::endgroup::"; }

shop_sql(){ docker compose exec -T db psql -U vpnshop -d vpnshop -v ON_ERROR_STOP=1 -At "$@"; }
support_sql(){ docker compose exec -T support_db psql -U support -d support -v ON_ERROR_STOP=1 -At "$@"; }
# Row count of every table, one «table count» per line: the fingerprint compared before and after.
counts(){
  "$1" <<'SQL' | sort
SELECT format('SELECT %L || '' '' || count(*) FROM %I.%I', schemaname || '.' || tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1 \gexec
SQL
}
files(){ # service dir
  docker compose exec -T "$1" sh -c "cd '$2' && find . -type f -exec sha256sum {} + | sort -k2"
}

step 'Known data'
shop_sql -c "CREATE TABLE dr_drill(id int PRIMARY KEY, note text, amount numeric(12,2));
             INSERT INTO dr_drill SELECT g, 'row ' || g, g * 1.5 FROM generate_series(1, 777) g;" >/dev/null
support_sql -c "CREATE TABLE dr_drill(id int PRIMARY KEY); INSERT INTO dr_drill SELECT generate_series(1, 33);" >/dev/null
docker compose exec -T backend sh -c 'mkdir -p /data/media/drill && head -c 65536 /dev/urandom > /data/media/drill/banner.bin'
docker compose exec -T backend sh -c 'head -c 4096 /dev/urandom > /data/app-packages/drill.apk'
docker compose exec -T support_pro sh -c 'head -c 2048 /dev/urandom > /data/uploads/drill.bin'
counts shop_sql > "$DEST/shop.before"; counts support_sql > "$DEST/support.before"
files backend /data/media > "$DEST/media.before"; files backend /data/app-packages > "$DEST/packages.before"
files support_pro /data/uploads > "$DEST/uploads.before"
shop_sql -c 'SELECT version_num FROM alembic_version' > "$DEST/head.before"
grep -q '^public.dr_drill 777$' "$DEST/shop.before" || fail 'seed rows are missing'
echo "shop tables: $(wc -l < "$DEST/shop.before"), support tables: $(wc -l < "$DEST/support.before"), head: $(cat "$DEST/head.before")"
done_step

step 'Copy with scripts/backup.sh'
BACKUP_DEST="$DEST" bash scripts/backup.sh
bundle="$(ls "$DEST"/shop-*.vpb)"
[[ -f "$bundle.sha256" ]] || fail 'backup.sh made no SHA256 file'
docker compose ps --services --status running | grep -qx backend || fail 'backup.sh did not start the shop again'
done_step

step 'A changed copy is refused'
cp "$bundle" "$DEST/changed.vpb"; cp "$bundle.sha256" "$DEST/changed.vpb.sha256"
printf 'x' | dd of="$DEST/changed.vpb" bs=1 seek=100 conv=notrunc status=none
sed -i "s/$(basename "$bundle")/changed.vpb/" "$DEST/changed.vpb.sha256"
code=0; bash scripts/restore.sh "$DEST/changed.vpb" > "$DEST/changed.log" 2>&1 || code=$?
[[ $code == 3 ]] || { cat "$DEST/changed.log"; fail "a changed copy must be refused with code 3, got $code"; }
done_step

step 'Restore over a running shop is refused'
code=0; bash scripts/restore.sh "$bundle" > "$DEST/running.log" 2>&1 || code=$?
[[ $code == 4 ]] || { cat "$DEST/running.log"; fail "restore over a running shop must be refused with code 4, got $code"; }
docker compose stop "${WRITERS[@]}"
code=0; bash scripts/restore.sh "$bundle" > "$DEST/live.log" 2>&1 || code=$?
[[ $code == 5 ]] || { cat "$DEST/live.log"; fail "restore into a database with data must be refused with code 5, got $code"; }
done_step

step 'Lose everything'
docker compose down -v --remove-orphans
project="$(docker compose config --format json | jq -r .name)"
if docker volume ls -q | grep -q "^${project}_postgres_data$"; then fail 'volumes were not removed'; fi
docker compose up -d --wait db support_db
[[ "$(shop_sql -c "SELECT count(*) FROM pg_tables WHERE schemaname='public'")" == 0 ]] || fail 'the new database is not empty'
done_step

step 'Restore with scripts/restore.sh'
bash scripts/restore.sh "$bundle" | tee "$DEST/restore.log"
grep -q 'Secrets match this installation' "$DEST/restore.log" || fail 'secrets of the copy were not recognised'
docker compose up -d --wait --wait-timeout 240 "${SERVICES[@]}"
done_step

step 'Everything came back'
counts shop_sql > "$DEST/shop.after"; counts support_sql > "$DEST/support.after"
files backend /data/media > "$DEST/media.after"; files backend /data/app-packages > "$DEST/packages.after"
files support_pro /data/uploads > "$DEST/uploads.after"
shop_sql -c 'SELECT version_num FROM alembic_version' > "$DEST/head.after"
for name in shop support media packages uploads head; do
  diff -u "$DEST/$name.before" "$DEST/$name.after" || fail "$name differs after the restore"
done
[[ "$(shop_sql -c 'SELECT sum(amount) FROM dr_drill')" == "453379.50" ]] || fail 'restored amounts differ'
docker compose exec -T backend python -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)))"
# The restored shop writes again: a new row lands after the restored ones.
shop_sql -c "INSERT INTO dr_drill VALUES (778, 'after restore', 1)" >/dev/null
done_step
echo "::notice title=DR drill::copy made, all volumes destroyed, restored: $(wc -l < "$DEST/shop.after") shop tables, $(wc -l < "$DEST/support.after") Support Pro tables, $(wc -l < "$DEST/media.after") media files — identical"
rm -rf "$DEST"
