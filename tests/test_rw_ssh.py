"""v28.75.0 (stage 16): rotation of the SSH key of a Remnawave wizard server, against a fake SSH server.

* the shop makes its own Ed25519 key per server, adds it to ``authorized_keys`` with its marker, logs in with it
  and only then forgets the old key or password;
* the previous key of the shop is removed by its marker; keys of the owner are never touched;
* a new key that does not log in is removed again and the old access stays;
* the scripts check user and marker on the server too; the route needs a confirmed session."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import rw_api, rw_jobs, rw_ssh
from app.models import AuditLog, RemnawaveServer
from app.rw_remote import Result, load_private_key
from app.security import decrypt_secret, encrypt_secret
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test", role="admin")
OWNER_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOwnerOwnerOwnerOwnerOwnerOwnerOwnerOwner owner@laptop"


class Host:
    def __init__(self):
        self.keys = [OWNER_KEY]
        self.calls = []
        self.accepts_new = True


class Session:
    def __init__(self, host, server):
        self.host, self.server = host, server

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def run(self, script, *args, stdin=None, timeout=60, root=True):
        h = self.host
        name = {rw_ssh.ADD_KEY: "add", rw_ssh.REMOVE_KEY: "remove", rw_ssh.VERIFY: "verify"}[script]
        login = self.server.get("key") or self.server.get("password")
        h.calls.append((name, args, login))
        if name == "add":
            h.keys.append(stdin.decode())
            return Result(0, "added\n", "")
        if name == "remove":
            h.keys = [k for k in h.keys if not k.endswith(" " + args[1])]
            return Result(0, "removed\n", "")
        # verify: only a key that is in authorized_keys logs in
        if not self.server.get("key") or not h.accepts_new:
            return Result(255, "", "Permission denied")
        pub = load_private_key(self.server["key"]).get_base64()
        return Result(0 if any(pub in k for k in h.keys) else 255, "rw-key-ok corgi\n", "")


@pytest.fixture
def host(monkeypatch):
    h = Host()
    monkeypatch.setattr(rw_jobs, "CONNECT", lambda server: Session(h, server))
    return h


async def server(db, method="password"):
    row = RemnawaveServer(name="fi-1", host="198.51.100.4", ssh_port=22, ssh_user="corgi", auth_method=method,
                          ssh_secret=encrypt_secret("owner-password-123"), host_key_fingerprint="SHA256:" + "A" * 43)
    db.add(row)
    await db.commit()
    return row


def test_new_key_is_ed25519_with_a_marker():
    private, line, fp, marker = rw_ssh.new_key(5)
    assert private.startswith("-----BEGIN OPENSSH PRIVATE KEY-----") and line.startswith("ssh-ed25519 ")
    assert line.endswith(" " + marker) and marker.startswith("corgi-shop-5-") and fp.startswith("SHA256:")
    assert load_private_key(private).get_base64() in line
    for script in (rw_ssh.ADD_KEY, rw_ssh.REMOVE_KEY):  # the server checks user and marker too
        assert "bad user" in script and "bad marker" in script


@pytest.mark.asyncio
async def test_rotation_replaces_the_password_then_the_previous_shop_key(database, host):
    db = database
    row = await server(db)
    first = await rw_ssh.rotate_key(row.id, db, ADMIN)
    assert first["auth_method"] == "key" and first["ssh_key"]["managed"] and not first["ssh_key"]["rotation_due"]
    assert first["rotation"]["previous"] == "password" and "PasswordAuthentication" in first["rotation"]["note"]
    await db.refresh(row)
    assert "owner-password" not in decrypt_secret(row.ssh_secret)  # the password is not kept any more
    assert [c[0] for c in host.calls] == ["add", "verify"] and host.calls[0][2] == "owner-password-123"
    first_marker = row.ssh_key_marker
    assert OWNER_KEY in host.keys and any(k.endswith(first_marker) for k in host.keys)

    second = await rw_ssh.rotate_key(row.id, db, ADMIN)  # within the same second: the markers still differ
    await db.refresh(row)
    assert second["rotation"]["previous_key_removed"] and row.ssh_key_marker != first_marker
    assert not any(k.endswith(first_marker) for k in host.keys)
    assert OWNER_KEY in host.keys  # the owner's key stays
    assert sum(k.startswith("ssh-ed25519 ") and "corgi-shop-" in k for k in host.keys) == 1
    audits = (await db.execute(select(AuditLog.action).where(AuditLog.action == "rw.server.key_rotated"))).scalars().all()
    assert len(audits) == 2
    listed = (await rw_api.list_servers(db, ADMIN))["servers"][0]
    assert listed["ssh_key"]["fingerprint"] == row.ssh_key_fingerprint and "ssh_secret" not in listed


@pytest.mark.asyncio
async def test_a_key_that_does_not_log_in_is_taken_back(database, host):
    db = database
    row = await server(db)
    host.accepts_new = False
    with pytest.raises(HTTPException) as err:
        await rw_ssh.rotate_key(row.id, db, ADMIN)
    assert err.value.status_code == 502 and "доступ прежний" in err.value.detail
    await db.refresh(row)
    assert row.auth_method == "password" and decrypt_secret(row.ssh_secret) == "owner-password-123"
    assert host.keys == [OWNER_KEY] and [c[0] for c in host.calls] == ["add", "verify", "remove"]


def test_route_needs_a_confirmed_session():
    from app_contract import all_routes
    route = next(r for p, r in all_routes() if p == "/api/admin/rw/servers/{server_id}/rotate-key")
    assert any(getattr(d.call, "step_up", False) for d in route.dependant.dependencies)
