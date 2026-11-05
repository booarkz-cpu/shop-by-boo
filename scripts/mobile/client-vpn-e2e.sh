#!/usr/bin/env bash
# v28.79.0: end-to-end test of «Корги Люси: клиент» (mobile/android-client) on an emulator (CI) — the same check as
# scripts/mobile/vpn-e2e.sh of the customer app: the subscription is imported, the app connects, the page behind the
# tunnel answers, the app disconnects.
#
# The host runs Xray (VLESS over TCP) and serves a subscription with that one server on http://10.0.2.2.
# The Xray server sends 198.18.0.42:80 — a benchmark address nobody answers — to a local page saying
# «corgi-tunnel-ok» (Xray blocks private addresses behind a VLESS inbound by default: «finalRules» allows exactly that
# one local port). So the page is reachable from the emulator only through the tunnel:
#   1. before connecting: no answer;  2. connected: «corgi-tunnel-ok»;  3. disconnected: no answer again.
#
#   bash scripts/mobile/client-vpn-e2e.sh <app-debug.apk> <xray binary>     (inside android-emulator-runner)
set -euo pipefail
APK="$(realpath "$1")"; XRAY="$(realpath "$2")"  # absolute: the script works in its own directory below
PKG="${CORGI_PKG:-shop.corgi.client.preview}"
WORK="${RUNNER_TEMP:-/tmp}/client-vpn-e2e"; mkdir -p "$WORK"; cd "$WORK"
UUID="$(cat /proc/sys/kernel/random/uuid)"
cat > xray.json <<JSON
{"log":{"loglevel":"warning"},
 "inbounds":[{"listen":"0.0.0.0","port":10086,"protocol":"vless","settings":{"clients":[{"id":"$UUID"}],"decryption":"none"},
              "streamSettings":{"network":"tcp","security":"none"}}],
 "outbounds":[{"tag":"direct","protocol":"freedom"},{"tag":"check","protocol":"freedom","settings":{"redirect":"127.0.0.1:18080","finalRules":[{"action":"allow","ip":["127.0.0.1"],"port":"18080"}]}}],
 "routing":{"rules":[{"type":"field","ip":["198.18.0.42"],"outboundTag":"check"}]}}
JSON
mkdir -p page sub
echo "corgi-tunnel-ok" > page/index.html
printf 'vless://%s@10.0.2.2:10086?encryption=none&type=tcp&security=none#corgi-ci' "$UUID" | base64 -w0 > sub/index.html
"$XRAY" run -c xray.json > xray.log 2>&1 &
python3 -m http.server 18080 --bind 127.0.0.1 --directory page > page.log 2>&1 &
python3 -m http.server 18081 --bind 0.0.0.0 --directory sub > sub.log 2>&1 &
trap 'kill $(jobs -p) 2>/dev/null || true; tail -n 20 xray.log >&2 || true; tail -n 5 page.log >&2 || true' EXIT
sleep 2
curl -fsS http://127.0.0.1:18081/ >/dev/null

# stdin stays open a few seconds: nc closes the connection at end of input, before a tunnelled answer arrives.
probe() { adb shell "(printf 'GET / HTTP/1.0\r\n\r\n'; sleep 4) | toybox nc -w 6 198.18.0.42 80 2>/dev/null" | tr -d '\r' || true; }
state() { adb shell "run-as $PKG cat shared_prefs/client_vpn.xml 2>/dev/null" | sed -n 's/.*name="state">\([a-z]*\)<.*/\1/p'; }

adb install -r "$APK" >/dev/null
adb shell appops set "$PKG" ACTIVATE_VPN allow
if probe | grep -q corgi-tunnel-ok; then echo "FAIL: the check page answers without the tunnel" >&2; exit 1; fi
echo "1/3 without the tunnel: no answer (as expected)"

adb shell am start -W -n "$PKG/shop.corgi.client.ui.MainActivity" --es client_test_import "http://10.0.2.2:18081/" --ez client_test_connect true >/dev/null
for i in $(seq 1 30); do [ "$(state)" = on ] && break; sleep 2; done
[ "$(state)" = on ] || { echo "FAIL: the VPN did not connect (state: $(state))" >&2; adb shell "run-as $PKG cat shared_prefs/client_vpn.xml" >&2 || true; exit 1; }
adb shell dumpsys connectivity | grep -q "VPN" || echo "note: dumpsys shows no VPN network"
ok=""; for i in $(seq 1 10); do if probe | grep -q corgi-tunnel-ok; then ok=1; break; fi; sleep 2; done
[ -n "$ok" ] || { echo "FAIL: connected, but the check page does not answer through the tunnel" >&2; exit 1; }
echo "2/3 connected: the page answers only the tunnel can reach"

adb shell am start -W -n "$PKG/shop.corgi.client.ui.MainActivity" --ez client_test_stop true >/dev/null
for i in $(seq 1 15); do [ "$(state)" = off ] && break; sleep 2; done
[ "$(state)" = off ] || { echo "FAIL: the VPN did not disconnect" >&2; exit 1; }
sleep 2
if probe | grep -q corgi-tunnel-ok; then echo "FAIL: the page still answers after disconnecting" >&2; exit 1; fi
echo "3/3 disconnected: no answer again"
echo "Corgi client VPN: PASS"
