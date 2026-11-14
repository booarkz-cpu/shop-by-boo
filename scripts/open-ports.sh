#!/usr/bin/env bash
# Open the host firewall for the test stand or a production VDS.
# test: TCP 18080-18083
# vds:  SSH, TCP 80, TCP 443, UDP 443
# Does not publish PostgreSQL, Redis, or the application port.
set -u

MODE="${1:-}"
case "$MODE" in
  test|vds) ;;
  *)
    echo "usage: bash scripts/open-ports.sh test|vds" >&2
    exit 2
    ;;
esac

if [[ "$(id -u)" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    exec sudo -n bash "$0" "$@"
  fi
  echo "open-ports: no root privileges, host firewall was left unchanged." >&2
  echo "open-ports: run later with: sudo bash scripts/open-ports.sh ${MODE}" >&2
  exit 0
fi

log() { printf 'open-ports: %s\n' "$*"; }

allow_ufw() {
  command -v ufw >/dev/null 2>&1 || return 0
  if [[ "$MODE" == "test" ]]; then
    ufw allow 18080:18083/tcp >/dev/null 2>&1 || true
    if ufw status 2>/dev/null | grep -qi 'Status: active'; then
      log "ufw allows TCP 18080-18083"
    else
      log "ufw is inactive; published Docker ports stay reachable without enabling it"
    fi
    return 0
  fi
  # SSH_ONLY_FROM: the installer limited SSH to the owner's address; opening OpenSSH here would undo that.
  [[ -n "${SSH_ONLY_FROM:-}" ]] || ufw allow OpenSSH >/dev/null 2>&1 || true
  ufw allow 80/tcp >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
  ufw allow 443/udp >/dev/null 2>&1 || true
  ufw --force enable >/dev/null 2>&1 || true
  log "ufw allows SSH, TCP 80/443 and UDP 443"
}

allow_firewalld() {
  command -v firewall-cmd >/dev/null 2>&1 || return 0
  firewall-cmd --state >/dev/null 2>&1 || return 0
  if [[ "$MODE" == "test" ]]; then
    firewall-cmd --permanent --add-port=18080-18083/tcp >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
    log "firewalld allows TCP 18080-18083"
    return 0
  fi
  [[ -n "${SSH_ONLY_FROM:-}" ]] || firewall-cmd --permanent --add-service=ssh >/dev/null 2>&1 || true
  firewall-cmd --permanent --add-service=http >/dev/null 2>&1 || true
  firewall-cmd --permanent --add-service=https >/dev/null 2>&1 || true
  firewall-cmd --permanent --add-port=443/udp >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
  log "firewalld allows SSH, TCP 80/443 and UDP 443"
}

allow_filter() {
  local bin="$1" proto="$2" port="$3"
  command -v "$bin" >/dev/null 2>&1 || return 0
  "$bin" -C INPUT -p "$proto" --dport "$port" -j ACCEPT >/dev/null 2>&1 || \
    "$bin" -I INPUT 1 -p "$proto" --dport "$port" -j ACCEPT >/dev/null 2>&1 || true
  if "$bin" -L DOCKER-USER >/dev/null 2>&1; then
    "$bin" -C DOCKER-USER -p "$proto" --dport "$port" -j ACCEPT >/dev/null 2>&1 || \
      "$bin" -I DOCKER-USER 1 -p "$proto" --dport "$port" -j ACCEPT >/dev/null 2>&1 || true
  fi
}

allow_nft() {
  local proto="$1" port="$2"
  command -v nft >/dev/null 2>&1 || return 0
  nft insert rule inet filter input "$proto" dport "$port" accept >/dev/null 2>&1 || true
  nft insert rule ip filter INPUT "$proto" dport "$port" accept >/dev/null 2>&1 || true
}

if [[ "$MODE" == "test" ]]; then
  allow_ufw
  allow_firewalld
  for port in 18080 18081 18082 18083; do
    allow_filter iptables tcp "$port"
    allow_filter ip6tables tcp "$port"
    allow_nft tcp "$port"
  done
  log "test stand ports TCP 18080-18083"
else
  allow_ufw
  allow_firewalld
  vds_ports="22 80 443"
  [[ -z "${SSH_ONLY_FROM:-}" ]] || vds_ports="80 443"
  for port in $vds_ports; do
    allow_filter iptables tcp "$port"
    allow_filter ip6tables tcp "$port"
    allow_nft tcp "$port"
  done
  allow_filter iptables udp 443
  allow_filter ip6tables udp 443
  allow_nft udp 443
  log "VDS ports SSH, TCP 80/443 and UDP 443"
fi

if command -v netfilter-persistent >/dev/null 2>&1; then
  netfilter-persistent save >/dev/null 2>&1 || true
fi
exit 0
