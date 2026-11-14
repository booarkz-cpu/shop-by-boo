"""v28.148.0 (REQ-MIG-0021, item 32 of the old remnawave-manager): SSH limited to the owner's address.

The installer's firewall section and scripts/open-ports.sh run here with fake ufw / iptables / nft that record their
arguments, so the test checks the commands a real run would issue."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fake_bin(tmp: Path) -> Path:
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    for name in ("ufw", "iptables", "ip6tables", "nft", "firewall-cmd"):
        tool = bin_dir / name
        # -C (check) fails so allow_filter goes on to insert; firewall-cmd --state fails so firewalld is skipped.
        tool.write_text(f'#!/bin/sh\necho "{name} $*" >> "{tmp}/calls"\n'
                        'case "$1" in -C|--state) exit 1;; esac\nexit 0\n')
        tool.chmod(0o755)
    # open-ports.sh re-runs itself through sudo when not root, which would drop the fake PATH; the runner is not root.
    (bin_dir / "id").write_text("#!/bin/sh\necho 0\n")
    (bin_dir / "id").chmod(0o755)
    return bin_dir


def firewall_section(tmp: Path, env: dict) -> tuple[int, str, str]:
    text = (ROOT / "deploy/install-vps.sh").read_text()
    start = text.index("# ADMIN_SSH_IP=<адрес>")
    end = text.index("ufw allow 80/tcp", start)
    script = ('log(){ echo "LOG $*"; }; warn(){ echo "WARN $*"; }; die(){ echo "DIE $*"; exit 1; }\nSSH_PORT=2222\n'
              + text[start:end] + 'echo "SSH_FROM=$SSH_FROM"\n')
    run_env = {"PATH": f"{fake_bin(tmp)}:/usr/bin:/bin", **env}
    proc = subprocess.run(["bash", "-c", script], env=run_env, capture_output=True, text=True)
    calls = (tmp / "calls").read_text() if (tmp / "calls").exists() else ""
    return proc.returncode, proc.stdout, calls


def test_without_address_ssh_stays_open_to_all(tmp_path):
    code, out, calls = firewall_section(tmp_path, {})
    assert code == 0 and "SSH_FROM=\n" in out
    assert "ufw allow 2222/tcp" in calls and "from" not in calls


def test_address_of_the_current_session_limits_ssh(tmp_path):
    code, out, calls = firewall_section(tmp_path, {"ADMIN_SSH_IP": "203.0.113.10",
                                                   "SSH_CONNECTION": "203.0.113.10 51515 198.51.100.2 2222"})
    assert code == 0 and "SSH_FROM=203.0.113.10" in out
    assert "ufw delete allow 2222/tcp" in calls
    assert "ufw allow from 203.0.113.10 to any port 2222 proto tcp" in calls


def test_another_address_never_locks_the_operator_out(tmp_path):
    code, out, calls = firewall_section(tmp_path, {"ADMIN_SSH_IP": "203.0.113.10",
                                                   "SSH_CONNECTION": "192.0.2.7 51515 198.51.100.2 2222"})
    assert code == 0 and "SSH_FROM=\n" in out and "WARN" in out
    assert "ufw allow 2222/tcp" in calls and "from" not in calls


def test_not_an_address_is_ignored(tmp_path):
    code, out, calls = firewall_section(tmp_path, {"ADMIN_SSH_IP": "example.com; rm -rf /"})
    assert code == 0 and "SSH_FROM=\n" in out and "WARN" in out
    assert "ufw allow 2222/tcp" in calls and "rm" not in calls


def open_ports(tmp: Path, env: dict) -> str:
    run_env = {"PATH": f"{fake_bin(tmp)}:/usr/bin:/bin", **env}
    proc = subprocess.run(["bash", str(ROOT / "scripts/open-ports.sh"), "vds"], env=run_env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return (tmp / "calls").read_text()


def test_open_ports_does_not_reopen_ssh_when_limited(tmp_path):
    calls = open_ports(tmp_path, {"SSH_ONLY_FROM": "203.0.113.10"})
    assert "OpenSSH" not in calls and "--dport 22 " not in calls and "dport 22 " not in calls
    assert "ufw allow 80/tcp" in calls and "--dport 443" in calls


def test_open_ports_keeps_ssh_by_default(tmp_path):
    calls = open_ports(tmp_path, {})
    assert "ufw allow OpenSSH" in calls and "--dport 22 " in calls


def test_installer_passes_the_limit_to_open_ports():
    text = (ROOT / "deploy/install-vps.sh").read_text()
    assert 'SSH_ONLY_FROM="$SSH_FROM" bash "$ROOT/scripts/open-ports.sh" vds' in text
    assert os.path.exists(ROOT / "scripts/open-ports.sh")
