#!/usr/bin/env bash
# Install from Docker's signed apt repository; reuse a working existing engine.
# Official procedure: https://docs.docker.com/engine/install/ubuntu/
#                    https://docs.docker.com/engine/install/debian/
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run the Docker installer as root.' >&2; exit 1; }
if command -v docker >/dev/null 2>&1; then
  docker compose version >/dev/null 2>&1 || {
    echo 'Existing Docker has no Compose v2 plugin. Install its compatible plugin before continuing; the installer will not replace a live engine.' >&2
    exit 1
  }
  systemctl enable --now docker
  exit 0
fi
. /etc/os-release
case "${ID:-}" in ubuntu|debian) ;; *) echo 'Only Ubuntu and Debian are supported.' >&2; exit 1;; esac
docker_codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
docker_arch="$(dpkg --print-architecture)"
[[ "$docker_codename" =~ ^[a-z][a-z0-9-]+$ && "$docker_arch" =~ ^[a-z0-9]+$ ]] || {
  echo 'Invalid OS codename or architecture.' >&2; exit 1;
}
# Do not silently replace Docker repositories installed by an operator.
if [[ -e /etc/apt/sources.list.d/docker.list || -e /etc/apt/sources.list.d/docker.sources ]]; then
  echo 'A Docker apt source already exists. Review it and install Engine/Compose from that source.' >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
docker_key_tmp="$(mktemp /etc/apt/keyrings/docker.asc.XXXXXXXX)"
trap 'rm -f "$docker_key_tmp"' EXIT
curl --proto '=https' --tlsv1.2 -fsSL "https://download.docker.com/linux/$ID/gpg" -o "$docker_key_tmp"
rg_key='BEGIN PGP PUBLIC KEY BLOCK'
grep -q "$rg_key" "$docker_key_tmp" || { echo 'Docker signing key download is invalid.' >&2; exit 1; }
install -m 0644 "$docker_key_tmp" /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/$ID
Suites: $docker_codename
Components: stable
Architectures: $docker_arch
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker version >/dev/null
docker compose version >/dev/null
