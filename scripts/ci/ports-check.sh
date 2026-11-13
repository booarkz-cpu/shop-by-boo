#!/usr/bin/env bash
# v28.134.0 (owner's task of 2026-11-13): the ports script of backend/app/rw_ports.py for real, on the CI runner —
# a server with iptables closing INPUT and a server with an nftables input chain «policy drop», each in a network
# namespace with a web server behind the firewall. Open → reachable; scan sees it; reboot (rules lost) → reapply
# brings it back; close → unreachable again; the SSH port is never closed. Needs root.
set -euo pipefail
cd "$(dirname "$0")/../.."
W=$(mktemp -d)
fail() { echo "FAIL: $*"; exit 1; }
ok() { echo "ok: $*"; }
PYTHONPATH=backend APP_ENV=test MEDIA_DIR=/tmp/media BACKUP_DIR=/tmp/backups APP_SECRET=x python3 -c 'from app import rw_ports; open("'"$W"'/node.sh", "w").write(rw_ports.NODE)'
cleanup() { for ns in cfw cnf; do ip netns pids "$ns" 2>/dev/null | xargs -r kill 2>/dev/null || true; ip netns del "$ns" 2>/dev/null || true; done; }
trap cleanup EXIT

mkns() {  # mkns <name> <subnet octet>
  ip netns add "$1"; ip link add "v$1" type veth peer name eth0 netns "$1"
  ip addr add "10.$2.0.1/24" dev "v$1"; ip link set "v$1" up
  ip netns exec "$1" ip addr add "10.$2.0.2/24" dev eth0; ip netns exec "$1" ip link set eth0 up; ip netns exec "$1" ip link set lo up
  ip netns exec "$1" bash -c 'cd /tmp && exec python3 -m http.server 8080 --bind 0.0.0.0' >/dev/null 2>&1 &
  sleep 1
}
node() { local ns=$1; shift; ip netns exec "$ns" bash -s -- "$@" < "$W/node.sh"; }
reach() { curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://10.$1.0.2:8080/" || true; }

# --- iptables (Ubuntu's iptables is iptables-nft: its table «ip filter» is left to iptables, not touched as nftables)
mkns cfw 91
ip netns exec cfw iptables -P INPUT DROP
ip netns exec cfw iptables -A INPUT -i lo -j ACCEPT
ip netns exec cfw iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
ip netns exec cfw iptables -A INPUT -p tcp --dport 22 -j ACCEPT
[ "$(reach 91)" = 000 ] && ok "iptables: the port is closed before" || fail "iptables: port open before"
out=$(node cfw scan); echo "$out"
echo "$out" | grep -qx "firewall iptables" && echo "$out" | grep -qx "allowed tcp 22" && echo "$out" | grep -q "^listen tcp 8080 python" \
  && ! echo "$out" | grep -q "^firewall nftables" && ok "scan: iptables, SSH allowed, the web server listening" || fail "scan iptables"
out=$(node cfw open tcp/8080,udp/8443); echo "$out"
[ "$(echo "$out" | tail -1)" = "ports=open" ] && [ "$(reach 91)" = 200 ] && ok "iptables: opened and reachable" || fail "iptables open"
sc=$(node cfw scan); echo "$sc" | grep -qx "opened tcp/8080" && echo "$sc" | grep -qx "allowed tcp 8080" && ok "scan shows the port as opened by the shop" || fail "scan after open"
node cfw open tcp/8080 >/dev/null
[ "$(ip netns exec cfw iptables -S INPUT | grep -c 'corgi-ports')" = 2 ] && ok "opening twice adds no second rule" || { ip netns exec cfw iptables -S INPUT; fail "duplicate rule"; }
# A reboot: iptables forgets; the boot unit's «reapply» puts the rules back.
ip netns exec cfw iptables -D INPUT -p tcp --dport 8080 -m comment --comment corgi-ports -j ACCEPT
[ "$(reach 91)" = 000 ] || fail "rule not removed for the reboot test"
ip netns exec cfw bash /usr/local/sbin/corgi-ports.sh reapply >/dev/null
[ "$(reach 91)" = 200 ] && ok "after a «reboot» the rules come back (reapply)" || fail "reapply"
[ -f /etc/systemd/system/corgi-ports.service ] && systemctl is-enabled corgi-ports.service >/dev/null && ok "the boot unit is installed and enabled" || fail "boot unit"
rc=0; node cfw close tcp/22 >/dev/null || rc=$?
[ "$rc" = 3 ] && ip netns exec cfw iptables -S INPUT | grep -q -- '--dport 22 -j ACCEPT' && ok "the SSH port is refused" || fail "ssh close ($rc)"
rc=0; node cfw open tcp/70000 >/dev/null || rc=$?; [ "$rc" = 2 ] && ok "a bad port is refused" || fail "bad port ($rc)"
rc=0; node cfw open 'tcp/80;id' >/dev/null || rc=$?; [ "$rc" = 2 ] && ok "a bad argument is refused" || fail "bad argument ($rc)"
out=$(node cfw close tcp/8080); [ "$(reach 91)" = 000 ] && ! grep -qx tcp/8080 /etc/corgi/ports.list && ok "close: unreachable again and forgotten" || { echo "$out"; fail "close"; }
node cfw close udp/8443 >/dev/null
[ "$(ip netns exec cfw iptables -S INPUT | grep -c 'corgi-ports')" = 0 ] && ok "nothing of the shop left in iptables" || fail "rules left"

# --- nftables, an own input chain with policy drop
mkns cnf 92
ip netns exec cnf nft -f - <<'NFT'
table inet hostfw {
	chain input {
		type filter hook input priority 0; policy drop;
		iif lo accept
		ct state established,related accept
		tcp dport 22 accept
	}
}
NFT
[ "$(reach 92)" = 000 ] && ok "nftables: the port is closed before" || fail "nft port open before"
sc=$(node cnf scan); echo "$sc" | grep -qx "firewall nftables" && ok "scan: nftables" || fail "scan nft"
node cnf open tcp/8080 >/dev/null
[ "$(reach 92)" = 200 ] && ip netns exec cnf nft list chain inet hostfw input | grep -q 'comment "corgi-ports tcp/8080"' && ok "nftables: opened and reachable" || fail "nft open"
node cnf close tcp/8080 >/dev/null
[ "$(reach 92)" = 000 ] && ! ip netns exec cnf nft list ruleset | grep -q corgi-ports && ok "nftables: closed, the rule removed" || fail "nft close"
ip netns exec cnf nft list chain inet hostfw input | grep -q 'tcp dport 22 accept' && ok "the server's own rules are untouched" || fail "own rules"
rm -f /etc/corgi/ports.list
echo "ports module: PASS"
