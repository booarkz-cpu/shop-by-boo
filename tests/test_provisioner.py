"""v28.58.0 (BUG-A4 / SEC-02, TECH-09): node installation over SSH, tested by behaviour.

Before, the node ran ``curl -fsSL https://get.docker.com | sh`` as root: a script from another site,
unpinned and unchecked. Now Docker comes from Docker's signed apt repository, and the downloaded key
must have Docker's published fingerprint. The install script is executed here with fake system tools."""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from app import provisioner

COMPOSE = "services:\n  remnanode:\n    image: remnawave/node:latest\n    environment:\n      - SECRET_KEY='a b'\n"


class Channel:
    def __init__(self, code):
        self.code = code

    def recv_exit_status(self):
        return self.code


class Stream:
    def __init__(self, data=b"", code=0):
        self.data, self.channel = data, Channel(code)

    def read(self):
        return self.data


class Client:
    def __init__(self, code=0):
        self.code, self.commands, self.closed = code, [], False

    def exec_command(self, command, timeout=None):
        self.commands.append((command, timeout))
        return None, Stream(b"ok", self.code), Stream(b"apt failed", self.code)

    def close(self):
        self.closed = True


def connect_with(client, seen):
    def fake(host, port, username, password=None, private_key=None, timeout=20, host_key_fingerprint=None):
        seen.update(host=host, fingerprint=host_key_fingerprint)
        return client
    return fake


def test_installs_from_the_signed_repository_and_quotes_every_value(monkeypatch):
    client, seen = Client(), {}
    monkeypatch.setattr(provisioner, "_connect", connect_with(client, seen))
    result = provisioner.run_ssh("203.0.113.7", 22, "root", None, "key", COMPOSE, "198.51.100.1; reboot", 2222,
                                 host_key_fingerprint="SHA256:abc")
    assert result == {"ok": True, "host": "203.0.113.7", "directory": "/opt/remnanode"}
    assert seen == {"host": "203.0.113.7", "fingerprint": "SHA256:abc"} and client.closed
    command, timeout = client.commands[0]
    assert "get.docker.com" not in command and "| sh" not in command
    assert provisioner.DOCKER_KEY_FINGERPRINT in command and "download.docker.com/linux/" in command
    assert timeout >= 600
    # The panel address cannot add a command: it is one quoted argument of ufw.
    assert "'198.51.100.1; reboot'" in command


def test_failure_of_the_remote_install_is_reported_without_its_output(monkeypatch):
    client = Client(code=21)
    monkeypatch.setattr(provisioner, "_connect", connect_with(client, {}))
    with pytest.raises(provisioner.ProvisionError, match="Remote install failed"):
        provisioner.run_ssh("203.0.113.7", 22, "root", "pw", None, COMPOSE, None, host_key_fingerprint="SHA256:abc")
    assert client.closed


@pytest.mark.parametrize("compose,port,message", [("", 2222, "empty"), ("services: {}", 2222, "remnawave/node"),
                                                   (COMPOSE, 70000, "port")])
def test_invalid_requests_never_connect(monkeypatch, compose, port, message):
    monkeypatch.setattr(provisioner, "_connect", lambda *a, **k: pytest.fail("connected"))
    with pytest.raises(provisioner.ProvisionError, match=message):
        provisioner.run_ssh("203.0.113.7", 22, "root", "pw", None, compose, None, port)


