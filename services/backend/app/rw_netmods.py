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
* mtproto — a Telegram MTProto proxy (9seconds/mtg, MIT, image pinned by digest) with FakeTLS: to a censor the traffic
  looks like TLS to the chosen site. The secret is made once on the server (/etc/corgi/mtproto.secret, 0600) and kept
  until «off»; the container runs with --restart unless-stopped; ufw, when active, opens only its port.
* crowdsec — CrowdSec with the nftables bouncer from the official repository: bans SSH brute force and scanners;
  the owner's, the shop's and the panel's addresses are allowlisted first (v28.114.0).
* sni_scan — read-only: from the node, which well-known sites answer TLS 1.3 with HTTP/2 and how fast — candidates for
  the REALITY «dest» of a node without SelfSteal (nothing is changed on the server).

scripts/ci/netmods-check.sh runs all three in network namespaces / a scratch root in CI.
"""
from __future__ import annotations

import re

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

# v28.114.0 (master prompt v6, REQ-NODE-0020 / 0037): CrowdSec from its official repository (docs.crowdsec.net «Install on
# Linux», manual repository setup) with the nftables firewall bouncer. The administrator's, the shop's and the panel's
# addresses go to an allowlist first, so the owner is never banned from his own server. «community» — the shared
# blocklist of CrowdSec: with it the server reports attackers' addresses to CrowdSec; without it the engine runs with
# -no-capi and its Central API credentials are wiped (the package registers once while it installs). «off» purges the packages, the repository, the key and the data.
CROWDSEC = r"""set -eu
action="$1"; community="${2:-off}"; allow="${3:--}"
key=/etc/apt/keyrings/corgi-crowdsec.gpg; list=/etc/apt/sources.list.d/corgi-crowdsec.list; dropin=/etc/systemd/system/crowdsec.service.d
export DEBIAN_FRONTEND=noninteractive
off() {
  if command -v apt-get >/dev/null 2>&1; then
    systemctl stop crowdsec-firewall-bouncer crowdsec >/dev/null 2>&1 || true
    apt-get purge -y -qq crowdsec-firewall-bouncer-nftables crowdsec >/dev/null 2>&1 || true
  fi
  rm -rf /etc/crowdsec /var/lib/crowdsec "$key" "$list" "$dropin"
  if command -v nft >/dev/null 2>&1; then nft delete table ip crowdsec 2>/dev/null || true; nft delete table ip6 crowdsec6 2>/dev/null || true; fi
  if command -v systemctl >/dev/null 2>&1; then systemctl daemon-reload >/dev/null 2>&1 || true; fi
}
case "$action" in
on)
  case "$community" in on|off) ;; *) echo "bad community"; exit 2 ;; esac
  case "$allow" in *[!0-9a-fA-F.:/,-]*) echo "bad allow"; exit 2 ;; esac
  command -v apt-get >/dev/null 2>&1 && [ -d /run/systemd/system ] || { echo "unsupported"; exit 5; }
  apt-get update -qq >/dev/null 2>&1 || true
  apt-get install -y -qq curl gnupg ca-certificates nftables >/dev/null || { echo "apt failed"; exit 6; }
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL --retry 3 --retry-delay 2 https://packagecloud.io/crowdsec/crowdsec/gpgkey | gpg --dearmor --yes -o "$key" || { echo "no repository key"; exit 7; }
  echo "deb [signed-by=$key] https://packagecloud.io/crowdsec/crowdsec/any any main" > "$list"
  apt-get update -qq >/dev/null 2>&1 || true
  apt-get install -y -qq crowdsec crowdsec-firewall-bouncer-nftables >/dev/null || { echo "install failed"; exit 6; }
  cscli collections install crowdsecurity/linux crowdsecurity/sshd >/dev/null 2>&1 || true
  rm -rf "$dropin"
  if [ "$community" = off ]; then
    unit=$(systemctl show -p FragmentPath --value crowdsec); start=$(grep -m1 '^ExecStart=' "$unit" | cut -d= -f2-)
    [ -n "$start" ] || { echo "no unit"; exit 6; }
    install -d -m 0755 "$dropin"; printf '[Service]\nExecStart=\nExecStart=%s -no-capi\n' "$start" > "$dropin/corgi.conf"
    # The package registers the server with the Central API once, while it installs. The credentials are wiped,
    # so neither the engine nor cscli can send or fetch anything afterwards.
    : > /etc/crowdsec/online_api_credentials.yaml
  elif [ ! -s /etc/crowdsec/online_api_credentials.yaml ]; then
    cscli capi register >/dev/null 2>&1 || { echo "capi register failed"; exit 6; }
  fi
  systemctl daemon-reload; systemctl enable crowdsec crowdsec-firewall-bouncer >/dev/null 2>&1 || true
  systemctl restart crowdsec || true
  i=0; until cscli lapi status >/dev/null 2>&1; do i=$((i+1)); [ "$i" -le 30 ] || break; sleep 2; done
  n=0
  cscli allowlists delete corgi >/dev/null 2>&1 || true
  if [ "$allow" != "-" ]; then
    cscli allowlists create corgi -d "Corgi: administrator, shop and panel addresses" >/dev/null || { echo "allowlist failed"; exit 6; }
    for a in $(echo "$allow" | tr ',' ' '); do cscli allowlists add corgi "$a" >/dev/null && n=$((n+1)); done
  fi
  # The package registers the bouncer while the engine may still be starting, and then its key is refused
  # («API error: access forbidden»). A key of our own makes the result the same on every run.
  bconf=/etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml
  [ -f "$bconf" ] || { echo "no bouncer config"; exit 6; }
  cscli bouncers delete corgi-firewall >/dev/null 2>&1 || true
  bkey=$(cscli bouncers add corgi-firewall -o raw 2>/dev/null) && [ -n "$bkey" ] || { echo "bouncer key failed"; exit 6; }
  sed -i "s|^api_key:.*|api_key: $bkey|" "$bconf"; chmod 600 "$bconf"
  systemctl restart crowdsec-firewall-bouncer || true
  sleep 3
  for svc in crowdsec crowdsec-firewall-bouncer; do
    systemctl is-active --quiet "$svc" || { echo "$svc is not active"; journalctl -u "$svc" -n 15 --no-pager 2>/dev/null | tail -n 15; exit 6; }
  done
  echo "crowdsec=on bouncer=nftables community=$community collections=$(cscli collections list -o raw 2>/dev/null | tail -n +2 | wc -l) allow=$n" ;;
