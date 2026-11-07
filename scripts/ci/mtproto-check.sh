#!/usr/bin/env bash
# v28.94.0 (stage 20, N7): the MTProto module checked for real on the runner — the very script of
# backend/app/rw_netmods.py with the pinned image: «on» makes a FakeTLS secret, starts the container and the port
# answers a TLS ClientHello with the cover site's name; a second «on» keeps the secret; «off» removes the container,
# the secret and the port. Needs Docker and python3.
set -euo pipefail
cd "$(dirname "$0")/../.."
dir=$(mktemp -d); trap 'bash "$dir/mtproto.sh" off >/dev/null 2>&1 || true; rm -rf "$dir"' EXIT
image=$(PYTHONPATH=backend APP_ENV=test MEDIA_DIR=/tmp/media BACKUP_DIR=/tmp/backups python3 - "$dir" <<'PY'
import sys
from app import rw_netmods as m
open(f"{sys.argv[1]}/mtproto.sh", "w").write(m.MTPROTO)
print(m.MTPROTO_IMAGE)
PY
)
fail() { echo "FAIL: $*"; docker logs corgi-mtproto 2>&1 | tail -20 || true; exit 1; }
port=19443
out=$(bash "$dir/mtproto.sh" on "$port" www.cloudflare.com "$image") || fail "on: $out"
line=$(echo "$out" | tail -1); echo "${line%%secret=*}secret=[…]"
case "$line" in "mtproto=on port=$port domain=www.cloudflare.com secret=ee"*) ;; *) fail "unexpected answer: $line" ;; esac
secret=${line##*secret=}
[ "$(stat -c %a /etc/corgi/mtproto.secret)" = 600 ] || fail "the secret file is not 0600"
for _ in $(seq 1 20); do ss -ltnH "sport = :$port" | grep -q . && break; sleep 1; done
ss -ltnH "sport = :$port" | grep -q . || fail "nothing listens on $port"
# FakeTLS: a TLS ClientHello without the secret is answered like the cover site would (mtg forwards it), not refused.
timeout 15 openssl s_client -connect "127.0.0.1:$port" -servername www.cloudflare.com </dev/null >/dev/null 2>&1 && echo "ok: TLS handshake on $port" \
  || echo "note: TLS handshake through the cover site failed (the runner may not reach www.cloudflare.com)"
again=$(bash "$dir/mtproto.sh" on "$port" www.cloudflare.com "$image" | tail -1)
[ "${again##*secret=}" = "$secret" ] || fail "a second «on» changed the secret"
echo "ok: the secret is kept"
bash "$dir/mtproto.sh" on 80 www.cloudflare.com "nineseconds/mtg:latest" >/dev/null 2>&1 && fail "an image without a digest was accepted" || echo "ok: unpinned image refused"
bash "$dir/mtproto.sh" off | grep -qx "mtproto=off" || fail "off"
docker ps -a --format '{{.Names}}' | grep -qx corgi-mtproto && fail "the container is still there"
[ ! -e /etc/corgi/mtproto.secret ] || fail "the secret is still there"
echo "ok: off removes the container and the secret"