def _tool(directory: Path, name: str, body: str):
    path = directory / name
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(tmp_path, os_release: str, fingerprint: str | None, docker_ready: bool = False):
    """Run DOCKER_INSTALL with fake apt-get, curl, gpg, dpkg and docker; returns (code, stderr, log)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "log"
    for name in ("apt-get", "install", "chmod", "dpkg"):
        _tool(bin_dir, name, f'echo "{name} $*" >> "{log}"; [ "$1" = "--print-architecture" ] && echo amd64; exit 0')
    _tool(bin_dir, "curl", f'echo "curl $*" >> "{log}"; while [ "$#" -gt 0 ]; do [ "$1" = "-o" ] && echo key > "$2"; shift; done')
    _tool(bin_dir, "gpg", f'echo "gpg $*" >> "{log}"; case "$*" in *show-keys*) echo "fpr:::::::::{fingerprint or ""}:";; esac')
    ready = "exit 0" if docker_ready else f'[ -f "{tmp_path}/installed" ] && exit 0; exit 1'
    _tool(bin_dir, "docker", f'echo "docker $*" >> "{log}"; {ready}')
    release = tmp_path / "os-release"
    release.write_text(os_release)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "OS_RELEASE": str(release), "HOME": str(tmp_path)}
    # The repository list goes to /etc; point it at the temp dir for the test.
    script = provisioner.DOCKER_INSTALL.replace("/etc/apt/sources.list.d/docker.list", str(tmp_path / "docker.list")) \
        .replace("/etc/apt/keyrings/docker.gpg", str(tmp_path / "docker.gpg"))
    script = script.replace("docker compose version >/dev/null\n", f'touch "{tmp_path}/installed"; docker compose version >/dev/null\n')
    proc = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=30)
    return proc.returncode, proc.stderr, log.read_text() if log.exists() else ""


needs_bash = pytest.mark.skipif(not shutil.which("bash") or os.name != "posix", reason="needs bash")


@needs_bash
def test_install_script_checks_the_key_before_adding_the_repository(tmp_path):
    code, err, log = _run(tmp_path, "ID=debian\nVERSION_CODENAME=bookworm\n", provisioner.DOCKER_KEY_FINGERPRINT)
    assert code == 0, err
    assert "https://download.docker.com/linux/debian/gpg" in log and "--proto =https" in log
    assert "docker-compose-plugin" in log
    assert "bookworm stable" in (tmp_path / "docker.list").read_text()


@needs_bash
def test_install_script_refuses_a_key_with_another_fingerprint(tmp_path):
    code, err, log = _run(tmp_path, "ID=ubuntu\nVERSION_CODENAME=noble\n", "0" * 40)
    assert code == 21 and "fingerprint mismatch" in err
    assert not (tmp_path / "docker.list").exists() and "docker-ce" not in log


@needs_bash
def test_install_script_stops_on_other_systems_and_skips_ready_docker(tmp_path):
    code, err, _ = _run(tmp_path, "ID=alpine\n", provisioner.DOCKER_KEY_FINGERPRINT)
    assert code == 20 and "install Docker" in err
    ready = tmp_path / "ready"
    ready.mkdir()
    code, _, log = _run(ready, "ID=alpine\n", None, docker_ready=True)
    assert code == 0 and "apt-get" not in log


def test_node_compose_is_the_official_one_and_the_key_cannot_escape():
    import yaml
    text = provisioner.node_compose("key: with\" quotes' and $vars", 2223)
    service = yaml.safe_load(text)["services"]["remnanode"]
    assert service["image"] == provisioner.NODE_IMAGE and service["network_mode"] == "host" and service["cap_add"] == ["NET_ADMIN"]
    assert service["environment"] == {"NODE_PORT": "2223", "SECRET_KEY": "key: with\" quotes' and $vars"}
    assert set(service) == {"image", "container_name", "hostname", "network_mode", "restart", "cap_add", "ulimits", "environment"}
    for bad in ("", "a\nb", "x" * 9000):
        with pytest.raises(provisioner.ProvisionError):
            provisioner.node_compose(bad)


@pytest.mark.asyncio
async def test_admin_api_takes_typed_values_not_a_compose_file(monkeypatch):
    from types import SimpleNamespace

    from pydantic import ValidationError

    from app import admin_api, main as shop
    fingerprint = "SHA256:" + "A" * 43
    with pytest.raises(ValidationError):  # a compose text from the browser is refused
        admin_api.NodeProvisionIn(host="203.0.113.7", ssh_username="root", ssh_password="pw", ssh_host_key=fingerprint,
                                  compose_yaml="services: {evil: {image: alpine, privileged: true}}")
    with pytest.raises(ValidationError):  # no host key, no connection
        admin_api.NodeProvisionIn(host="203.0.113.7", ssh_username="root", ssh_password="pw")
    seen = {}

    class Panel:
        async def node_secret_key(self):
            return "panel-secret"

    def fake_ssh(**kw):
        seen.update(kw)
        return {"ok": True, "host": kw["host"], "directory": "/opt/remnanode"}

    class Db:
        def add(self, row):
            seen["audit"] = row.action

        async def commit(self):
            return None

    monkeypatch.setattr(shop, "RemnawaveClient", Panel)
    monkeypatch.setattr(shop, "run_ssh", fake_ssh)
    payload = admin_api.NodeProvisionIn(host="203.0.113.7", ssh_username="root", ssh_private_key="k", ssh_host_key=fingerprint,
                                        panel_ip="198.51.100.1")
    out = await admin_api.provision_node(payload, Db(), SimpleNamespace(email="root@example.test"))
    assert out["ok"] and seen["host_key_fingerprint"] == fingerprint and seen["audit"] == "node.provisioned"
    assert 'SECRET_KEY: "panel-secret"' in seen["compose_yaml"] and provisioner.NODE_IMAGE in seen["compose_yaml"]
    bad = admin_api.NodeProvisionIn(host="203.0.113.7", ssh_username="root", ssh_password="pw", ssh_host_key=fingerprint, panel_ip="x; reboot")
    with pytest.raises(Exception) as err:
        await admin_api.provision_node(bad, Db(), SimpleNamespace(email="a"))
    assert getattr(err.value, "status_code", None) == 400
