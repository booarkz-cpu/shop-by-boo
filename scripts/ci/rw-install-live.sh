#!/usr/bin/env bash
# v28.66.0 (stage 10): the GitHub runner plays a clean VPS for the installation wizard. sshd gets a fresh root key
# (only for this job), the test reads the host key fingerprint the same way an administrator would
# (ssh-keygen -lf) and installs «panel + node» through the wizard's API and runner (tests/live/test_install_live.py).
set -Eeuo pipefail
WORK="${RUNNER_TEMP:-/tmp}/rw-install"
mkdir -p "$WORK"
ssh-keygen -q -t ed25519 -N '' -C corgi-ci -f "$WORK/id_ed25519"
sudo install -d -m 0700 /root/.ssh
sudo tee -a /root/.ssh/authorized_keys < "$WORK/id_ed25519.pub" >/dev/null
sudo chmod 600 /root/.ssh/authorized_keys
printf 'PermitRootLogin prohibit-password\nPasswordAuthentication no\n' | sudo tee /etc/ssh/sshd_config.d/99-corgi-ci.conf >/dev/null
sudo systemctl restart ssh || sudo systemctl restart sshd
HOST="$(hostname -I | awk '{print $1}')"
FP="$(sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub | awk '{print $2}')"
cd "${GITHUB_WORKSPACE:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel)}"
set +e
RW_INSTALL_HOST="$HOST" RW_INSTALL_KEY_FILE="$WORK/id_ed25519" RW_INSTALL_FINGERPRINT="$FP" \
  python -m pytest -q -s -rfE "${RW_LIVE_TEST:-tests/live/test_install_live.py}" -p no:cacheprovider
status=$?
if [[ $status -ne 0 ]]; then
  for c in remnawave remnanode remnawave-caddy remnawave-selfsteal remnawave-xray-checker; do sudo docker logs --tail 40 "$c" 2>&1 | sed "s/^/$c: /"; done
fi
echo "Installer (${RW_LIVE_TEST:-tests/live/test_install_live.py}) on the runner over SSH — exit $status" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
exit $status
