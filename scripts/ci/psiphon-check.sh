#!/usr/bin/env bash
# v28.99.0 (stage 20, N7): psiphond checked for real on the runner — the very script of backend/app/rw_netmods.py builds
# psiphond from the pinned commit in the pinned Go image, generates the server's keys and runs it as a systemd service;
# then Psiphon's own ConsoleClient (built the same way) is given only this server's entry and must fetch a page through
# the tunnel. A second «on» keeps the keys; «off» removes the service, the user's files and the port. Needs root,
# systemd, Docker, python3, network.
set -euo pipefail
cd "$(dirname "$0")/../.."
dir=$(mktemp -d); trap 'bash "$dir/psiphon.sh" off >/dev/null 2>&1 || true; docker rm -f corgi-psiphon-client >/dev/null 2>&1 || true; rm -rf "$dir"' EXIT
read -r commit image < <(PYTHONPATH=backend APP_ENV=test MEDIA_DIR=/tmp/media BACKUP_DIR=/tmp/backups python3 - "$dir" <<'PY'
import sys
from app import rw_netmods as m
open(f"{sys.argv[1]}/psiphon.sh", "w").write(m.PSIPHON)
print(m.PSIPHON_COMMIT, m.PSIPHON_BUILDER)
PY
)
fail() { echo "FAIL: $*"; journalctl -u corgi-psiphon -n 30 --no-pager 2>/dev/null || true; exit 1; }
ip=$(hostname -I | awk '{print $1}')
port=19445
out=$(bash "$dir/psiphon.sh" on "$port" "$ip" "$commit" "$image" OSSH) || fail "on: $(echo "$out" | tail -5)"
line=$(echo "$out" | tail -1); echo "${line%%entry=*}entry=[…]"
case "$line" in "psiphon=on port=$port protocol=OSSH entry="*) ;; *) fail "unexpected answer" ;; esac
systemctl is-active --quiet corgi-psiphon || fail "the service is not active"
[ "$(stat -c %U /opt/corgi-psiphon/psiphond.config)" = corgi-psiphon ] || fail "the config is not the service user's"
[ "$(stat -c %a /opt/corgi-psiphon/server-entry.dat)" = 600 ] || fail "the server entry is not 0600"
echo "ok: psiphond built from $commit and running as corgi-psiphon"
PYTHONPATH=backend APP_ENV=test MEDIA_DIR=/tmp/media BACKUP_DIR=/tmp/backups python3 - "$line" "$dir/client.json" <<'PY'
import json, sys
from app import rw_netmods as m
client = m.psiphon_client(sys.argv[1])
assert client and client["port"] == 19445, client
json.dump(client["config"], open(sys.argv[2], "w"))
PY
# Psiphon's own client, from the same commit, knows only this server.
docker run -d --name corgi-psiphon-client --network host -e GOTOOLCHAIN=local -e CGO_ENABLED=0 -e GOFLAGS=-mod=vendor \
  -v "$dir/client.json:/client.json:ro" "$image" sh -ec '
  git clone -q --filter=blob:none https://github.com/Psiphon-Labs/psiphon-tunnel-core /src; cd /src; git checkout -q "$0"
  cd ConsoleClient; go build -trimpath -o /tmp/ConsoleClient .; mkdir -p /tmp/data; cd /tmp/data
  exec /tmp/ConsoleClient -config /client.json' "$commit" >/dev/null
ok=""
for i in $(seq 1 90); do
  if curl -fsS --max-time 10 --socks5-hostname 127.0.0.1:1080 -o /dev/null https://www.gstatic.com/generate_204 2>/dev/null; then ok=1; break; fi
  sleep 5
done
[ -n "$ok" ] || { docker logs --tail 40 corgi-psiphon-client 2>&1 | grep -v TargetServerEntry || true; fail "no page through the Psiphon tunnel"; }
echo "ok: a page through the tunnel of this psiphond (ConsoleClient with its server entry only)"
docker rm -f corgi-psiphon-client >/dev/null
entry=${line##*entry=}
again=$(bash "$dir/psiphon.sh" on "$port" "$ip" "$commit" "$image" OSSH | tail -1)
[ "${again##*entry=}" = "$entry" ] || fail "a second «on» changed the server's keys"
echo "ok: the keys are kept"
bash "$dir/psiphon.sh" on "$port" "$ip" "$commit" "golang:latest" >/dev/null 2>&1 && fail "an image without a digest was accepted" || echo "ok: unpinned image refused"
bash "$dir/psiphon.sh" off | grep -qx "psiphon=off" || fail "off"
systemctl is-active --quiet corgi-psiphon && fail "the service still runs"
[ ! -e /opt/corgi-psiphon ] || fail "the files are still there"
ss -ltnH "sport = :$port" | grep -q . && fail "the port still listens"
echo "ok: off removes the service, the files and the port"