status|unban)
  # v28.115.0: what is banned now, and lifting a false ban — from the panel, without a shell on the server.
  command -v cscli >/dev/null 2>&1 || { echo "not installed"; exit 8; }
  if [ "$action" = unban ]; then
    ip="${2:-}"
    case "$ip" in ""|*[!0-9a-fA-F.:]*) echo "bad address"; exit 2 ;; esac
    cscli decisions delete --ip "$ip" >/dev/null 2>&1 || { echo "unban failed"; exit 6; }
    echo "unbanned=$ip"
  fi
  # id,source,ip,reason,action,country,as,events_count,expiration,simulated,alert_id — the newest 30, without the header.
  cscli decisions list -o raw 2>/dev/null | tail -n +2 | head -n 30 | awk -F, '{print "ban " $3 " | " $4 " | " $2 " | " $9}' | sed 's/^ban Ip:/ban /'
  echo "crowdsec=on decisions=$(cscli decisions list -o raw 2>/dev/null | tail -n +2 | wc -l)" ;;
off) off; echo "crowdsec=off" ;;
*) exit 2 ;;
esac
"""

# v28.94.0 (N7): 9seconds/mtg 2.x — https://github.com/9seconds/mtg (MIT). Digest from the «Resolve image digests» workflow (2026-11-07).
MTPROTO_IMAGE = "nineseconds/mtg:2@sha256:9553495b5216cbe6b238e88ce8a3d43ef582e4dc45fcdd7a14d54497500f5d4f"  # mtg v2.3.0

MTPROTO = r"""set -eu
action="$1"; port="${2:-}"; domain="${3:-}"; image="${4:-}"
secret_file=/etc/corgi/mtproto.secret; name=corgi-mtproto
ufw_on() { command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; }
off() {
  command -v docker >/dev/null 2>&1 && docker rm -f "$name" >/dev/null 2>&1 || true
  if [ -f /etc/corgi/mtproto.port ] && ufw_on; then ufw delete allow "$(cat /etc/corgi/mtproto.port)/tcp" >/dev/null 2>&1 || true; fi
  rm -f "$secret_file" /etc/corgi/mtproto.port
}
case "$action" in
on)
  case "$port" in ""|*[!0-9]*) echo "bad port"; exit 2 ;; esac
  [ "$port" -ge 1 ] && [ "$port" -le 65535 ] || { echo "bad port"; exit 2; }
  case "$domain" in ""|*[!a-z0-9.-]*) echo "bad domain"; exit 2 ;; esac
  case "$image" in nineseconds/mtg:*@sha256:*) ;; *) echo "bad image"; exit 2 ;; esac
  command -v docker >/dev/null 2>&1 || { echo "nodocker"; exit 7; }
  if ss -ltnH "sport = :$port" 2>/dev/null | grep -q . && ! docker ps --format '{{.Names}}' | grep -qx "$name"; then echo "busy"; exit 5; fi
  install -d -m 0755 /etc/corgi
  docker pull -q "$image" >/dev/null || { echo "nopull"; exit 6; }
  if [ ! -s "$secret_file" ] || [ "$(cat /etc/corgi/mtproto.domain 2>/dev/null)" != "$domain" ]; then
    secret=$(docker run --rm "$image" generate-secret --hex "$domain" | tr -d '[:space:]')
    case "$secret" in ee[0-9a-f]*) ;; *) echo "nosecret"; exit 6 ;; esac
    umask 077; printf '%s' "$secret" > "$secret_file"; printf '%s' "$domain" > /etc/corgi/mtproto.domain
  fi
  secret=$(cat "$secret_file")
  old=$(cat /etc/corgi/mtproto.port 2>/dev/null || true)
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" --restart unless-stopped --network host --read-only --cap-drop ALL --security-opt no-new-privileges \
    "$image" simple-run "0.0.0.0:$port" "$secret" >/dev/null
  if ufw_on; then
    [ -n "$old" ] && [ "$old" != "$port" ] && ufw delete allow "$old/tcp" >/dev/null 2>&1 || true
    ufw allow "$port/tcp" >/dev/null
  fi
  printf '%s' "$port" > /etc/corgi/mtproto.port
  sleep 2
  docker ps --format '{{.Names}}' | grep -qx "$name" || { docker logs --tail 20 "$name" 2>&1 | sed 's/ee[0-9a-f]\{20,\}/[secret]/g'; echo "norun"; exit 6; }
  echo "mtproto=on port=$port domain=$domain secret=$secret" ;;
