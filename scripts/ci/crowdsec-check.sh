#!/usr/bin/env bash
# v28.114.0 (master prompt v6, REQ-NODE-0020 / 0037): the CrowdSec module of «Установка» checked for real — the very
# script of backend/app/rw_netmods.py on the CI runner (Ubuntu, systemd):
#  * the engine and the nftables bouncer are installed from the official repository and both services run;
#  * the allowlist holds the addresses passed to the script;
#  * without the shared blocklist the engine does not talk to the Central API;
#  * a ban decision reaches nftables (the bouncer enforces it);
#  * a second run changes nothing; «off» removes the packages, the repository, the key, the data and the tables.
# Needs root and network access to packagecloud.io.
set -euo pipefail
cd "$(dirname "$0")/../.."
dir=$(mktemp -d); trap 'rm -rf "$dir"' EXIT
PYTHONPATH=backend APP_ENV=test MEDIA_DIR=/tmp/media BACKUP_DIR=/tmp/backups python3 - "$dir" <<'PY'
import sys
from app import rw_netmods as m
open(f"{sys.argv[1]}/crowdsec.sh", "w").write(m.CROWDSEC)
PY
fail() { echo "FAIL: $*"; exit 1; }
ok() { echo "ok: $*"; }
s="$dir/crowdsec.sh"

out=$(bash "$s" on off 203.0.113.9,198.51.100.0/24) || { echo "$out" | tail -n 30; fail "install failed"; }
echo "$out" | tail -1
echo "$out" | tail -1 | grep -q '^crowdsec=on bouncer=nftables community=off collections=[1-9][0-9]* allow=2$' || fail "unexpected result line"
systemctl is-active --quiet crowdsec && systemctl is-active --quiet crowdsec-firewall-bouncer && ok "engine and bouncer are running" || fail "a service is down"
cscli allowlists inspect corgi | grep -q 203.0.113.9 && cscli allowlists inspect corgi | grep -q 198.51.100.0/24 && ok "allowlist holds the owner's addresses" || fail "allowlist"
cscli collections list -o raw | grep -q crowdsecurity/sshd && ok "SSH brute-force scenarios installed" || fail "no sshd collection"
if cscli capi status >/dev/null 2>&1; then fail "the engine talks to the Central API although the shared blocklist is off"; else ok "no Central API without the shared blocklist"; fi
cscli bouncers list -o raw | tail -n +2 | grep -q . && ok "bouncer registered" || fail "bouncer not registered"

cscli decisions add --ip 192.0.2.77 --duration 5m --reason corgi-ci >/dev/null
found=0; for _ in $(seq 1 20); do if nft list ruleset 2>/dev/null | grep -q '192\.0\.2\.77'; then found=1; break; fi; sleep 2; done
[ "$found" = 1 ] && ok "a ban reaches nftables" || { nft list ruleset | head -40; fail "the ban did not reach nftables"; }
# An allowlisted address is never banned by a scenario decision list: the engine refuses or drops it.
cscli decisions delete --ip 192.0.2.77 >/dev/null 2>&1 || true

out2=$(bash "$s" on off 203.0.113.9,198.51.100.0/24) || fail "second run exited with $?"
[ "$(echo "$out2" | tail -1)" = "$(echo "$out" | tail -1)" ] && ok "a second run gives the same state" || fail "second run differs: $(echo "$out2" | tail -1)"

[ "$(bash "$s" off | tail -1)" = "crowdsec=off" ] || fail "off"
! command -v cscli >/dev/null 2>&1 || fail "cscli stayed"
[ ! -e /etc/crowdsec ] && [ ! -e /var/lib/crowdsec ] && [ ! -e /etc/apt/sources.list.d/corgi-crowdsec.list ] && [ ! -e /etc/apt/keyrings/corgi-crowdsec.gpg ] \
  && [ ! -e /etc/systemd/system/crowdsec.service.d ] || fail "files stayed"
nft list ruleset 2>/dev/null | grep -q 'table ip crowdsec' && fail "the nftables table stayed" || ok "«off» removes everything"
bash "$s" off >/dev/null && ok "a second «off» is harmless"
echo "crowdsec module: PASS"
