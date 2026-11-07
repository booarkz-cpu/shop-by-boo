"""Server modules of «Установка» (v28.92.0, stage 20, N7): MSS clamp, node guard (nftables), swap.

Closed scripts with typed arguments, like the other node modules (rw_steps): each keeps its own files under
/etc/corgi, survives a reboot through its own systemd unit and is removed completely by «off». None of them touches
ufw, fail2ban, CrowdSec or the table of «Порт ноды для панели»: every one has an nftables table of its own.

* mss_clamp — measures the path MTU (DF pings to Cloudflare 1.1.1.1 and Yandex DNS 77.88.8.8); when it is below the
  interface's MTU, outgoing TCP SYNs get the MSS that fits (table inet corgi_mss). The node is not restarted.
* node_guard — a limit of new connections per second from one address on the node's ports; who goes over it is
  banned for 10 minutes (table inet corgi_guard, dynamic sets with timeouts). The shop's address, the panel's, the
  administrator's and CGNAT (100.64.0.0/10 — many clients behind one address) are never limited. «observe» only counts.
* swap — a swap file of the chosen size (/swapfile.corgi) and vm.swappiness=10, after a check of free disk space.

scripts/ci/netmods-check.sh runs all three in network namespaces / a scratch root in CI.
"""
from __future__ import annotations

MSS = r"""set -eu
action="$1"; conf=/etc/corgi/mss.nft; unit=/etc/systemd/system/corgi-mss.service
systemd_on() { [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; }
off() {
  command -v nft >/dev/null 2>&1 && nft delete table inet corgi_mss 2>/dev/null || true
  if systemd_on; then systemctl disable corgi-mss.service >/dev/null 2>&1 || true; fi
  rm -f "$conf" "$unit"
}
case "$action" in
on)
  command -v nft >/dev/null 2>&1 || { DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nftables >/dev/null 2>&1 || { echo "nonft"; exit 7; }; }
  iface=$(ip route show default 2>/dev/null | awk '/^default/ {for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')
  [ -n "$iface" ] || { echo "noroute"; exit 5; }
  mtu=$(cat "/sys/class/net/$iface/mtu")
  best=0
  for host in ${MSS_HOSTS:-1.1.1.1 77.88.8.8}; do
    lo=1000; hi=$((mtu - 28)); ok=0
    while [ "$lo" -le "$hi" ]; do
      mid=$(((lo + hi) / 2))
      if ping -M do -s "$mid" -c 1 -W 1 "$host" >/dev/null 2>&1; then ok=$mid; lo=$((mid + 1)); else hi=$((mid - 1)); fi
    done
    if [ "$ok" -gt 0 ]; then p=$((ok + 28)); if [ "$best" -eq 0 ] || [ "$p" -lt "$best" ]; then best=$p; fi; fi
  done
  [ "$best" -gt 0 ] || { echo "nopath"; exit 6; }
  echo "iface=$iface mtu=$mtu path=$best"
  if [ "$best" -ge "$mtu" ]; then off; echo "clamp=not-needed"; exit 0; fi
  mss=$((best - 40))
  install -d -m 0755 /etc/corgi
  {
    echo "table inet corgi_mss {}"
    echo "delete table inet corgi_mss"
    echo "table inet corgi_mss {"
    echo "  chain postrouting {"
    echo "    type filter hook postrouting priority mangle; policy accept;"
    echo "    oifname \"$iface\" tcp flags syn tcp option maxseg size > $mss tcp option maxseg size set $mss"
    echo "  }"
    echo "}"
  } > "$conf.new"
  nft -c -f "$conf.new" || { rm -f "$conf.new"; echo "nft-syntax"; exit 7; }
  mv -f "$conf.new" "$conf"; nft -f "$conf"
  if systemd_on; then
    printf '[Unit]\nDescription=MSS clamp of the shop\nAfter=network-pre.target\n[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStart=%s -f %s\n[Install]\nWantedBy=multi-user.target\n' "$(command -v nft)" "$conf" > "$unit"
    systemctl daemon-reload; systemctl enable corgi-mss.service >/dev/null 2>&1 || true
  fi
  echo "clamp=$mss" ;;
off) off; echo "clamp=off" ;;
*) exit 2 ;;
esac
"""