off) off; echo "mtproto=off" ;;
*) exit 2 ;;
esac
"""


def mtproto_link(host: str, line: str) -> dict:
    """The script's last line → what the administrator gives to clients (tg:// and https://t.me links)."""
    fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
    if fields.get("mtproto") != "on" or not fields.get("secret"):
        return {}
    query = f"server={host}&port={fields['port']}&secret={fields['secret']}"
    return {"port": int(fields["port"]), "domain": fields.get("domain", ""), "tg": f"tg://proxy?{query}",
            "https": f"https://t.me/proxy?{query}"}


# v28.99.0 (N7, by the owner's request of 2026-11-07): psiphond — the Psiphon server (Psiphon-Labs/psiphon-tunnel-core,
# GPL-3.0) of the owner's own: built on the node from a pinned commit in a pinned Go image (no binary is downloaded),
# run as a systemd service under its own user. It is not the public Psiphon network: only clients given this server's
# entry (TargetServerEntry) connect. The files stay in /opt/corgi-psiphon (keys survive «on» again); «off» removes all.
PSIPHON_REPO = "https://github.com/Psiphon-Labs/psiphon-tunnel-core"
PSIPHON_COMMIT = "fc35a756e293fac716b3be55ead259c4eab4fe2b"  # master of 2026-11-06
PSIPHON_BUILDER = "golang:1.26-bookworm@sha256:5de7c99eb78ca5e515a4c340235d0955ec5964a5071c492c15503d7c267da473"  # go1.26.10 («Resolve image digests», 2026-11-07)
PSIPHON_PROTOCOLS = ("OSSH", "TLS-OSSH")

