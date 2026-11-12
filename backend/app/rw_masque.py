"""MASQUE on a node, managed by the shop itself (the Remnawave panel does not know the protocol).

What stands on a node (``/opt/corgi-masque``, two containers on the host network):

* ``corgi-masque-xray`` — the official Xray image with one MASQUE inbound (HTTP/2, loopback only) and the gRPC API
  on loopback; users are added and removed through that API without a restart;
* ``corgi-masque-haproxy`` — the public TCP port with the certificate of the SelfSteal domain. A request to the
  secret path goes to Xray, everything else goes to the node's own SelfSteal site (the same unix socket REALITY
  hands foreign connections to), so a visitor of the port sees the site, its 404 page and its headers.

Checked for real by ``scripts/ci/masque-check.sh`` on a CI runner. Why HAProxy and HTTP/2 only: Xray's MASQUE
inbound has no fallback (any other path is a bare 404), Caddy does not pass an extended CONNECT of this kind, and
nothing can hand HTTP/3 datagrams over — so the masked variant is HTTP/2 over TCP.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import io
import json
import re
import tarfile

from . import masque
from .rw_plan import DOMAIN, SELFSTEAL_SOCKET

# Digests resolved on 2026-11-12 (docker buildx imagetools inspect).
XRAY_IMAGE = "ghcr.io/xtls/xray-core:26.11.9@sha256:9812e382e229e9ed63fd179bf1a4e3fe244c12ff3ae4fd8128745d79c87575ab"
HAPROXY_IMAGE = "haproxy:3.2-alpine@sha256:1c3568e520453cc8ba98c39501febcf450429c80e6cc27ecad779961d76e597c"
TAG = "MASQUE"
DIR = "/opt/corgi-masque"
INNER_PORT = 12087          # Xray's MASQUE inbound, loopback
API_PORT = 12086            # Xray's gRPC API, loopback
DEFAULT_PORT = masque.DEFAULT_PORT
# One IPv4 range of 65 thousand tunnel addresses. No IPv6 inside the tunnel: many nodes have no IPv6 route, and a
# client that was given an IPv6 address would send there what the node cannot deliver.
POOL = ("10.77.0.1/16",)
PREFIX = re.compile(r"^[a-z0-9]{16,40}\Z")
EMAIL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}\Z")

__all__ = ["XRAY_IMAGE", "HAPROXY_IMAGE", "NODE", "credentials", "new_prefix", "path", "server_config", "haproxy_cfg", "compose",
           "bundle", "client_config", "parse_result"]


def credentials(secret: str, key: str) -> tuple[str, str]:
    """Login and password of one subscription. Nothing is stored: both follow from the shop's secret and the
    subscription's own key, so they are the same after a restart and cannot be guessed from the login."""
    if not secret or not key:
        raise ValueError("Нужны секрет магазина и ключ подписки")
    digest = hmac.new(secret.encode(), f"masque:{key}".encode(), hashlib.sha256).digest()
    login = "m" + hashlib.sha256(f"masque-login:{key}".encode()).hexdigest()[:15]
    return login, base64.urlsafe_b64encode(digest[:24]).decode()


def new_prefix(secret: str, node: str) -> str:
    """The secret first segment of the tunnel path of one node (stable for the node, unknown to a visitor)."""
    return hmac.new(secret.encode(), f"masque-path:{node}".encode(), hashlib.sha256).hexdigest()[:24]


def path(prefix: str) -> str:
    if not PREFIX.match(prefix):
        raise ValueError("Некорректный секретный путь")
    return f"/{prefix}/{{target}}/{{ipproto}}/"


def _port(port: int) -> int:
    # Ports below 1024 belong to the node's own services (80, 443 and the panel's transports).
    if not 1024 <= int(port) <= 65535 or int(port) in (INNER_PORT, API_PORT):
        raise ValueError("Порт MASQUE: от 1024 до 65535")
    return int(port)


