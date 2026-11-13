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
INNER_PORT = 12087          # Xray's MASQUE inbound, loopback (the MASQUE transport cannot listen on a unix socket)
API_PORT = 12086            # reserved: never offered as the public port
# Xray's API has no TCP port: it is a unix socket in a directory only the two containers see. A loopback port could
# be reached through the node's own VPN (the panel's Xray runs on the host network and an old core lets a customer
# connect to 127.0.0.1) — and the API has no password. The inbound stays on loopback: it asks for the secret path
# and a password itself.
RUN = "/run/masque"
API_SOCK = f"{RUN}/api.sock"
HAPROXY_SOCK = f"{RUN}/haproxy.sock"
LIMITS_MAP = "/maps/limits.map"
DEFAULT_PORT = masque.DEFAULT_PORT
# One IPv4 range of 65 thousand tunnel addresses. No IPv6 inside the tunnel: many nodes have no IPv6 route, and a
# client that was given an IPv6 address would send there what the node cannot deliver.
POOL = ("10.77.0.1/16",)
PREFIX = re.compile(r"^[a-z0-9]{16,40}\Z")
EMAIL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}\Z")

__all__ = ["XRAY_IMAGE", "HAPROXY_IMAGE", "NODE", "credentials", "new_prefix", "path", "server_config", "haproxy_cfg", "compose",
           "bundle", "client_config", "parse_result", "shield", "SHIELD_DEFAULT"]


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
        "api": {"tag": "api", "listen": API_SOCK, "services": ["HandlerService", "StatsService"]},
        "stats": {},
        "policy": {"levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True}}},
        "inbounds": [inbound],
        # freedom keeps Xray's default final rules: a tunnel user cannot reach the node's private networks.
        "outbounds": [{"tag": "direct", "protocol": "freedom"}, {"tag": "block", "protocol": "blackhole"}],
        "routing": {"rules": [{"type": "field", "protocol": ["bittorrent"], "outboundTag": "block"}]},
    }


# Protections against detection that the owner chooses when a node is installed (decision of 2026-11-12).
# The block counts refusals per address, and a client retries by itself, so the default threshold is not small;
# customers of one mobile operator can share an address — hence a short default term.
SHIELD_DEFAULT = {"strict_sni": True, "tls_like_site": True, "probe_ban": True, "ban_after": 30, "ban_minutes": 10}
# Caddy's (Go's) defaults, in its order: what a visitor of port 443 negotiates with the same site.
SITE_TLS13 = "TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256"
SITE_TLS12 = ("ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
              "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305")
SITE_CURVES = "X25519:P-256:P-384"
# What Go's net/http (Caddy) answers to a request it cannot parse — instead of HAProxy's own HTML page.
ERROR_400 = "HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain; charset=utf-8\r\nConnection: close\r\n\r\n400 Bad Request"