PSIPHON = r"""set -eu
action="$1"; port="${2:-}"; ip="${3:-}"; commit="${4:-}"; image="${5:-}"; proto="${6:-OSSH}"
d=/opt/corgi-psiphon; unit=/etc/systemd/system/corgi-psiphon.service
repo=https://github.com/Psiphon-Labs/psiphon-tunnel-core
ufw_on() { command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; }
case "$action" in
on)
  case "$port" in ""|*[!0-9]*) echo "bad port"; exit 2 ;; esac
  [ "$port" -ge 1024 ] && [ "$port" -le 65535 ] || { echo "bad port"; exit 2; }
  case "$ip" in ""|*[!0-9.]*) echo "bad ip"; exit 2 ;; esac
  echo "$commit" | grep -Eq '^[0-9a-f]{40}$' || { echo "bad commit"; exit 2; }
  case "$image" in golang:*@sha256:*) ;; *) echo "bad image"; exit 2 ;; esac
  case "$proto" in OSSH|TLS-OSSH) ;; *) echo "bad protocol"; exit 2 ;; esac
  command -v docker >/dev/null 2>&1 || { echo "nodocker"; exit 7; }
  if ss -ltnH "sport = :$port" 2>/dev/null | grep -q . && ! systemctl is-active --quiet corgi-psiphon; then echo "busy"; exit 5; fi
  install -d -m 0750 "$d"
  if [ ! -x "$d/psiphond" ] || [ "$(cat "$d/commit" 2>/dev/null)" != "$commit" ]; then
    docker run --rm -e GOTOOLCHAIN=local -e CGO_ENABLED=0 -e GOFLAGS=-mod=vendor -v "$d:/out" "$image" sh -ec '
      git clone -q --filter=blob:none "$0" /src; cd /src; git checkout -q "$1"; [ "$(git rev-parse HEAD)" = "$1" ]
      cd Server; go build -trimpath -ldflags "-s -w" -o /out/psiphond.new .' "$repo" "$commit" || { echo "nobuild"; exit 6; }
    mv -f "$d/psiphond.new" "$d/psiphond"; chmod 0755 "$d/psiphond"; printf '%s' "$commit" > "$d/commit"
  fi
  id corgi-psiphon >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin corgi-psiphon
  if [ ! -s "$d/server-entry.dat" ] || [ "$(cat "$d/listen" 2>/dev/null)" != "$ip $proto:$port" ]; then
    ( cd "$d" && rm -f psiphond.config psiphond-*.config server-entry.dat && ./psiphond --ipaddress "$ip" --protocol "$proto:$port" --web 0 generate >/dev/null )
    printf '%s' "$ip $proto:$port" > "$d/listen"
  fi
  chown -R corgi-psiphon "$d"; chmod 0600 "$d"/*.config "$d/server-entry.dat"
  printf '%s\n' "[Unit]" "Description=Psiphon server of the shop (psiphond)" "After=network-online.target" "[Service]" \
    "User=corgi-psiphon" "WorkingDirectory=$d" "ExecStart=$d/psiphond run" "Restart=always" "RestartSec=5" "NoNewPrivileges=yes" \
    "ProtectSystem=strict" "ReadWritePaths=$d" "ProtectHome=yes" "PrivateTmp=yes" "CapabilityBoundingSet=" "[Install]" \
    "WantedBy=multi-user.target" > "$unit"
  old=$(cat "$d/port" 2>/dev/null || true)
  systemctl daemon-reload; systemctl enable corgi-psiphon >/dev/null 2>&1; systemctl restart corgi-psiphon
  if ufw_on; then
    if [ -n "$old" ] && [ "$old" != "$port" ]; then ufw delete allow "$old/tcp" >/dev/null 2>&1 || true; fi
    ufw allow "$port/tcp" >/dev/null
  fi
  printf '%s' "$port" > "$d/port"
  for i in $(seq 1 15); do ss -ltnH "sport = :$port" | grep -q . && break; sleep 1; done
  ss -ltnH "sport = :$port" | grep -q . || { journalctl -u corgi-psiphon -n 20 --no-pager 2>/dev/null | tail -20; echo "norun"; exit 6; }
  echo "psiphon=on port=$port protocol=$proto entry=$(cat "$d/server-entry.dat")" ;;
off)
  systemctl disable --now corgi-psiphon >/dev/null 2>&1 || true
  rm -f "$unit"; systemctl daemon-reload || true
  if [ -f "$d/port" ] && ufw_on; then ufw delete allow "$(cat "$d/port")/tcp" >/dev/null 2>&1 || true; fi
  rm -rf "$d"; echo "psiphon=off" ;;
*) exit 2 ;;
esac
"""


