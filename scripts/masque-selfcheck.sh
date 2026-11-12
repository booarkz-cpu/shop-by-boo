#!/usr/bin/env bash
# MASQUE self-check: the inbound and outbound built by backend/app/masque.py against a real Xray-core.
#
#   bash scripts/masque-selfcheck.sh [xray tag, default v26.11.9]
#
# Downloads the official Xray release, makes a certificate for node.example.com (trusted by the test client only),
# starts a MASQUE server and a client on loopback and fetches a page through the tunnel over HTTP/3 and over HTTP/2.
# A wrong password must fail. Needs root for one line in /etc/hosts, python3 with the backend's requirements, curl,
# openssl and unzip. Meant for a throw-away machine such as a CI runner; it is not part of the installer.
set -euo pipefail

TAG="${1:-v26.11.9}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
DOMAIN="node.example.com"
PORT=2087
say() { echo "x:1:1: $*"; }
cleanup() { pkill -P $$ >/dev/null 2>&1 || true; }
trap cleanup EXIT

cd "$WORK"
curl -fsSL -o xray.zip "https://github.com/XTLS/Xray-core/releases/download/${TAG}/Xray-linux-64.zip"
say "Xray ${TAG} sha256 $(sha256sum xray.zip | cut -c1-64)"
unzip -q xray.zip xray && chmod +x xray
say "$(./xray version | head -n1)"

openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 2 -keyout key.pem -out cert.pem \
  -subj "/CN=${DOMAIN}" -addext "subjectAltName=DNS:${DOMAIN}" >/dev/null 2>&1
grep -q " ${DOMAIN}\$" /etc/hosts || echo "127.0.0.1 ${DOMAIN}" | sudo tee -a /etc/hosts >/dev/null

ADDRESS="$(hostname -I | awk '{print $1}')"
PYTHONPATH="$ROOT/backend" ADDRESS="$ADDRESS" WORK="$WORK" DOMAIN="$DOMAIN" PORT="$PORT" python3 - <<'PY'
import json, os
from app import masque
work, domain, port = os.environ["WORK"], os.environ["DOMAIN"], int(os.environ["PORT"])
server = masque.inbound(domain, f"{work}/cert.pem", f"{work}/key.pem", [{"email": "u1@shop", "pass": "right"}], port=port)
# Xray's freedom outbound refuses private addresses on a server by default; the test page lives on this machine, so one target is allowed.
allow = {"action": "allow", "network": "tcp", "port": "8099", "ip": [os.environ["ADDRESS"]]}
json.dump({"log": {"loglevel": "info"}, "inbounds": [server], "outbounds": [{"protocol": "freedom", "settings": {"finalRules": [allow]}}]},
          open(f"{work}/server.json", "w"))
for name, http, password in (("h3", "h3", "right"), ("h2", "h2", "right"), ("bad", "h3", "wrong")):
    client = masque.outbound(domain, "u1@shop", password, port=port, http=http)
    # The test certificate is self-signed: the client is told to trust exactly it (a real node has a public certificate).
    client["streamSettings"]["tlsSettings"]["certificates"] = [{"usage": "verify", "certificateFile": f"{work}/cert.pem"}]
    socks = {"listen": "127.0.0.1", "port": 1080, "protocol": "socks", "settings": {"udp": True}}
    json.dump({"log": {"loglevel": "info"}, "inbounds": [socks], "outbounds": [client]}, open(f"{work}/client-{name}.json", "w"))
PY

for config in server client-h3 client-h2; do
  ./xray run -test -c "$config.json" >"$config.test.log" 2>&1 && say "config $config: accepted by Xray" || { say "config $config: REFUSED: $(tail -n 3 "$config.test.log" | tr '\n' ' ')"; exit 1; }
done

mkdir site && echo "corgi-masque-ok" > site/probe.txt
(cd site && python3 -m http.server 8099 --bind 0.0.0.0 >/dev/null 2>&1) &
./xray run -c server.json >server.log 2>&1 &
sleep 2

fetch() {  # fetch <client config name>: prints the page fetched through the tunnel, or nothing
  ./xray run -c "client-$1.json" >"client-$1.log" 2>&1 &
  local pid=$!
  sleep 2
  curl -fsS --max-time 15 --socks5-hostname 127.0.0.1:1080 "http://${ADDRESS}:8099/probe.txt" 2>"curl-$1.log" || true
  kill "$pid" >/dev/null 2>&1 || true
  wait "$pid" 2>/dev/null || true
}

failed=0
for http in h3 h2; do
  if [ "$(fetch "$http")" = "corgi-masque-ok" ]; then say "tunnel over $http: page fetched through MASQUE"
  else say "tunnel over $http: FAILED: $(grep -v "accepted\|started\|Reading" "client-$http.log" | tail -n 6 | tr '\n' ' ') $(tail -n 1 "curl-$http.log")"; failed=1; fi
done
if [ -z "$(fetch bad)" ]; then say "wrong password: refused"; else say "wrong password: ACCEPTED"; failed=1; fi
[ "$failed" = 0 ] || { say "server log: $(grep -v "Reading\|started" server.log | tail -n 8 | tr '\n' ' ')"; exit 1; }
say "MASQUE self-check passed"
