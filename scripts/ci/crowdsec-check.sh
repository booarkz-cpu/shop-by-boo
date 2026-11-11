#!/usr/bin/env bash
# v28.114.0 (master prompt v6, REQ-NODE-0020 / 0037): the CrowdSec module of «Установка» checked for real — the very
# script of backend/app/rw_netmods.py on the CI runner (Ubuntu, systemd):
#  * the engine and the nftables bouncer are installed from the official repository and both services run;
#  * the allowlist holds the addresses passed to the script;
#  * without the shared blocklist the engine does not talk to the Central API;
#  * a ban decision reaches nftables (the bouncer enforces it); «status» lists it, «unban» lifts it and it leaves nftables;
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
tr '\0' ' ' < "/proc/$(systemctl show -p MainPID --value crowdsec)/cmdline" | grep -q -- '-no-capi' || fail "the engine runs without -no-capi"
[ ! -s /etc/crowdsec/online_api_credentials.yaml ] || fail "Central API credentials stayed"
if cscli capi status >/dev/null 2>&1; then fail "the Central API is reachable although the shared blocklist is off"; else ok "no Central API without the shared blocklist"; fi
cscli bouncers list -o raw | tail -n +2 | grep -q . && ok "bouncer registered" || fail "bouncer not registered"

cscli decisions add --ip 192.0.2.77 --duration 5m --reason corgi-ci >/dev/null
found=0; for _ in $(seq 1 20); do if nft list ruleset 2>/dev/null | grep -q '192\.0\.2\.77'; then found=1; break; fi; sleep 2; done
[ "$found" = 1 ] && ok "a ban reaches nftables" || { nft list ruleset | head -40; fail "the ban did not reach nftables"; }
# v28.115.0: the panel's «показать блокировки» and «снять блокировку».
st=$(bash "$s" status); echo "$st" | grep -q '^ban 192\.0\.2\.77 | corgi-ci' && echo "$st" | tail -1 | grep -q '^crowdsec=on decisions=[1-9]' && ok "status lists the ban" || { echo "$st"; fail "status"; }
un=$(bash "$s" unban 192.0.2.77); echo "$un" | grep -q '^unbanned=192\.0\.2\.77$' && ! echo "$un" | grep -q '^ban 192\.0\.2\.77' && ok "unban lifts it" || { echo "$un"; fail "unban"; }
gone=0; for _ in $(seq 1 20); do if ! nft list ruleset 2>/dev/null | grep -q '192\.0\.2\.77'; then gone=1; break; fi; sleep 2; done
[ "$gone" = 1 ] && ok "the address leaves nftables" || fail "the address stayed in nftables"
rc=0; bash "$s" unban '1.2.3.4;id' >/dev/null 2>&1 || rc=$?; [ "$rc" = 2 ] && ok "a bad address is refused" || fail "bad address accepted ($rc)"

out2=$(bash "$s" on off 203.0.113.9,198.51.100.0/24) || fail "second run exited with $?"
[ "$(echo "$out2" | tail -1)" = "$(echo "$out" | tail -1)" ] && ok "a second run gives the same state" || fail "second run differs: $(echo "$out2" | tail -1)"

[ "$(bash "$s" off | tail -1)" = "crowdsec=off" ] || fail "off"
hash -r
if command -v cscli >/dev/null 2>&1 || dpkg -s crowdsec >/dev/null 2>&1; then dpkg -l | grep -i crowdsec || true; fail "the packages stayed"; fi
[ ! -e /etc/crowdsec ] && [ ! -e /var/lib/crowdsec ] && [ ! -e /etc/apt/sources.list.d/corgi-crowdsec.list ] && [ ! -e /etc/apt/keyrings/corgi-crowdsec.gpg ] \
  && [ ! -e /etc/systemd/system/crowdsec.service.d ] || fail "files stayed"
nft list ruleset 2>/dev/null | grep -q 'table ip crowdsec' && fail "the nftables table stayed" || ok "«off» removes everything"
bash "$s" off >/dev/null && ok "a second «off» is harmless"
rc=0; bash "$s" status >/dev/null 2>&1 || rc=$?; [ "$rc" = 8 ] && ok "status says «not installed» after removal" || fail "status after removal ($rc)"
echo "crowdsec module: PASS"
