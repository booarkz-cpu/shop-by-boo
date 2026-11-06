#!/usr/bin/env bash
# Restore drill (stage 19, C2): a running shop gets customers, a subscription, a payment, an administrator and a
# file; scripts/backup.sh makes the encrypted copy; then everything is lost — every volume and both .env files;
# the copy alone brings the shop back, and the drill checks that every table, the customer's subscription and
# payment, the administrator's sign-in and the file are exactly as before.
#
# Runs in CI after the stack is up (job «Containers» in ci.yml). Needs docker compose, jq, python3 and flock.
# The password is generated per run and never printed.
set -Eeuo pipefail
APP_DIR="${APP_DIR:-$PWD}"
cd "$APP_DIR"
work="${RUNNER_TEMP:-$(mktemp -d)}/restore-drill"
rm -rf "$work"
mkdir -p "$work/backups"
chmod 700 "$work"
BACKUP_BUNDLE_PASSWORD="drill-$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
export BACKUP_BUNDLE_PASSWORD
DRILL_ADMIN_PASSWORD="Drill-$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
export DRILL_ADMIN_PASSWORD
step(){ printf '\n== %s\n' "$*"; }
fail(){ echo "::error title=restore drill::$*"; exit 1; }

# Row counts of every table in both databases, one line per table: «db.table=count».
counts(){
  local query="SELECT string_agg(table_name||'='||(xpath('/row/c/text()', query_to_xml('SELECT count(*) AS c FROM public.'||quote_ident(table_name), false, true, '')))[1]::text, E'\n' ORDER BY table_name) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
  docker compose exec -T db psql -U vpnshop -d vpnshop -At -c "$query" | sed 's/^/shop./'
  docker compose exec -T support_db psql -U support -d support -At -c "$query" | sed 's/^/support./'
}

# The drill customer, subscription, payment and administrator as one line each (what a person would check).
records(){
  docker compose exec -T db psql -U vpnshop -d vpnshop -At -c "
    SELECT 'user', u.referral_code, u.wallet_balance FROM users u WHERE u.referral_code='DRILL-USER'
    UNION ALL SELECT 'subscription', s.lifecycle_status||' '||to_char(s.expires_at,'YYYY-MM-DD HH24:MI:SS')||' '||s.remnawave_uuid, s.device_limit_snapshot
      FROM subscriptions s JOIN users u ON u.id=s.user_id WHERE u.referral_code='DRILL-USER'
    UNION ALL SELECT 'payment', p.order_id||' '||p.status||' '||p.currency, p.amount FROM payments p WHERE p.order_id='drill-order-1'
    UNION ALL SELECT 'admin', a.email||' '||a.role||' '||md5(a.password_hash), 0 FROM admin_users a WHERE a.email='drill-admin@example.test'
    ORDER BY 1"
}

media_digest(){
  docker compose run --rm --no-deps -T --entrypoint sh backend -c 'sha256sum /data/media/drill/proof.txt' | awk '{print $1}'
}

admin_login(){
  docker compose exec -T -e DRILL_ADMIN_PASSWORD backend python - <<'PY'
import json, os, urllib.request
body = json.dumps({"email": "drill-admin@example.test", "password": os.environ["DRILL_ADMIN_PASSWORD"]}).encode()
request = urllib.request.Request("http://127.0.0.1:8000/api/admin/auth/login", data=body, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(request, timeout=20) as answer:
    data = json.load(answer)
assert answer.status == 200 and data.get("email") == "drill-admin@example.test" and data.get("role") == "admin", data
print("admin sign-in OK")
PY
}

step "1. A working shop gets data"
docker compose exec -T -e DRILL_ADMIN_PASSWORD backend python - <<'PY'
import asyncio, os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from app.config import settings
from app.models import AdminUser, Payment, Plan, Subscription, User
from app.security import hash_password

async def main():
    engine = create_async_engine(settings.database_url)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        user = User(referral_code="DRILL-USER", username="drill", wallet_balance=Decimal("123.45"))
        plan = Plan(name="Drill plan", price=Decimal("199"), duration_days=30, traffic_limit_gb=100, device_limit=3)
        db.add_all([user, plan])
        await db.flush()
        sub = Subscription(user_id=user.id, plan_id=plan.id, expires_at=datetime(2030, 1, 2, 3, 4, 5), lifecycle_status="active",
                           remnawave_uuid="drill-remote-uuid", traffic_limit_gb_snapshot=100, device_limit_snapshot=3)
        db.add(sub)
        await db.flush()
        db.add_all([Payment(user_id=user.id, subscription_id=sub.id, plan_id=plan.id, provider="sandbox", order_id="drill-order-1",
                            amount=Decimal("199.00"), currency="RUB", status="paid", fulfillment_status="completed",
                            idempotency_key="drill-idem-1"),
                    AdminUser(email="drill-admin@example.test", password_hash=hash_password(os.environ["DRILL_ADMIN_PASSWORD"]), role="admin")])
        await db.commit()
    await engine.dispose()
    folder = Path("/data/media/drill")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "proof.txt").write_text("Корги Люси restore drill " + datetime.utcnow().isoformat())