def shield(value: dict | None = None) -> dict:
    """The chosen protections, validated; anything missing takes the default."""
    raw = {**SHIELD_DEFAULT, **(value or {})}
    out = {key: bool(raw[key]) for key in ("strict_sni", "tls_like_site", "probe_ban")}
    try:
        out["ban_after"], out["ban_minutes"] = int(raw["ban_after"]), int(raw["ban_minutes"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Порог и срок блокировки — целые числа") from exc
    if not 5 <= out["ban_after"] <= 500:
        raise ValueError("Порог блокировки: от 5 до 500 отказов")
    if not 1 <= out["ban_minutes"] <= 1440:
        raise ValueError("Срок блокировки: от 1 минуты до суток")
    return out


def haproxy_cfg(domain: str, port: int, prefix: str, protections: dict | None = None) -> str:
    """The public side. Always: only an extended CONNECT to the secret path reaches Xray — any other request, the
    secret path included, is answered by the SelfSteal site; HAProxy's own error pages are replaced."""
    if not DOMAIN.match(domain) or not PREFIX.match(prefix):
        raise ValueError("Некорректные настройки MASQUE")
    port, opts = _port(port), shield(protections)
    tls = "ssl crt /tls/site.pem alpn h2,http/1.1" + (" strict-sni" if opts["strict_sni"] else "")
    site_tls = f"""	ssl-default-bind-options ssl-min-ver TLSv1.2
	ssl-default-bind-ciphersuites {SITE_TLS13}
	ssl-default-bind-ciphers {SITE_TLS12}
	ssl-default-bind-curves {SITE_CURVES}
""" if opts["tls_like_site"] else ""
    # HAProxy sees an HTTP/2 extended CONNECT (RFC 8441) as a request with «Upgrade: <protocol>»; that is what the
    # tunnel rule matches. A plain GET of the secret path has no such header and goes to the site.
    # A banned address keeps getting the site — also on the right path — so the ban cannot be seen from outside.
    # The entry lives ban_minutes after the address's last request.
    ban_track = f"""	stick-table type ipv6 size 100k expire {opts["ban_minutes"]}m store gpc1
	http-request track-sc0 src
	http-request sc-inc-gpc1(0) if {{ req.hdr(upgrade) -i connect-ip }} !{{ path_beg /{prefix}/ }}
""" if opts["probe_ban"] else ""
    ban_acl = f" !{{ sc0_get_gpc1 ge {opts['ban_after']} }}" if opts["probe_ban"] else ""
    ban_count = "	http-response sc-inc-gpc1(0) if { status 401 }\n" if opts["probe_ban"] else ""
    return f"""global
	log stdout format raw local0 notice
	stats socket {HAPROXY_SOCK} mode 600 level admin
{site_tls}defaults
	mode http
	log global
	timeout connect 5s
	timeout client 1h
	timeout server 1h
	timeout tunnel 1h
	timeout http-request 15s
	errorfile 400 /errors/400.http
	errorfile 408 /dev/null
	errorfile 500 /dev/null
	errorfile 502 /dev/null
	errorfile 503 /dev/null
	errorfile 504 /dev/null
frontend public
	bind :{port} {tls}
#V6#	bind :::{port} v6only {tls}
	http-request deny deny_status 400 if !{{ req.hdr(host) -m found }}
{ban_track}	acl tunnel req.hdr(upgrade) -i connect-ip
	acl secret path_beg /{prefix}/
	http-request track-sc1 http_auth_user table tunnels if tunnel secret
	http-request set-var(txn.limit) http_auth_user,map_str_int({LIMITS_MAP},0) if tunnel secret
	http-request set-var(txn.open) sc1_conn_cur if tunnel secret
	acl limited var(txn.limit) -m int gt 0
	acl too_many var(txn.open),sub(txn.limit) -m int gt 0
	use_backend site if tunnel secret limited too_many
	use_backend tunnel if tunnel secret{ban_acl}
	default_backend site
backend tunnels
	stick-table type string len 64 size 100k expire 1h store conn_cur
backend tunnel
{ban_count}	server xray 127.0.0.1:{INNER_PORT} ssl verify none alpn h2 sni str({domain})
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
    volumes: ["./xray:/usr/local/etc/xray:ro", "./tls/xray:/tls:ro", "./run:/run/masque:rw"]
  haproxy:
    image: {HAPROXY_IMAGE}
    container_name: corgi-masque-haproxy
    restart: always
    network_mode: host
    # root inside the container: the SelfSteal socket of the node's Caddy is writable by its owner only.
    user: "0:0"
    command: ["haproxy", "-W", "-db", "-f", "/usr/local/etc/haproxy/haproxy.cfg"]
    volumes: ["./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro", "./tls/haproxy:/tls:ro", "./errors:/errors:ro", "./maps:/maps:ro", "./run:/run/masque:rw",
              "/dev/shm:/dev/shm:rw"]
    depends_on: [xray]
"""


def limits_map(users: list[dict]) -> str:
    """``login limit`` per line: how many tunnels a login may hold at once (0 or absent: no limit)."""
    return "".join(f"{u['email']} {int(u.get('limit') or 0)}\n" for u in users if int(u.get("limit") or 0) > 0)


def bundle(domain: str, port: int, prefix: str, users: list[dict], protections: dict | None = None) -> bytes:
    """What the node script receives on stdin: a tar.gz with every file of the stack and the list of logins.
    A user may carry ``limit`` — the number of simultaneous tunnels (the plan's device limit)."""
    config = server_config(domain, users, prefix)
    files = {
        "config.json": json.dumps(config, ensure_ascii=False, separators=(",", ":")),
        "haproxy.cfg": haproxy_cfg(domain, port, prefix, protections),
        "docker-compose.yml": compose(),
        "400.http": ERROR_400,
        "limits.map": limits_map(users),
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
# status | traffic | off
# Exit codes: 2 bad arguments, 3 bad archive, 5 the node is not ready (no docker / no SelfSteal / no certificate),
# 6 the stack did not start, 7 the port is held by another program, 8 not installed.
NODE = r"""set -eu
action="$1"; domain="${2:-}"; port="${3:-0}"; sum="${4:-}"
dir=__DIR__; api=unix://__APISOCK__; xr=corgi-masque-xray; hp=corgi-masque-haproxy
certsh=/usr/local/sbin/corgi-masque-cert.sh; unit=/etc/systemd/system/corgi-masque-cert
xapi() { docker exec "$xr" /usr/local/bin/xray api "$@"; }
fw() {  # port on|off
  command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | head -1 | grep -q active || return 0
  if [ "$2" = on ]; then ufw allow "$1/tcp" >/dev/null; else ufw delete allow "$1/tcp" >/dev/null 2>&1 || true; fi
}
running() { [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = true ]; }
live() { xapi inbounduser -s "$api" -tag=__TAG__ 2>/dev/null | grep -o '"email": *"[^"]*"' | cut -d'"' -f4 | sort -u; }
# limits_apply <old map> <new map>: changes HAProxy's tunnel limits in place through its admin socket (no reload: a
# reload would leave an old process behind for as long as its tunnels live). Without python3 the new limits wait for
# the next restart of the container; the answer says which it was.
limits_apply() {
  command -v python3 >/dev/null 2>&1 || { echo pending; return 0; }
  python3 - "$1" "$2" "$dir/run/haproxy.sock" "__MAP__" <<'PY' || echo pending
import socket, sys
old, new, sock, name = sys.argv[1:5]
def read(path):
    try:
        return dict(line.split() for line in open(path) if len(line.split()) == 2)
    except OSError:
        return {}
a, b = read(old), read(new)
cmds = [f"del map {name} {k}" for k in a if k not in b]
cmds += [f"add map {name} {k} {v}" for k, v in b.items() if k not in a]
cmds += [f"set map {name} {k} {v}" for k, v in b.items() if k in a and a[k] != v]
for i in range(0, len(cmds), 50):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(5)
    s.connect(sock)
    s.sendall((";".join(cmds[i:i + 50]) + "\n").encode())
    while s.recv(4096):
        pass
    s.close()
print("applied")
PY
}
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
  for f in config.json haproxy.cfg docker-compose.yml users 400.http limits.map; do [ -f "$tmp/x/$f" ] || { echo "bad archive"; exit 3; }; done
  if [ "$action" = sync ]; then
    running "$xr" || { echo "not installed"; exit 8; }
    install -m 0640 -o 0 -g 65532 "$tmp/x/config.json" "$dir/xray/config.json.new"; mv -f "$dir/xray/config.json.new" "$dir/xray/config.json"
    sort -u "$tmp/x/users" > "$tmp/want"; live > "$tmp/live"
    comm -23 "$tmp/live" "$tmp/want" > "$tmp/drop"; comm -13 "$tmp/live" "$tmp/want" > "$tmp/add"
    if [ -s "$tmp/drop" ]; then xargs -r -n 50 docker exec "$xr" /usr/local/bin/xray api rmu -s "$api" -tag=__TAG__ < "$tmp/drop" >/dev/null 2>&1 || true; fi
    if [ -s "$tmp/add" ]; then xapi adu -s "$api" /usr/local/etc/xray/config.json >/dev/null 2>&1 || true; fi
    live > "$tmp/now"
    cmp -s "$tmp/now" "$tmp/want" || { echo "users differ after sync"; exit 6; }
    limits=same
    install -d -m 0755 "$dir/maps"
    if ! cmp -s "$tmp/x/limits.map" "$dir/maps/limits.map" 2>/dev/null; then
      limits=$(limits_apply "$dir/maps/limits.map" "$tmp/x/limits.map")
      install -m 0644 "$tmp/x/limits.map" "$dir/maps/limits.map"
    fi
    echo "masque=sync users=$(wc -l < "$tmp/want") added=$(wc -l < "$tmp/add") removed=$(wc -l < "$tmp/drop") limits=$limits"
    exit 0
  fi
  running remnawave-selfsteal || { echo "noselfsteal"; exit 5; }
  # Before anything is changed: the public port must be free — or held by this stack's own HAProxy (a reinstall).
  if command -v ss >/dev/null 2>&1; then
    holder=$(ss -Hltnp "sport = :$port" 2>/dev/null | grep -o 'users:(("[^"]*"' | cut -d'"' -f2 | grep -vx haproxy | head -n1 || true)
    [ -z "$holder" ] || { echo "port busy: $holder"; exit 7; }
  fi
  install -d -m 0755 "$dir" "$dir/xray" "$dir/tls" "$dir/maps"
  install -d -m 0770 -o 65532 -g 65532 "$dir/run"; rm -f "$dir/run"/*.sock
  install -m 0644 "$tmp/x/limits.map" "$dir/maps/limits.map"
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
  install -d -m 0755 "$dir/errors"; install -m 0644 "$tmp/x/400.http" "$dir/errors/400.http"
  install -m 0644 "$tmp/x/docker-compose.yml" "$dir/docker-compose.yml"
  cd "$dir"
  docker compose up -d --force-recreate --quiet-pull >/dev/null 2>&1 || { echo "compose failed"; docker compose logs --tail 20 2>&1 | tail -n 20; exit 6; }
  ok=0
  for i in $(seq 1 20); do
    if running "$xr" && running "$hp" && xapi inbounduser -s "$api" -tag=__TAG__ >/dev/null 2>&1 \
       && (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then ok=1; break; fi
    sleep 2
  done
  [ "$ok" = 1 ] || { echo "not started"; ls -l "$dir/run" 2>&1 | tail -n 5; xapi inbounduser -s "$api" -tag=__TAG__ 2>&1 | tail -n 2; docker compose logs --tail 20 2>&1 | tail -n 20; exit 6; }
  fw "$port" on
  echo "masque=on users=$(live | wc -l) port=$port cert=$(openssl x509 -in "$dir/tls/xray/cert.pem" -noout -enddate 2>/dev/null | cut -d= -f2 | tr ' ' '_')" ;;
status)
  running "$xr" && running "$hp" || { echo "not installed"; exit 8; }
  port=$(grep -m1 -o 'bind :[0-9]*' "$dir/haproxy.cfg" | cut -d: -f2)
  xapi statsquery -s "$api" -pattern "user>>>" 2>/dev/null | tr -d ' \n' | grep -o '"name":"user>>>[^"]*","value":[0-9]*' \
    | sed 's/"name":"user>>>\([^>]*\)>>>traffic>>>\([a-z]*\)","value":\([0-9]*\)/traffic \1 \2 \3/' || true
  echo "masque=on users=$(live | wc -l) port=$port cert=$(openssl x509 -in "$dir/tls/xray/cert.pem" -noout -enddate 2>/dev/null | cut -d= -f2 | tr ' ' '_')" ;;
traffic)
  # What every login moved since the previous call (the counters are reset by the call).
  running "$xr" || { echo "not installed"; exit 8; }
  xapi statsquery -s "$api" -pattern "user>>>" -reset 2>/dev/null | tr -d ' \n' | grep -o '"name":"user>>>[^"]*","value":[0-9]*' \
    | sed 's/"name":"user>>>\([^>]*\)>>>traffic>>>\([a-z]*\)","value":\([0-9]*\)/traffic \1 \2 \3/' || true
  echo "cert $(openssl x509 -in "$dir/tls/xray/cert.pem" -noout -enddate 2>/dev/null | cut -d= -f2 | tr ' ' '_')"
  echo "masque=traffic" ;;
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
""".replace("__DIR__", DIR).replace("__APISOCK__", API_SOCK).replace("__TAG__", TAG).replace("__MAP__", LIMITS_MAP)