def server_config(domain: str, users: list[dict], prefix: str) -> dict:
    """The whole Xray config of the node's MASQUE container."""
    inbound = masque.inbound(domain, "/tls/cert.pem", "/tls/key.pem", users, tag=TAG, port=INNER_PORT, http=("h2",), path=path(prefix),
                             address=POOL)
    inbound["listen"] = "127.0.0.1"
    for user in inbound["settings"]["users"]:
        if not EMAIL.match(user["email"]):
            raise ValueError("Некорректный логин MASQUE")
    return {
        "log": {"loglevel": "warning"},
        "api": {"tag": "api", "listen": f"127.0.0.1:{API_PORT}", "services": ["HandlerService", "StatsService"]},
        "stats": {},
        "policy": {"levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True}}},
        "inbounds": [inbound],
        # freedom keeps Xray's default final rules: a tunnel user cannot reach the node's private networks.
        "outbounds": [{"tag": "direct", "protocol": "freedom"}, {"tag": "block", "protocol": "blackhole"}],
        "routing": {"rules": [{"type": "field", "protocol": ["bittorrent"], "outboundTag": "block"}]},
    }


def haproxy_cfg(domain: str, port: int, prefix: str) -> str:
    if not DOMAIN.match(domain) or not PREFIX.match(prefix):
        raise ValueError("Некорректные настройки MASQUE")
    port = _port(port)
    tls = "ssl crt /tls/site.pem alpn h2,http/1.1"
    return f"""global
	log stdout format raw local0 notice
defaults
	mode http
	log global
	timeout connect 5s
	timeout client 1h
	timeout server 1h
	timeout tunnel 1h
	timeout http-request 15s
frontend public
	bind :{port} {tls}
#V6#	bind :::{port} v6only {tls}
	use_backend tunnel if {{ path_beg /{prefix}/ }}
	default_backend site
backend tunnel
	server xray 127.0.0.1:{INNER_PORT} ssl verify none alpn h2 sni str({domain})
backend site
	http-request set-header Host {domain}
	server site unix@{SELFSTEAL_SOCKET} ssl verify none alpn h2,http/1.1 sni str({domain}) send-proxy
"""


def compose() -> str:
    return f"""services:
  xray:
    image: {XRAY_IMAGE}
    container_name: corgi-masque-xray
    restart: always
    network_mode: host
    command: ["run", "-c", "/usr/local/etc/xray/config.json"]
    volumes: ["./xray:/usr/local/etc/xray:ro", "./tls/xray:/tls:ro"]
  haproxy:
    image: {HAPROXY_IMAGE}
    container_name: corgi-masque-haproxy
    restart: always
    network_mode: host
    # root inside the container: the SelfSteal socket of the node's Caddy is writable by its owner only.
    user: "0:0"
    command: ["haproxy", "-W", "-db", "-f", "/usr/local/etc/haproxy/haproxy.cfg"]
    volumes: ["./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro", "./tls/haproxy:/tls:ro", "/dev/shm:/dev/shm:rw"]
    depends_on: [xray]
"""


def bundle(domain: str, port: int, prefix: str, users: list[dict]) -> bytes:
    """What the node script receives on stdin: a tar.gz with every file of the stack and the list of logins."""
    config = server_config(domain, users, prefix)
    files = {
        "config.json": json.dumps(config, ensure_ascii=False, separators=(",", ":")),
        "haproxy.cfg": haproxy_cfg(domain, port, prefix),
        "docker-compose.yml": compose(),
        "users": "".join(u["email"] + "\n" for u in config["inbounds"][0]["settings"]["users"]),
    }
    out = io.BytesIO()
    # mtime=0 everywhere: the same input gives the same bytes, so the same checksum.
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as packed, tarfile.open(fileobj=packed, mode="w") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o600, 0
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def client_config(domain: str, port: int, prefix: str, login: str, password: str, remark: str) -> dict:
    """A whole Xray client config for one node: what a JSON subscription consists of (v2rayNG, Happ, the shop's client)."""
    proxy = masque.outbound(domain, login, password, port=_port(port), http="h2", path=path(prefix), tag="proxy")
    return {
        "remarks": remark,
        "log": {"loglevel": "warning"},
        "dns": {"servers": ["1.1.1.1", "8.8.8.8"], "queryStrategy": "UseIPv4"},
        "inbounds": [
            {"tag": "socks", "listen": "127.0.0.1", "port": 10808, "protocol": "socks", "settings": {"udp": True},
             "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]}},
            {"tag": "http", "listen": "127.0.0.1", "port": 10809, "protocol": "http"},
        ],
        "outbounds": [proxy, {"tag": "direct", "protocol": "freedom"}, {"tag": "block", "protocol": "blackhole"}],
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": [{"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"}]},
    }


def parse_result(out: str) -> dict:
    """``masque=on users=3 port=2087 …`` — the last line of the node script as a dict."""
    line = (out or "").strip().splitlines()[-1] if (out or "").strip() else ""
    return dict(part.split("=", 1) for part in line.split() if "=" in part)


# on|sync <domain> <port> <sha256 of stdin>   — stdin: bundle()
# status | off
# Exit codes: 2 bad arguments, 3 bad archive, 5 the node is not ready (no docker / no SelfSteal / no certificate),
# 6 the stack did not start, 8 not installed.
NODE = r"""set -eu
action="$1"; domain="${2:-}"; port="${3:-0}"; sum="${4:-}"
dir=__DIR__; api=127.0.0.1:__API__; xr=corgi-masque-xray; hp=corgi-masque-haproxy
certsh=/usr/local/sbin/corgi-masque-cert.sh; unit=/etc/systemd/system/corgi-masque-cert
xapi() { docker exec "$xr" /usr/local/bin/xray api "$@"; }
fw() {  # port on|off
  command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | head -1 | grep -q active || return 0
  if [ "$2" = on ]; then ufw allow "$1/tcp" >/dev/null; else ufw delete allow "$1/tcp" >/dev/null 2>&1 || true; fi
}
running() { [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = true ]; }
live() { xapi inbounduser -s "$api" -tag=__TAG__ 2>/dev/null | grep -o '"email": *"[^"]*"' | cut -d'"' -f4 | sort -u; }
case "$action" in
on|sync)
  case "$domain" in *[!a-z0-9.-]*|"") echo "bad domain"; exit 2 ;; esac
  case "$port" in *[!0-9]*|"") echo "bad port"; exit 2 ;; esac
  [ "$port" -ge 1024 ] && [ "$port" -le 65535 ] || { echo "bad port"; exit 2; }
  case "$sum" in *[!0-9a-f]*) echo "bad sum"; exit 2 ;; esac
  [ "${#sum}" = 64 ] || { echo "bad sum"; exit 2; }
  command -v docker >/dev/null 2>&1 || { echo "nodocker"; exit 5; }
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  cat > "$tmp/b.tgz"
  [ "$(sha256sum "$tmp/b.tgz" | cut -d' ' -f1)" = "$sum" ] || { echo "bad archive"; exit 3; }
  mkdir "$tmp/x"; tar -xzf "$tmp/b.tgz" -C "$tmp/x" --no-same-owner
  for f in config.json haproxy.cfg docker-compose.yml users; do [ -f "$tmp/x/$f" ] || { echo "bad archive"; exit 3; }; done
  if [ "$action" = sync ]; then
    running "$xr" || { echo "not installed"; exit 8; }
    install -m 0640 -o 0 -g 65532 "$tmp/x/config.json" "$dir/xray/config.json.new"; mv -f "$dir/xray/config.json.new" "$dir/xray/config.json"
    sort -u "$tmp/x/users" > "$tmp/want"; live > "$tmp/live"
    comm -23 "$tmp/live" "$tmp/want" > "$tmp/drop"; comm -13 "$tmp/live" "$tmp/want" > "$tmp/add"
    if [ -s "$tmp/drop" ]; then xargs -r -n 50 docker exec "$xr" /usr/local/bin/xray api rmu -s "$api" -tag=__TAG__ < "$tmp/drop" >/dev/null 2>&1 || true; fi
    if [ -s "$tmp/add" ]; then xapi adu -s "$api" /usr/local/etc/xray/config.json >/dev/null 2>&1 || true; fi
    live > "$tmp/now"
    cmp -s "$tmp/now" "$tmp/want" || { echo "users differ after sync"; exit 6; }
    echo "masque=sync users=$(wc -l < "$tmp/want") added=$(wc -l < "$tmp/add") removed=$(wc -l < "$tmp/drop")"
    exit 0
  fi
  running remnawave-selfsteal || { echo "noselfsteal"; exit 5; }
  install -d -m 0755 "$dir" "$dir/xray" "$dir/tls"
  install -d -m 0750 -o 65532 -g 65532 "$dir/tls/xray"; install -d -m 0700 "$dir/tls/haproxy"
  cat > "$certsh" <<EOF
#!/bin/sh
# Copies the certificate of the SelfSteal domain from the node's Caddy for the MASQUE containers.
set -eu
t=$dir/tls
d=\$(docker exec remnawave-selfsteal sh -c 'find /data/caddy/certificates -type d -name "$domain" | head -n1')
[ -n "\$d" ] || exit 3
docker exec remnawave-selfsteal cat "\$d/$domain.crt" > \$t/cert.new
docker exec remnawave-selfsteal cat "\$d/$domain.key" > \$t/key.new
[ -s \$t/cert.new ] && [ -s \$t/key.new ] || exit 4
if [ -s \$t/xray/cert.pem ] && cmp -s \$t/cert.new \$t/xray/cert.pem && cmp -s \$t/key.new \$t/xray/key.pem; then rm -f \$t/cert.new \$t/key.new; exit 0; fi
cat \$t/cert.new \$t/key.new > \$t/haproxy/site.pem.new
install -m 0644 -o 65532 -g 65532 \$t/cert.new \$t/xray/cert.pem; install -m 0600 -o 65532 -g 65532 \$t/key.new \$t/xray/key.pem
chmod 0600 \$t/haproxy/site.pem.new; mv -f \$t/haproxy/site.pem.new \$t/haproxy/site.pem
rm -f \$t/cert.new \$t/key.new
docker kill -s HUP $hp >/dev/null 2>&1 || true
docker restart $xr >/dev/null 2>&1 || true
EOF
  chmod 0700 "$certsh"
  if [ -d /run/systemd/system ]; then
    printf '[Unit]\nDescription=Copy the SelfSteal certificate for MASQUE\n[Service]\nType=oneshot\nExecStart=%s\n' "$certsh" > "$unit.service"
    printf '[Unit]\nDescription=Daily copy of the SelfSteal certificate for MASQUE\n[Timer]\nOnCalendar=daily\nRandomizedDelaySec=1h\nPersistent=true\n[Install]\nWantedBy=timers.target\n' > "$unit.timer"
    systemctl daemon-reload; systemctl enable --now corgi-masque-cert.timer >/dev/null 2>&1 || true
  fi
  for i in $(seq 1 24); do "$certsh" 2>/dev/null && break; sleep 5; done
  [ -s "$dir/tls/xray/cert.pem" ] && [ -s "$dir/tls/haproxy/site.pem" ] || { echo "nocert"; exit 5; }
  install -m 0640 -o 0 -g 65532 "$tmp/x/config.json" "$dir/xray/config.json"
  if [ -e /proc/net/if_inet6 ]; then sed 's/^#V6#//' "$tmp/x/haproxy.cfg" > "$dir/haproxy.cfg"; else grep -v '^#V6#' "$tmp/x/haproxy.cfg" > "$dir/haproxy.cfg"; fi
  chmod 0644 "$dir/haproxy.cfg"
  install -m 0644 "$tmp/x/docker-compose.yml" "$dir/docker-compose.yml"
  cd "$dir"
  docker compose up -d --force-recreate --quiet-pull >/dev/null 2>&1 || { echo "compose failed"; docker compose logs --tail 20 2>&1 | tail -n 20; exit 6; }
  ok=0
  for i in $(seq 1 20); do
    if running "$xr" && running "$hp" && xapi inbounduser -s "$api" -tag=__TAG__ >/dev/null 2>&1 \
       && (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then ok=1; break; fi
    sleep 2
  done
  [ "$ok" = 1 ] || { echo "not started"; docker compose logs --tail 20 2>&1 | tail -n 20; exit 6; }
  fw "$port" on
  echo "masque=on users=$(live | wc -l) port=$port cert=$(openssl x509 -in "$dir/tls/xray/cert.pem" -noout -enddate 2>/dev/null | cut -d= -f2 | tr ' ' '_')" ;;
status)
  running "$xr" && running "$hp" || { echo "not installed"; exit 8; }
  port=$(grep -m1 -o 'bind :[0-9]*' "$dir/haproxy.cfg" | cut -d: -f2)
  xapi statsquery -s "$api" -pattern "user>>>" 2>/dev/null | tr -d ' \n' | grep -o '"name":"user>>>[^"]*","value":[0-9]*' \
    | sed 's/"name":"user>>>\([^>]*\)>>>traffic>>>\([a-z]*\)","value":\([0-9]*\)/traffic \1 \2 \3/' || true
  echo "masque=on users=$(live | wc -l) port=$port cert=$(openssl x509 -in "$dir/tls/xray/cert.pem" -noout -enddate 2>/dev/null | cut -d= -f2 | tr ' ' '_')" ;;
off)
  port=$(grep -m1 -o 'bind :[0-9]*' "$dir/haproxy.cfg" 2>/dev/null | cut -d: -f2 || true)
  if [ -f "$dir/docker-compose.yml" ] && command -v docker >/dev/null 2>&1; then (cd "$dir" && docker compose down --remove-orphans >/dev/null 2>&1) || true; fi
  if command -v docker >/dev/null 2>&1; then docker rm -f "$xr" "$hp" >/dev/null 2>&1 || true; fi
  if [ -d /run/systemd/system ]; then systemctl disable --now corgi-masque-cert.timer >/dev/null 2>&1 || true; fi
  rm -f "$unit.service" "$unit.timer" "$certsh"; rm -rf "$dir"
  if [ -d /run/systemd/system ]; then systemctl daemon-reload >/dev/null 2>&1 || true; fi
  [ -n "${port:-}" ] && fw "$port" off
  echo "masque=off" ;;
*) exit 2 ;;
esac
""".replace("__DIR__", DIR).replace("__API__", str(API_PORT)).replace("__TAG__", TAG)
