#!/usr/bin/env bash
# v28.129.0 (owner's task of 2026-11-12): MASQUE on a node behind the SelfSteal site, checked for real — the very
# script and files of backend/app/rw_masque.py on the CI runner (Ubuntu, Docker, systemd):
#  * the node's own SelfSteal Caddy runs as on a node (internal certificate), MASQUE is installed next to it;
#  * a visitor of the MASQUE port gets the SelfSteal site and its 404 page, also on a wrong and on the right «secret» path;
#  * protections against detection (v28.130.0): strict SNI, the site's TLS settings, no proxy error pages, an invisible
#    block of an address that tries wrong passwords — and the same node with the optional ones switched off;
#  * a real Xray client fetches a page through the tunnel; a wrong password and a private address are refused;
#  * a user is added and removed through the API without restarting Xray; the removed one is cut off;
#  * «status» reports users and traffic; a second «on» changes nothing; «off» removes everything.
# Needs root, Docker and network access (image pulls, the Xray release, one page fetched through the tunnel).
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$PWD; W=$(mktemp -d); DOMAIN=node.example.com; PORT=2087; SS=/opt/remnawave-selfsteal
fail() { echo "FAIL: $*"; exit 1; }
ok() { echo "ok: $*"; }
cleanup() { pkill -f "$W/xray" >/dev/null 2>&1 || true; pkill -f "http.server 8099" >/dev/null 2>&1 || true; }
trap cleanup EXIT
py() { PYTHONPATH="$ROOT/backend" APP_ENV=test MEDIA_DIR=/tmp/media BACKUP_DIR=/tmp/backups python3 "$@"; }

grep -q " $DOMAIN\$" /etc/hosts || echo "127.0.0.1 $DOMAIN" >> /etc/hosts
mkdir -p "$SS/sites/current"
echo '<!doctype html><title>Corgi bakery</title><h1>selfsteal-site-home</h1>' > "$SS/sites/current/index.html"
echo '<!doctype html><title>Not found</title><h1>selfsteal-site-404</h1>' > "$SS/sites/current/404.html"
py - "$SS" "$W" "$DOMAIN" <<'PY'
import sys
from app import rw_masque as m, rw_plan
ss, w, domain = sys.argv[1:4]
open(f"{ss}/Caddyfile", "w").write(rw_plan.selfsteal_caddyfile(domain, "internal", None))
open(f"{ss}/docker-compose.yml", "w").write(rw_plan.selfsteal_compose())
open(f"{w}/node.sh", "w").write(m.NODE)
PY
(cd "$SS" && docker compose up -d --quiet-pull >/dev/null 2>&1) || fail "SelfSteal Caddy did not start"
for _ in $(seq 1 30); do [ -S /dev/shm/selfsteal.sock ] && break; sleep 1; done
[ -S /dev/shm/selfsteal.sock ] && ok "the node's SelfSteal site is up" || fail "no SelfSteal socket"

bundle() {  # bundle <file> <login:password>...   (SHIELD=off: every optional protection switched off)
  py - "$DOMAIN" "$PORT" "${SHIELD:-on}" "$@" <<'PY'
import sys
from app import rw_masque as m
domain, port, mode, out, *users = sys.argv[1:]
prefix = m.new_prefix("ci-secret", "node-1")
shield = {"ban_after": 20, "ban_minutes": 1} if mode == "on" else {"strict_sni": False, "tls_like_site": False, "probe_ban": False}
open(out, "wb").write(m.bundle(domain, int(port), prefix, [dict(zip(("email", "pass"), u.split(":"))) for u in users], shield))
PY
}
node() { local action=$1 file=$2; bash "$W/node.sh" "$action" "$DOMAIN" "$PORT" "$(sha256sum "$file" | cut -d' ' -f1)" < "$file"; }
PREFIX=$(py -c 'from app import rw_masque as m; print(m.new_prefix("ci-secret", "node-1"))')

bundle "$W/b1.tgz" u1:pass-one
out=$(node on "$W/b1.tgz") || { echo "$out" | tail -n 25; fail "install failed"; }
echo "$out" | tail -1
echo "$out" | tail -1 | grep -q "^masque=on users=1 port=$PORT cert=" || fail "unexpected result line"
started=$(docker inspect -f '{{.State.StartedAt}}' corgi-masque-xray)
docker exec remnawave-selfsteal cat /data/caddy/pki/authorities/local/root.crt > "$W/root.crt"
[ -s "$W/root.crt" ] || fail "no root certificate"

