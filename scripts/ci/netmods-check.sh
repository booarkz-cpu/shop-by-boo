#!/usr/bin/env bash
# v28.92.0 (stage 20, N7): the server modules of «Установка» checked for real — the very scripts of
# backend/app/rw_netmods.py in network namespaces (and a swap file on the runner):
#  * node_guard: an outsider who opens new connections faster than the limit is banned; an allowed address is not;
#    «observe» only counts; «off» removes the table;
#  * mss_clamp: node → router → far host where the far link has MTU 1400: the script finds the path MTU and
#    clamps the MSS to 1360; «off» removes it;
#  * swap: a 256 MB swap file is created and switched on, «off» removes it (skipped where swapon is not allowed).
# Needs root, iproute2, nftables, python3.
set -euo pipefail
cd "$(dirname "$0")/../.."
dir=$(mktemp -d); trap 'for n in g-node g-ok g-out m-node m-rt m-far; do ip netns del $n 2>/dev/null || true; done; rm -rf "$dir"' EXIT
PYTHONPATH=backend APP_ENV=test MEDIA_DIR=/tmp/media BACKUP_DIR=/tmp/backups python3 - "$dir" <<'PY'
import sys
from app import rw_netmods as m
for name in ("GUARD", "MSS", "SWAP"):
    open(f"{sys.argv[1]}/{name.lower()}.sh", "w").write(getattr(m, name))
PY
fail() { echo "FAIL: $*"; exit 1; }
ok() { echo "ok: $*"; }

# ---- node guard
for n in g-node g-ok g-out; do ip netns add $n; ip -n $n link set lo up; done
pair() { ip link add "v-$1" type veth peer name "n-$1"; ip link set "v-$1" netns "$1"; ip link set "n-$1" netns "$4"
  ip -n "$1" addr add "$3/24" dev "v-$1"; ip -n "$1" link set "v-$1" up; ip -n "$4" addr add "$2/24" dev "n-$1"; ip -n "$4" link set "n-$1" up; }
pair g-ok 10.92.1.1 10.92.1.2 g-node
pair g-out 10.92.2.1 10.92.2.2 g-node
# A listener with a long queue that closes every connection: only the firewall can refuse one.
ip netns exec g-node python3 -c "
import socket
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('0.0.0.0', 443)); s.listen(4096)
while True:
    c, _ = s.accept(); c.close()
" >/dev/null 2>&1 &
sleep 1
burst() {  # namespace, address → how many of 60 quick connections opened
  ip netns exec "$1" python3 - "$2" <<'PY'
import socket, sys
n = 0
for _ in range(60):
    try:
        socket.create_connection((sys.argv[1], 443), 1).close(); n += 1
    except OSError:
        pass
print(n)
PY
}
ip netns exec g-node bash "$dir/guard.sh" on 443 5 10.92.1.2 enforce
[ "$(burst g-ok 10.92.1.1)" = 60 ] && ok "an allowed address is never limited" || fail "the allowed address was limited"
got=$(burst g-out 10.92.2.1); [ "$got" -lt 60 ] && ok "a flood is cut: $got of 60" || fail "no limit for the outsider"
ip netns exec g-node bash "$dir/guard.sh" status | grep -Eq "banned=[1-9]" && ok "the flooder is banned" || fail "no ban"
ip netns exec g-node bash "$dir/guard.sh" on 443 5 10.92.1.2 observe
[ "$(burst g-out 10.92.2.1)" = 60 ] && ok "«observe» only counts" || fail "«observe» blocked"
ip netns exec g-node bash "$dir/guard.sh" off
ip netns exec g-node nft list table inet corgi_guard >/dev/null 2>&1 && fail "the table stayed" || ok "«off» removes the table"
if ip netns exec g-node bash "$dir/guard.sh" on '443;id' 5 - enforce >/dev/null 2>&1; then fail "bad ports accepted"; fi

# ---- MSS clamp: node — router — far (MTU 1400 on the far link)
for n in m-node m-rt m-far; do ip netns add $n; ip -n $n link set lo up; done
ip link add m1 type veth peer name r1; ip link set m1 netns m-node; ip link set r1 netns m-rt
ip link add r2 type veth peer name f2; ip link set r2 netns m-rt; ip link set f2 netns m-far
ip -n m-node addr add 10.93.1.2/24 dev m1; ip -n m-node link set m1 up; ip -n m-node route add default via 10.93.1.1
ip -n m-rt addr add 10.93.1.1/24 dev r1; ip -n m-rt link set r1 up
ip -n m-rt addr add 10.93.2.1/24 dev r2; ip -n m-rt link set r2 mtu 1400; ip -n m-rt link set r2 up
ip -n m-far addr add 10.93.2.2/24 dev f2; ip -n m-far link set f2 mtu 1400; ip -n m-far link set f2 up; ip -n m-far route add default via 10.93.2.1
ip netns exec m-rt sysctl -q -w net.ipv4.ip_forward=1
out=$(ip netns exec m-node env MSS_HOSTS=10.93.2.2 bash "$dir/mss.sh" on)
echo "$out" | grep -q "clamp=1360" && ok "path MTU 1400 → MSS 1360" || fail "MSS: $out"
ip netns exec m-node nft list table inet corgi_mss | grep -q "maxseg size set 1360" && ok "the clamp rule is in place" || fail "no clamp rule"
ip netns exec m-node bash "$dir/mss.sh" off >/dev/null
ip netns exec m-node nft list table inet corgi_mss >/dev/null 2>&1 && fail "the MSS table stayed" || ok "«off» removes the clamp"

# ---- swap
if swapon --show >/dev/null 2>&1 && [ "$(id -u)" = 0 ]; then
  f="$dir/swapfile.corgi"
  if SWAP_FILE="$f" bash "$dir/swap.sh" on 256 2>"$dir/swap.err"; then
    swapon --show=NAME --noheadings | grep -qx "$f" && ok "swap file on" || fail "swap not active"
    SWAP_FILE="$f" bash "$dir/swap.sh" off >/dev/null
    [ ! -e "$f" ] && ! swapon --show=NAME --noheadings | grep -qx "$f" && ok "swap off and removed" || fail "swap stayed"
  else
    echo "skip: swapon is not allowed here ($(cat "$dir/swap.err" | head -1))"
  fi
fi
echo "server modules: PASS"