def psiphon_client(line: str) -> dict:
    """The script's last line → the client config of ConsoleClient (and the Psiphon libraries) for this server only."""
    import secrets as _secrets
    fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
    entry = fields.get("entry", "")
    if fields.get("psiphon") != "on" or not re.fullmatch(r"[0-9a-f]{40,20000}", entry):
        return {}
    return {"port": int(fields["port"]), "protocol": fields.get("protocol", "OSSH"),
            "config": {"LocalSocksProxyPort": 1080, "LocalHttpProxyPort": 8080,
                       "PropagationChannelId": _secrets.token_hex(8).upper(), "SponsorId": _secrets.token_hex(8).upper(),
                       "TargetServerEntry": entry, "DisableRemoteServerListFetcher": True}}


SNI_CANDIDATES = ("www.microsoft.com", "www.apple.com", "dl.google.com", "www.samsung.com", "www.nvidia.com", "www.amd.com",
                  "www.intel.com", "www.cisco.com", "www.oracle.com", "www.ibm.com", "www.logitech.com", "www.asus.com",
                  "www.dell.com", "www.hp.com", "www.lenovo.com", "www.mozilla.org", "www.yahoo.com", "www.bing.com",
                  "gateway.icloud.com", "itunes.apple.com", "swdist.apple.com", "www.speedtest.net", "addons.mozilla.org",
                  "www.tesla.com", "www.sony.com", "www.xbox.com", "www.playstation.com", "www.adobe.com")

SNI_SCAN = r"""set -u
command -v openssl >/dev/null 2>&1 || { echo "noopenssl"; exit 7; }
for host in "$@"; do
  case "$host" in *[!a-z0-9.-]*) continue ;; esac
  start=$(date +%s%N)
  out=$(echo | timeout 6 openssl s_client -connect "$host:443" -servername "$host" -tls1_3 -alpn h2 2>/dev/null)
  ms=$(( ($(date +%s%N) - start) / 1000000 ))
  proto=$(printf '%s' "$out" | grep -m1 -o 'Protocol *: *TLSv1.3\|New, TLSv1.3' | head -1)
  alpn=$(printf '%s' "$out" | grep -m1 -o 'ALPN protocol: h2')
  group=$(printf '%s' "$out" | grep -m1 -io 'X25519[A-Za-z0-9]*' | head -1)
  if [ -n "$proto" ] && [ -n "$alpn" ]; then echo "ok $ms $host ${group:-?}"; else echo "no $ms $host"; fi
done
"""


def parse_sni(out: str) -> list[dict]:
    """The scan's lines → the fitting sites, fastest first."""
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "ok" and parts[1].isdigit():
            rows.append({"host": parts[2], "ms": int(parts[1]), "group": parts[3] if len(parts) > 3 else "?"})
    return sorted(rows, key=lambda r: r["ms"])