get() { curl -sS --max-time 10 --cacert "$W/root.crt" "$@"; }
get "https://$DOMAIN:$PORT/" | grep -q 'selfsteal-site-home' && ok "the MASQUE port shows the SelfSteal site" || { get -i "https://$DOMAIN:$PORT/" | head -n 12 || true; docker logs --tail 12 corgi-masque-haproxy 2>&1; docker logs --tail 8 remnawave-selfsteal 2>&1 | cut -c1-400; fail "no site on the MASQUE port"; }
[ "$(get -o /dev/null -w '%{http_code}' "https://$DOMAIN:$PORT/no-such-page")" = 404 ] && get "https://$DOMAIN:$PORT/no-such-page" | grep -q 'selfsteal-site-404' \
  && ok "an unknown page is the site's own 404" || fail "unknown page is not the site's 404"
get "https://$DOMAIN:$PORT/aaaaaaaaaaaaaaaaaaaaaaaa/1/2/" | grep -q 'selfsteal-site-404' && ok "a wrong secret path is the site's 404 too" || fail "wrong secret path"
hdr=$(get -D - -o /dev/null "https://$DOMAIN:$PORT/")
echo "$hdr" | grep -qi '^strict-transport-security:' && ! echo "$hdr" | grep -qi '^server:' && ok "the site's headers, no Server header" || { echo "$hdr"; fail "headers"; }
[ "$(get -o /dev/null -w '%{http_version}' "https://$DOMAIN:$PORT/")" = 2 ] && ok "the port speaks HTTP/2" || fail "no HTTP/2"
get "https://$DOMAIN:$PORT/$PREFIX/1/2/" | grep -q 'selfsteal-site-404' && ok "a plain request to the real secret path is the site's 404 as well" || fail "the secret path answers differently"
# What a scanner sees. No server name: no certificate, so the domain is not revealed.
if echo | timeout 10 openssl s_client -connect "127.0.0.1:$PORT" -noservername 2>/dev/null | grep -q 'BEGIN CERTIFICATE'; then fail "a certificate is given without a server name"; else ok "no certificate without the server name (strict SNI)"; fi
echo | timeout 10 openssl s_client -connect "127.0.0.1:$PORT" -servername "$DOMAIN" 2>/dev/null | grep -q 'BEGIN CERTIFICATE' || fail "no certificate with the right server name"
# A request that cannot be parsed gets what Go's net/http (Caddy) answers, not HAProxy's HTML page.
bad=$(printf 'THIS IS NOT HTTP\r\n\r\n' | timeout 10 openssl s_client -quiet -connect "127.0.0.1:$PORT" -servername "$DOMAIN" 2>/dev/null || true)
echo "$bad" | grep -q '^400 Bad Request' && echo "$bad" | grep -qi '^content-type: text/plain; charset=utf-8' && ! echo "$bad" | grep -qi '<html' \
  && ok "a malformed request is answered like the site's server, not like a proxy" || { echo "$bad"; fail "malformed request reveals the proxy"; }
nohost=$(printf 'GET / HTTP/1.1\r\n\r\n' | timeout 10 openssl s_client -quiet -connect "127.0.0.1:$PORT" -servername "$DOMAIN" 2>/dev/null || true)
echo "$nohost" | head -n1 | grep -q '^HTTP/1.1 400 Bad Request' && ! echo "$nohost" | grep -qi '<html' && ok "a request without Host is refused the same way" || { echo "$nohost"; fail "request without Host"; }
if echo | timeout 10 openssl s_client -connect "127.0.0.1:$PORT" -servername "$DOMAIN" -tls1_1 2>/dev/null | grep -q 'BEGIN CERTIFICATE'; then fail "TLS 1.1 is accepted"; else ok "TLS below 1.2 is refused, as on the site"; fi
suite=$(echo | timeout 10 openssl s_client -connect "127.0.0.1:$PORT" -servername "$DOMAIN" -tls1_2 2>/dev/null | sed -n 's/^ *Cipher *: *//p' | head -n1)
case "$suite" in ECDHE-*-AES128-GCM-SHA256|ECDHE-*-AES256-GCM-SHA384|ECDHE-*-CHACHA20-POLY1305) ok "TLS 1.2 suite is one of the site's: $suite" ;; *) fail "unexpected TLS 1.2 suite: $suite" ;; esac
ss -ltn | grep -q "127.0.0.1:12087 " && ss -ltn | grep -q "127.0.0.1:12086 " && ok "Xray listens on loopback only" || { ss -ltn; fail "Xray is not on loopback"; }