GUARD = r"""set -eu
action="$1"; ports="${2:-}"; rate="${3:-150}"; allow="${4:--}"; mode="${5:-enforce}"
conf=/etc/corgi/guard.nft; unit=/etc/systemd/system/corgi-guard.service
systemd_on() { [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; }
case "$action" in
on)
  case "$ports" in ""|*[!0-9,]*) echo "bad ports"; exit 2 ;; esac
  case "$rate" in ""|*[!0-9]*) echo "bad rate"; exit 2 ;; esac
  case "$allow" in *[!0-9a-fA-F.:/,-]*) echo "bad address"; exit 2 ;; esac
  case "$mode" in enforce|observe) ;; *) exit 2 ;; esac
  command -v nft >/dev/null 2>&1 || { DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nftables >/dev/null 2>&1 || { echo "nonft"; exit 7; }; }
  v4="100.64.0.0/10, 127.0.0.0/8"; v6="::1/128"
  if [ "$allow" != "-" ]; then
    for ip in $(echo "$allow" | tr , ' '); do case "$ip" in *:*) v6="$v6, $ip" ;; *) v4="$v4, $ip" ;; esac; done
  fi
  burst=$((rate * 2)); p=$(echo "$ports" | sed 's/,/, /g')
  if [ "$mode" = enforce ]; then act4="add @banned4 { ip saddr } drop"; act6="add @banned6 { ip6 saddr } drop"; else act4=""; act6=""; fi
  install -d -m 0755 /etc/corgi
  {
    echo "table inet corgi_guard {}"
    echo "delete table inet corgi_guard"
    echo "table inet corgi_guard {"
    echo "  set allow4 { type ipv4_addr; flags interval; elements = { $v4 } }"
    echo "  set allow6 { type ipv6_addr; flags interval; elements = { $v6 } }"
    echo "  set flood4 { type ipv4_addr; flags dynamic; timeout 1m; }"
    echo "  set flood6 { type ipv6_addr; flags dynamic; timeout 1m; }"
    echo "  set banned4 { type ipv4_addr; flags dynamic,timeout; timeout 10m; }"
    echo "  set banned6 { type ipv6_addr; flags dynamic,timeout; timeout 10m; }"
    echo "  chain input {"
    echo "    type filter hook input priority -5; policy accept;"
    echo "    iifname \"lo\" accept"
    echo "    ip saddr @allow4 accept"
    echo "    ip6 saddr @allow6 accept"
    [ "$mode" = enforce ] && echo "    ip saddr @banned4 counter drop"
    [ "$mode" = enforce ] && echo "    ip6 saddr @banned6 counter drop"
    echo "    ct state new tcp dport { $p } add @flood4 { ip saddr limit rate over $rate/second burst $burst packets } counter $act4"
    echo "    ct state new tcp dport { $p } add @flood6 { ip6 saddr limit rate over $rate/second burst $burst packets } counter $act6"
    echo "  }"
    echo "}"
  } > "$conf.new"
  nft -c -f "$conf.new" || { rm -f "$conf.new"; echo "nft-syntax"; exit 7; }
  mv -f "$conf.new" "$conf"; nft -f "$conf"
  if systemd_on; then
    printf '[Unit]\nDescription=Node guard of the shop\nAfter=network-pre.target\n[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStart=%s -f %s\n[Install]\nWantedBy=multi-user.target\n' "$(command -v nft)" "$conf" > "$unit"
    systemctl daemon-reload; systemctl enable corgi-guard.service >/dev/null 2>&1 || true
  fi
  echo "guard=$mode ports=$ports rate=$rate" ;;
status)
  command -v nft >/dev/null 2>&1 && nft list table inet corgi_guard >/dev/null 2>&1 || { echo "guard=off"; exit 0; }
  b4=$(nft list set inet corgi_guard banned4 2>/dev/null | grep -o 'expires' | wc -l)
  b6=$(nft list set inet corgi_guard banned6 2>/dev/null | grep -o 'expires' | wc -l)
  over=$(nft list chain inet corgi_guard input 2>/dev/null | grep 'limit rate over' | grep -o 'packets [0-9]*' | awk '{s+=$2} END {print s+0}')
  echo "guard=on banned=$((b4 + b6)) over=$over" ;;
off)
  command -v nft >/dev/null 2>&1 && nft delete table inet corgi_guard 2>/dev/null || true
  if systemd_on; then systemctl disable corgi-guard.service >/dev/null 2>&1 || true; fi
  rm -f "$conf" "$unit"; echo "guard=off" ;;
*) exit 2 ;;
esac
"""

SWAP = r"""set -eu
action="$1"; size="${2:-0}"; file=${SWAP_FILE:-/swapfile.corgi}; tune=/etc/sysctl.d/99-corgi-swap.conf
case "$action" in
on)
  case "$size" in ""|*[!0-9]*) exit 2 ;; esac
  [ "$size" -ge 256 ] && [ "$size" -le 16384 ] || { echo "bad size"; exit 2; }
  if swapon --show=NAME --noheadings 2>/dev/null | grep -qx "$file"; then
    cur=$(( $(stat -c %s "$file") / 1048576 ))
    [ "$cur" -eq "$size" ] && { echo "swap=$file size=${size}M unchanged"; exit 0; }
    swapoff "$file"
  fi
  free_mb=$(df -Pm "$(dirname "$file")" | awk 'NR==2 {print $4}')
  have=0; [ -f "$file" ] && have=$(( $(stat -c %s "$file") / 1048576 ))
  [ $((free_mb + have)) -ge $((size + 1024)) ] || { echo "nospace free=${free_mb}M"; exit 5; }
  rm -f "$file"
  fallocate -l "${size}M" "$file" 2>/dev/null || dd if=/dev/zero of="$file" bs=1M count="$size" status=none
  chmod 600 "$file"; mkswap -q "$file" >/dev/null; swapon "$file"
  grep -q "^$file " /etc/fstab 2>/dev/null || echo "$file none swap sw 0 0" >> /etc/fstab
  printf 'vm.swappiness=10\nvm.vfs_cache_pressure=50\n' > "$tune"; sysctl -q -p "$tune" 2>/dev/null || true
  echo "swap=$file size=${size}M" ;;
off)
  if swapon --show=NAME --noheadings 2>/dev/null | grep -qx "$file"; then swapoff "$file"; fi
  if [ -f /etc/fstab ]; then grep -v "^$file " /etc/fstab > /etc/fstab.corgi.tmp || true; cat /etc/fstab.corgi.tmp > /etc/fstab; rm -f /etc/fstab.corgi.tmp; fi
  rm -f "$file" "$tune"; echo "swap=off" ;;
*) exit 2 ;;
esac
"""