asyncio.run(main())
print("seeded")
PY
admin_login
backend_image="$(docker inspect --format '{{.Image}}' "$(docker compose ps -q backend)")"
[[ -n "$backend_image" ]] || fail "backend image not found"

step "2. Writers stop; what the shop holds is recorded"
docker compose stop backend worker bot support_pro support_worker
counts > "$work/counts.before"
records > "$work/records.before"
media_digest > "$work/media.before"
sha256sum .env support-pro/.env > "$work/env.before"
grep -q '^shop.users=' "$work/counts.before" || fail "no table counts"
test "$(wc -l < "$work/records.before")" = 4 || { cat "$work/records.before"; fail "the drill records were not all created"; }
echo "tables: $(wc -l < "$work/counts.before"), rows: $(awk -F= '{s+=$2} END {print s}' "$work/counts.before")"

step "3. The encrypted copy (scripts/backup.sh)"
APP_DIR="$APP_DIR" BACKUP_DEST="$work/backups" bash scripts/backup.sh
bundle="$(ls "$work"/backups/shop-*.vpb)"
(cd "$work/backups" && sha256sum -c "$(basename "$bundle").sha256")

step "4. Everything is lost: containers, every volume, both .env files"
docker compose down -v --remove-orphans
rm -f .env support-pro/.env
test ! -e .env

step "5. Restore from the copy alone"
umask 077
mkdir -p "$work/restore"
docker run --rm -i -e BACKUP_BUNDLE_PASSWORD -v "$APP_DIR/scripts:/s:ro" --entrypoint python "$backend_image" /s/backup_bundle.py decrypt \
  < "$bundle" > "$work/restore.tar" || { rm -f "$work/restore.tar"; fail "the copy could not be decrypted"; }
tar -xf "$work/restore.tar" -C "$work/restore"
python3 - "$work/restore" <<'PY'
import hashlib, json, sys
from pathlib import Path
folder = Path(sys.argv[1])
manifest = json.loads((folder / "backup-manifest.json").read_text())
for name, digest in manifest["files"].items():
    with (folder / name).open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == digest, name
print("manifest: %d files match, source %s" % (len(manifest["files"]), manifest["source_version"]))
PY
tar -xzf "$work/restore/environment.tar.gz" -C "$APP_DIR"
sha256sum -c "$work/env.before"
docker compose up -d --wait db support_db
docker compose run --rm volume_init  # fresh volumes belong to the non-root services again
docker compose exec -T db pg_restore --list < "$work/restore/shop.dump" > /dev/null
docker compose exec -T db pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error -U vpnshop -d vpnshop < "$work/restore/shop.dump"
docker compose exec -T support_db pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error -U support -d support < "$work/restore/support.dump"
docker compose run --rm --no-deps -T --entrypoint tar backend -xzf - -C /data/media < "$work/restore/media.tar.gz"
docker compose run --rm --no-deps -T --entrypoint tar backend -xzf - -C /data/app-packages < "$work/restore/app-packages.tar.gz"
docker compose run --rm --no-deps -T --entrypoint tar support_pro -xzf - -C /data/uploads < "$work/restore/support-uploads.tar.gz"

step "6. The shop holds exactly what it held"
counts > "$work/counts.after"
records > "$work/records.after"
media_digest > "$work/media.after"
diff -u "$work/counts.before" "$work/counts.after" || fail "table row counts differ after the restore"
diff -u "$work/records.before" "$work/records.after" || fail "the customer, subscription, payment or administrator differ"
diff -u "$work/media.before" "$work/media.after" || fail "the media file differs"
cat "$work/records.after"

step "7. The restored shop starts and the administrator signs in"
docker compose up -d --wait --wait-timeout 240 backend worker support_pro support_worker
admin_login
rm -rf "$work/restore" "$work/restore.tar"
unset BACKUP_BUNDLE_PASSWORD DRILL_ADMIN_PASSWORD
echo "RESTORE DRILL PASS"
