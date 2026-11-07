#!/usr/bin/env bash
# v28.90.0 (stage 20, N5): the node's port is reachable only from the panel. Runs the very FIREWALL script of
# backend/app/rw_steps.py inside a «node» network namespace with two neighbours — «panel» (allowed) and «outsider»
# — and checks with real TCP connections: the panel connects to the node's port, the outsider does not, the
# outsider still reaches another port of the node, an extra address added later connects, and «delete» opens the
# port again. Needs root, iproute2, nftables and python3.
set -euo pipefail
cd "$(dirname "$0")/../.."
PORT=2222
script=$(mktemp); trap 'rm -f "$script"; for n in cpg-node cpg-panel cpg-out; do ip netns del $n 2>/dev/null || true; done' EXIT
PYTHONPATH=backend APP_ENV=test MEDIA_DIR=/tmp/media BACKUP_DIR=/tmp/backups python3 - "$script" <<'PY'
import sys
from app import rw_steps
open(sys.argv[1], "w").write(rw_steps.FIREWALL)
PY
for n in cpg-node cpg-panel cpg-out; do ip netns add $n; ip -n $n link set lo up; done
link() {  # namespace, node-side address, peer address
  ip link add "v-$1" type veth peer name "n-$1"
  ip link set "v-$1" netns "$1"; ip link set "n-$1" netns cpg-node
  ip -n "$1" addr add "$3/24" dev "v-$1"; ip -n "$1" link set "v-$1" up
  ip -n cpg-node addr add "$2/24" dev "n-$1"; ip -n cpg-node link set "n-$1" up
}
link cpg-panel 10.91.1.1 10.91.1.2
link cpg-out 10.91.2.1 10.91.2.2
for p in $PORT 8080; do ip netns exec cpg-node python3 -m http.server $p --bind 0.0.0.0 >/dev/null 2>&1 & done
sleep 1
can() {  # namespace, address, port → 0 if a TCP connection opens within 3 s
  ip netns exec "$1" python3 -c "import socket,sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), 3).close()" "$2" "$3" 2>/dev/null
}
expect() {  # yes|no, namespace, address, port, what
  if can "$2" "$3" "$4"; then got=yes; else got=no; fi
  [ "$got" = "$1" ] || { echo "FAIL: $5 (expected $1, got $got)"; ip netns exec cpg-node nft list ruleset || true; exit 1; }
  echo "ok: $5"
}
expect yes cpg-out 10.91.2.1 $PORT "before the rule anyone reaches the node's port"
ip netns exec cpg-node bash "$script" 10.91.1.2 $PORT add
expect yes cpg-panel 10.91.1.1 $PORT "the panel reaches the node's port"
expect no cpg-out 10.91.2.1 $PORT "an outsider does not reach the node's port"
expect yes cpg-out 10.91.2.1 8080 "other ports of the node stay as they were"
ip netns exec cpg-node bash "$script" 10.91.1.2,10.91.2.2/32 $PORT add
expect yes cpg-out 10.91.2.1 $PORT "an extra address (a panel move) reaches the port"
ip netns exec cpg-node bash "$script" 10.91.1.2 $PORT add
expect no cpg-out 10.91.2.1 $PORT "applying again replaces the list, it does not add to it"
ip netns exec cpg-node bash "$script" 10.91.1.2 $PORT delete
expect yes cpg-out 10.91.2.1 $PORT "«delete» opens the port again"
if ip netns exec cpg-node bash "$script" '10.91.1.2;id' $PORT add >/dev/null; then echo "FAIL: a bad address was accepted"; exit 1; fi
echo "node port guard: PASS"