curl -fsSL -o "$W/xray.zip" https://github.com/XTLS/Xray-core/releases/download/v26.11.9/Xray-linux-64.zip
(cd "$W" && unzip -q xray.zip && chmod +x xray)
client() {  # client <name> <login> <password> [private]
  py - "$W" "$DOMAIN" "$PORT" "$@" <<'PY'
import json, sys
from app import rw_masque as m
w, domain, port, name, login, password, *private = sys.argv[1:]
config = m.client_config(domain, int(port), m.new_prefix("ci-secret", "node-1"), login, password, "ci")
# The node's certificate here is Caddy's internal one: the test client trusts exactly its root.
config["outbounds"][0]["streamSettings"]["tlsSettings"]["certificates"] = [{"usage": "verify", "certificateFile": f"{w}/root.crt"}]
if private:
    config.pop("routing")          # send even a private address into the tunnel, to see the node refuse it
json.dump(config, open(f"{w}/client-{name}.json", "w"))
PY
}
through() {  # through <client name> <url>: HTTP code of the url fetched through the tunnel ("000" when it fails)
  "$W/xray" run -c "$W/client-$1.json" > "$W/client-$1.log" 2>&1 & local pid=$!
  sleep 2
  curl -s -o /dev/null -w '%{http_code}' --max-time 15 --socks5-hostname 127.0.0.1:10808 "$2" || true
  kill "$pid" >/dev/null 2>&1 || true; wait "$pid" 2>/dev/null || true
}
URL=https://www.gstatic.com/generate_204
client u1 u1 pass-one; client bad u1 wrong; client u2 u2 pass-two; client private u1 pass-one private
"$W/xray" run -test -c "$W/client-u1.json" >/dev/null 2>&1 && ok "the subscription config is accepted by a real Xray client" || fail "client config refused"
[ "$(through u1 $URL)" = 204 ] && ok "a page is fetched through the tunnel behind the site" || { tail -n 5 "$W/client-u1.log"; docker logs --tail 10 corgi-masque-xray; docker logs --tail 10 corgi-masque-haproxy; fail "tunnel"; }
[ "$(through bad $URL)" = 000 ] && ok "a wrong password is refused" || fail "wrong password accepted"
(cd "$SS/sites/current" && exec python3 -m http.server 8099 --bind 0.0.0.0 >/dev/null 2>&1) &
sleep 1
[ "$(through private "http://$(hostname -I | awk '{print $1}'):8099/index.html")" = 000 ] && ok "a tunnel user cannot reach the node's private address" || fail "private address reachable"
[ "$(through u2 $URL)" = 000 ] && ok "an unknown user is refused" || fail "unknown user accepted"

bundle "$W/b2.tgz" u1:pass-one u2:pass-two
out=$(node sync "$W/b2.tgz") || { echo "$out"; fail "sync failed"; }
[ "$(echo "$out" | tail -1)" = "masque=sync users=2 added=1 removed=0" ] && ok "a user is added: $(echo "$out" | tail -1)" || { echo "$out"; fail "sync add"; }
[ "$(docker inspect -f '{{.State.StartedAt}}' corgi-masque-xray)" = "$started" ] && ok "Xray was not restarted" || fail "Xray restarted on sync"
[ "$(through u2 $URL)" = 204 ] && ok "the new user gets a tunnel at once" || fail "new user has no tunnel"
bundle "$W/b3.tgz" u2:pass-two
out=$(node sync "$W/b3.tgz") || { echo "$out"; fail "sync failed"; }
[ "$(echo "$out" | tail -1)" = "masque=sync users=1 added=0 removed=1" ] && ok "a user is removed: $(echo "$out" | tail -1)" || { echo "$out"; fail "sync remove"; }
[ "$(through u1 $URL)" = 000 ] && ok "the removed user is cut off" || fail "removed user still has a tunnel"
[ "$(through u2 $URL)" = 204 ] && ok "the remaining user keeps working" || fail "remaining user lost the tunnel"
[ "$(node sync "$W/b3.tgz" | tail -1)" = "masque=sync users=1 added=0 removed=0" ] && ok "a second sync changes nothing" || fail "second sync"
grep -q '"u2"' /opt/corgi-masque/xray/config.json && ! grep -q '"u1"' /opt/corgi-masque/xray/config.json && ok "the saved config holds the same users (a restart keeps them)" || fail "saved config"

st=$(bash "$W/node.sh" status); echo "$st"
echo "$st" | tail -1 | grep -q "^masque=on users=1 port=$PORT cert=" || fail "status line"
echo "$st" | grep -q '^traffic u2 downlink [1-9]' && ok "status reports the user's traffic" || fail "no traffic in status"

# Probing: enough wrong passwords (the threshold here is 20 refusals; a client may retry by itself), and the address
# gets only the site — even with the right password.
[ "$(through u2 $URL)" = 204 ] || fail "the address is blocked before the threshold"
blocked=0
for n in $(seq 1 24); do through bad $URL >/dev/null; if [ "$(through u2 $URL)" = 000 ]; then blocked=$n; break; fi; done
[ "$blocked" -gt 0 ] && ok "after repeated wrong passwords ($blocked more attempts) the address is blocked from the tunnel" || fail "no block after wrong passwords"
get "https://$DOMAIN:$PORT/" | grep -q 'selfsteal-site-home' && ok "the blocked address still sees the site (the block cannot be seen)" || fail "blocked address lost the site"

out=$(node on "$W/b3.tgz") || fail "second install failed"
echo "$out" | tail -1 | grep -q "^masque=on users=1 port=$PORT cert=" && ok "a second «on» gives the same state" || fail "second on"
[ "$(through u2 $URL)" = 204 ] || fail "tunnel after the second on"
SHIELD=off bundle "$W/b4.tgz" u2:pass-two
node on "$W/b4.tgz" >/dev/null || fail "install without the optional protections failed"
echo | timeout 10 openssl s_client -connect "127.0.0.1:$PORT" -noservername 2>/dev/null | grep -q 'BEGIN CERTIFICATE' && ok "with strict SNI off the port answers without a server name" || fail "strict SNI could not be switched off"
for _ in $(seq 1 8); do through bad $URL >/dev/null; done
[ "$(through u2 $URL)" = 204 ] && ok "with the probing block off wrong passwords block nobody" || fail "block is on though switched off"
get "https://$DOMAIN:$PORT/$PREFIX/1/2/" | grep -q 'selfsteal-site-404' && ok "the always-on protections stay: the secret path is still the site's 404" || fail "always-on protections lost"
rc=0; bash "$W/node.sh" on 'bad;domain' 2087 "$(printf 'a%.0s' $(seq 64))" < /dev/null >/dev/null 2>&1 || rc=$?; [ "$rc" = 2 ] && ok "a bad domain is refused" || fail "bad domain ($rc)"
rc=0; bash "$W/node.sh" on "$DOMAIN" 443 "$(printf 'a%.0s' $(seq 64))" < /dev/null >/dev/null 2>&1 || rc=$?; [ "$rc" = 2 ] && ok "a port below 1024 is refused" || fail "low port ($rc)"
rc=0; bash "$W/node.sh" on "$DOMAIN" 2087 "$(printf 'a%.0s' $(seq 64))" < "$W/b3.tgz" >/dev/null 2>&1 || rc=$?; [ "$rc" = 3 ] && ok "a damaged archive is refused" || fail "bad archive ($rc)"

[ "$(bash "$W/node.sh" off | tail -1)" = "masque=off" ] || fail "off"
[ ! -e /opt/corgi-masque ] && [ ! -e /usr/local/sbin/corgi-masque-cert.sh ] && [ ! -e /etc/systemd/system/corgi-masque-cert.timer ] \
  && ! docker ps -a --format '{{.Names}}' | grep -q '^corgi-masque-' && ok "«off» removes everything" || fail "something stayed after off"
docker ps --format '{{.Names}}' | grep -q '^remnawave-selfsteal$' && ok "the SelfSteal site is untouched" || fail "SelfSteal stopped"
bash "$W/node.sh" off >/dev/null && ok "a second «off» is harmless"
rc=0; bash "$W/node.sh" status >/dev/null 2>&1 || rc=$?; [ "$rc" = 8 ] && ok "status says «not installed» after removal" || fail "status after removal ($rc)"
echo "masque module: PASS"
