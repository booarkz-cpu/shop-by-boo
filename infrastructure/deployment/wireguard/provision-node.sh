#!/usr/bin/env bash
set -euo pipefail
# Provision a Linux Corgi Edge WireGuard node. Run only on a dedicated node.
# No user traffic is logged by this script.
IFACE="${WG_INTERFACE:-wg-corgi}"
ADDR="${WG_ADDRESS:-10.77.0.1/24}"
PORT="${WG_PORT:-51820}"
KEY_DIR="${WG_KEY_DIR:-/etc/corgi/wireguard}"
install -d -m 700 "$KEY_DIR"
command -v wg >/dev/null || { echo 'wireguard-tools is required' >&2; exit 1; }
command -v wg-quick >/dev/null || { echo 'wg-quick is required' >&2; exit 1; }
if [[ ! -f "$KEY_DIR/privatekey" ]]; then umask 077; wg genkey > "$KEY_DIR/privatekey"; fi
PUB="$(wg pubkey < "$KEY_DIR/privatekey")"
cat > "/etc/wireguard/${IFACE}.conf" <<EOF
[Interface]
Address = ${ADDR}
ListenPort = ${PORT}
PrivateKey = $(cat "$KEY_DIR/privatekey")
SaveConfig = false
EOF
chmod 600 "/etc/wireguard/${IFACE}.conf"
echo "Corgi WireGuard node prepared: ${IFACE}"
echo "Public key: ${PUB}"
echo "Start with: systemctl enable --now wg-quick@${IFACE}"
