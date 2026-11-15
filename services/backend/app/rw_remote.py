"""SSH to a Remnawave server for the installation wizard (v28.66, stage 10; docs/ru/new/DEPLOYMENT_AGENT.md).

* The host key must match the fingerprint stored for the server (``SHA256:…``); there is no trust on first use.
* Only fixed scripts of this module and of rw_steps run there. Values are passed as positional arguments of
  ``bash -c <script> rw <args…>`` — each one quoted with shlex — or on stdin; nothing from a request becomes code.
* A non-root user runs the scripts with ``sudo -n`` (password-less sudo is required; the preflight says so).
* Output kept for the step log is cut to its tail and stripped of the secrets the caller names."""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import shlex
import socket
from dataclasses import dataclass

import paramiko

logger = logging.getLogger(__name__)
TAIL = 4000


class RemoteError(RuntimeError):
    """The server could not be reached, refused the key, or a step's script failed."""


def fingerprint_of(key: paramiko.PKey) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def scan_fingerprint(host: str, port: int, timeout: float = 10) -> dict:
    """The server's host key fingerprint, read without logging in, for the administrator to compare."""
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
    except OSError as exc:
        raise RemoteError(f"Сервер {host}:{port} не принимает соединения SSH") from exc
    transport = paramiko.Transport(sock)
    try:
        transport.start_client(timeout=timeout)
        key = transport.get_remote_server_key()
        return {"fingerprint": fingerprint_of(key), "key_type": key.get_name()}
    except paramiko.SSHException as exc:
        raise RemoteError("Сервер не ответил как SSH") from exc
    finally:
        transport.close()


class _Pinned(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected: str):
        self.expected = expected

    def missing_host_key(self, client, hostname, key):
        import hmac
        if not hmac.compare_digest(fingerprint_of(key), self.expected):
            raise RemoteError("Ключ сервера не совпадает с сохранённым отпечатком: подключение остановлено")
        client.get_host_keys().add(hostname, key.get_name(), key)


def load_private_key(text: str) -> paramiko.PKey:
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return cls.from_private_key(io.StringIO(text))
        except (paramiko.SSHException, ValueError):
            continue
    raise RemoteError("Закрытый ключ SSH не распознан: нужен ключ Ed25519, ECDSA или RSA без пароля")


@dataclass
class Result:
    code: int
    out: str
    err: str


class Remote:
    """One SSH session to a server of the registry."""

    def __init__(self, host: str, port: int, user: str, fingerprint: str, *, key: str | None = None,
                 password: str | None = None, timeout: float = 20):
        if not fingerprint:
            raise RemoteError("Нет отпечатка ключа сервера")
        self.user = user
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(_Pinned(fingerprint))
        kwargs = dict(hostname=host, port=int(port), username=user, timeout=timeout, banner_timeout=timeout,
                      auth_timeout=timeout, allow_agent=False, look_for_keys=False)
        if key:
            kwargs["pkey"] = load_private_key(key)
        elif password:
            kwargs["password"] = password
        else:
            raise RemoteError("Нет ключа или пароля SSH")
        try:
            self.client.connect(**kwargs)
        except RemoteError:
            raise
        except paramiko.AuthenticationException as exc:
            raise RemoteError("Сервер не принял ключ или пароль SSH") from exc
        except (OSError, paramiko.SSHException) as exc:
            raise RemoteError(f"Нет соединения SSH с {host}:{port}") from exc

    def run(self, script: str, *args: str, stdin: bytes | None = None, timeout: int = 900, root: bool = True) -> Result:
        command = "bash -c " + shlex.quote(script) + " rw " + " ".join(shlex.quote(str(a)) for a in args)
        if root and self.user != "root":
            command = "sudo -n " + command
        chan_in, chan_out, chan_err = self.client.exec_command(command, timeout=timeout)
        if stdin is not None:
            chan_in.write(stdin)
        chan_in.channel.shutdown_write()
        out = chan_out.read().decode(errors="replace")
        err = chan_err.read().decode(errors="replace")
        return Result(chan_out.channel.recv_exit_status(), out, err)

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def tail(text: str, secrets: list[str] | tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "***")
    return text[-TAIL:]
