"""Plugin runtime: signed packages, capability approval, upgrade/rollback, scoped API, signed deliveries."""
import hashlib
import hmac
import io
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from sqlalchemy import func, select
from starlette.datastructures import Headers, UploadFile
from starlette.requests import Request

from app import main as shop
from app import plugins
from app.models import AuditLog, Notification, Payment, PluginDelivery, PluginEventCursor, PluginInstall, PluginPackage, User
from test_subscription_commerce import database

ADMIN = SimpleNamespace(email="admin@example.test", role="admin")
KEY = Ed25519PrivateKey.generate()
OTHER = Ed25519PrivateKey.generate()


def manifest(**over):
    data = {"id": "acme.crm", "name": "ACME CRM", "version": "1.0.0", "api_version": 1, "publisher": "ACME", "endpoint": "https://93.184.216.34/hooks/corgi",
            "capabilities": ["users.read"], "events": ["user.registered"], "settings": [{"key": "crm_key", "type": "secret", "label": "CRM key", "required": True}, {"key": "region", "type": "string", "label": "Region"}]}
    data.update(over)
    return data


def package(data=None, key=KEY, extra=None):
    files = {"manifest.json": json.dumps(data or manifest()).encode(), "README.md": b"# ACME"}
    files.update(extra or {})
    return plugins.sign_package(files, key)


def public(key=KEY):
    from base64 import b64encode
    from cryptography.hazmat.primitives import serialization
    return b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def upload_file(data):
    return UploadFile(file=io.BytesIO(data), filename="plugin.zip", headers=Headers({"content-type": "application/zip"}))


def bearer(token):
    return Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})


@pytest.fixture
def ready(database, monkeypatch):
    monkeypatch.setattr(shop, "_resolve_public_host", lambda host, port=443: ["93.184.216.34"])
    return database


async def trust(db, key=KEY):
    return await plugins.add_publisher(plugins.PublisherIn(name="ACME", public_key=public(key)), db, ADMIN)


async def install(db, data=None, settings=True):
    await trust(db)
    await plugins.upload(upload_file(package(data)), db, ADMIN)
    m = data or manifest()
    if settings:
        await plugins.save_settings(m["id"], plugins.SettingsIn(values={"crm_key": "s3cret", "region": "eu"}), db, ADMIN)
    return await plugins.enable(m["id"], plugins.EnableIn(version=m["version"], capabilities=m["capabilities"], events=m["events"]), db, ADMIN)


@pytest.mark.asyncio
async def test_signed_package_installs_and_credentials_are_shown_once(ready):
    view = await install(ready)
    assert view["state"] == "enabled" and view["active_version"] == "1.0.0"
    token, secret = view["credentials"]["api_token"], view["credentials"]["signing_secret"]
    row = await ready.get(PluginInstall, "acme.crm")
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest() and secret not in (row.signing_secret_encrypted or "")
    listing = await plugins.admin_plugins(ready, ADMIN)
    dumped = json.dumps(listing)
    assert token not in dumped and secret not in dumped and "s3cret" not in dumped
    secret_setting = next(s for s in listing["plugins"][0]["settings"] if s["key"] == "crm_key")
    assert secret_setting["value"] is None and secret_setting["configured"] is True
    again = await plugins.enable("acme.crm", plugins.EnableIn(version="1.0.0", capabilities=["users.read"], events=["user.registered"]), ready, ADMIN)
    assert "credentials" not in again
    actions = (await ready.scalars(select(AuditLog.action).where(AuditLog.target.in_(["acme.crm"])))).all()
    assert {"plugin.uploaded", "plugin.enabled", "plugin.settings.updated"} <= set(actions)


@pytest.mark.asyncio
@pytest.mark.parametrize("case,expected", [
    ("tampered", "Подпись пакета не совпадает"),
    ("untrusted", "неизвестным или отозванным"),
    ("extra", "Недопустимый файл"),
    ("api", "api_version"),
    ("event-without-capability", "Событиям нужны capabilities"),
    ("unknown-capability", "Неизвестные capabilities"),
    ("http", "endpoint"),
    ("not-zip", "zip"),
])
async def test_untrusted_or_invalid_packages_are_rejected(ready, monkeypatch, case, expected):
    await trust(ready)
    if case == "tampered":
        import zipfile
        signed = io.BytesIO(package())
        with zipfile.ZipFile(signed) as src:
            files = {n: src.read(n) for n in src.namelist()}
        files["manifest.json"] = json.dumps(manifest(capabilities=["users.read", "payments.read"])).encode()
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as dst:
            for n, d in files.items():
                dst.writestr(n, d)
        data = out.getvalue()
    elif case == "untrusted":
        data = package(key=OTHER)
    elif case == "extra":
        data = package(extra={"plugin.py": b"import os"})
    elif case == "api":
        data = package(manifest(api_version=2))
    elif case == "event-without-capability":
        data = package(manifest(capabilities=[], events=["payment.succeeded"]))
    elif case == "unknown-capability":
        data = package(manifest(capabilities=["admin.everything"]))
    elif case == "http":
        data = package(manifest(endpoint="http://93.184.216.34/hook"))
    else:
        data = b"not a zip"
    with pytest.raises(HTTPException) as error:
        await plugins.upload(upload_file(data), ready, ADMIN)
    assert error.value.status_code == 422 and expected in error.value.detail
    assert await ready.scalar(select(func.count(PluginPackage.id))) == 0


@pytest.mark.asyncio
async def test_private_endpoint_is_rejected(database, monkeypatch):
    await trust(database)
    with pytest.raises(HTTPException) as error:
        await plugins.upload(upload_file(package(manifest(endpoint="https://10.0.0.5/hook"))), database, ADMIN)
    assert error.value.status_code == 422 and "endpoint" in error.value.detail


@pytest.mark.asyncio
async def test_enable_requires_exact_approval_and_required_settings(ready):
    await trust(ready)
    await plugins.upload(upload_file(package()), ready, ADMIN)
    with pytest.raises(HTTPException) as error:
        await plugins.enable("acme.crm", plugins.EnableIn(version="1.0.0", capabilities=["users.read"], events=["user.registered"]), ready, ADMIN)
    assert error.value.status_code == 409 and "crm_key" in error.value.detail
    await plugins.save_settings("acme.crm", plugins.SettingsIn(values={"crm_key": "s3cret"}), ready, ADMIN)
    with pytest.raises(HTTPException) as error:
        await plugins.enable("acme.crm", plugins.EnableIn(version="1.0.0", capabilities=[], events=[]), ready, ADMIN)
    assert error.value.status_code == 409
    view = await plugins.enable("acme.crm", plugins.EnableIn(version="1.0.0", capabilities=["users.read"], events=["user.registered"]), ready, ADMIN)
    # An empty secret field keeps the stored secret.
    await plugins.save_settings("acme.crm", plugins.SettingsIn(values={"crm_key": "", "region": "us"}), ready, ADMIN)
    me = await plugins.plugin_me(bearer(view["credentials"]["api_token"]), ready)
    assert me["settings"] == {"crm_key": "s3cret", "region": "us"}
    with pytest.raises(HTTPException):
        await plugins.save_settings("acme.crm", plugins.SettingsIn(values={"unknown": "x"}), ready, ADMIN)


@pytest.mark.asyncio
async def test_token_reaches_only_approved_capabilities(ready):
    view = await install(ready)
    token = view["credentials"]["api_token"]
    user = await plugins.plugin_user(1, bearer(token), ready)
    assert user == {"id": 1, "username": "Owner", "created_at": user["created_at"]}
    for call in (plugins.plugin_subscriptions(1, bearer(token), ready), plugins.plugin_payment(1, bearer(token), ready)):
        with pytest.raises(HTTPException) as error:
            await call
        assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        await plugins.plugin_user(1, bearer("cpl_wrong"), ready)
    assert error.value.status_code == 401
    await plugins.disable("acme.crm", ready, ADMIN)
    with pytest.raises(HTTPException) as error:
        await plugins.plugin_user(1, bearer(token), ready)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_upgrade_waits_for_new_approval_and_rollback_is_bounded(ready):
    first = await install(ready)
    token = first["credentials"]["api_token"]
    bigger = manifest(version="1.1.0", capabilities=["users.read", "payments.read"], events=["user.registered", "payment.succeeded"])
    view = await plugins.upload(upload_file(package(bigger)), ready, ADMIN)
    assert view["active_version"] == "1.0.0"
    assert view["pending_upgrade"] == {"version": "1.1.0", "new_capabilities": ["payments.read"], "new_events": ["payment.succeeded"]}
    with pytest.raises(HTTPException) as error:
        await plugins.rollback("acme.crm", plugins.VersionIn(version="1.1.0"), ready, ADMIN)
    assert error.value.status_code == 409
    upgraded = await plugins.enable("acme.crm", plugins.EnableIn(version="1.1.0", capabilities=bigger["capabilities"], events=bigger["events"]), ready, ADMIN)
    assert upgraded["active_version"] == "1.1.0" and "credentials" not in upgraded
    ready.add(Payment(id=10, user_id=1, plan_id=1, provider="sandbox", order_id="o-10", amount=100, currency="RUB", status="succeeded"))
    await ready.commit()
    assert (await plugins.plugin_payment(10, bearer(token), ready))["amount"] == "100.00"
    back = await plugins.rollback("acme.crm", plugins.VersionIn(version="1.0.0"), ready, ADMIN)
    assert back["active_version"] == "1.0.0" and back["approved_capabilities"] == ["users.read"]
    with pytest.raises(HTTPException) as error:
        await plugins.plugin_payment(10, bearer(token), ready)
    assert error.value.status_code == 403
    with pytest.raises(HTTPException):
        await plugins.upload(upload_file(package(bigger)), ready, ADMIN)


@pytest.mark.asyncio
async def test_events_start_at_enable_time_and_are_delivered_once(ready):
    await plugins.scan_events(ready)  # initialises cursors at the current end: no history backfill
    assert await ready.scalar(select(func.count(PluginDelivery.id))) == 0
    m = manifest(capabilities=["users.read", "payments.read", "subscriptions.read"], events=["user.registered", "payment.succeeded", "subscription.activated"])
    await install(ready, m)
    ready.add(User(id=50, referral_code="NEW50", created_at=datetime.utcnow() + timedelta(seconds=1)))
    ready.add(Notification(user_id=1, kind="payment_success", title="t", body="b", dedupe_key="payment:7:success", created_at=datetime.utcnow() + timedelta(seconds=1)))
    ready.add(Notification(user_id=1, kind="subscription_ready", title="t", body="b", dedupe_key="payment:7:ready", created_at=datetime.utcnow() + timedelta(seconds=1)))
    ready.add(Notification(user_id=1, kind="support.reply", title="t", body="private", dedupe_key="support-message:1", created_at=datetime.utcnow() + timedelta(seconds=1)))
    await ready.commit()
    assert await plugins.scan_events(ready) == 3
    assert await plugins.scan_events(ready) == 0
    rows = (await ready.scalars(select(PluginDelivery).order_by(PluginDelivery.id))).all()
    assert [(r.event, r.payload) for r in rows] == [
        ("user.registered", {"user_id": 50}),
        ("payment.succeeded", {"payment_id": 7, "user_id": 1}),
        ("subscription.activated", {"payment_id": 7, "user_id": 1}),
    ]
    assert "private" not in json.dumps([r.payload for r in rows])
    # Rewinding the cursor (replay) never duplicates a delivery.
    cursor = await ready.get(PluginEventCursor, "notifications")
    cursor.last_id = 0
    await ready.commit()
    assert await plugins.scan_events(ready) == 0


class Endpoint:
    def __init__(self, status=200):
        self.status, self.requests = status, []

    def handler(self, request):
        self.requests.append(request)
        return httpx.Response(self.status if isinstance(self.status, int) else self.status.pop(0))


@pytest.fixture
def endpoint(monkeypatch):
    target = Endpoint()
    monkeypatch.setattr(plugins, "client_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(target.handler)))
    return target


async def queue_event(db, plugin_id="acme.crm", key="user.registered:1"):
    db.add(PluginDelivery(plugin_id=plugin_id, event="user.registered", event_key=key, payload={"user_id": 1}, status="queued", next_attempt_at=datetime.utcnow(), created_at=datetime.utcnow()))
    await db.commit()


@pytest.mark.asyncio
async def test_delivery_is_hmac_signed_with_timestamp(ready, endpoint):
    view = await install(ready)
    secret = view["credentials"]["signing_secret"]
    await queue_event(ready)
    assert await plugins.deliver_due(ready) == {"sent": 1}
    request = endpoint.requests[0]
    assert str(request.url) == "https://93.184.216.34/hooks/corgi"
    expected = "v1=" + hmac.new(secret.encode(), request.headers["x-corgi-timestamp"].encode() + b"." + request.content, hashlib.sha256).hexdigest()
    assert request.headers["x-corgi-signature"] == expected and request.headers["x-corgi-event"] == "user.registered"
    body = json.loads(request.content)
    assert body["data"] == {"user_id": 1} and body["plugin"] == "acme.crm" and body["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_retry_backoff_permanent_errors_and_automatic_stop(ready, endpoint):
    await install(ready)
    endpoint.status = 503
    await queue_event(ready)
    now = datetime.utcnow()
    assert await plugins.deliver_due(ready, now=now) == {"retry": 1}
    row = await ready.scalar(select(PluginDelivery))
    assert row.status == "queued" and row.next_attempt_at == now + timedelta(seconds=30)
    endpoint.status = 400
    await queue_event(ready, key="user.registered:2")
    assert await plugins.deliver_due(ready, now=now + timedelta(seconds=31)) == {"failed": 2}
    install_row = await ready.get(PluginInstall, "acme.crm")
    assert install_row.consecutive_failures == 3 and install_row.state == "enabled"
    for index in range(plugins.FAILURE_LIMIT):
        await queue_event(ready, key=f"user.registered:x{index}")
    await plugins.deliver_due(ready, now=now + timedelta(minutes=5))
    await ready.refresh(install_row)
    assert install_row.state == "failing" and "автоматически" in install_row.disabled_reason
    await queue_event(ready, key="user.registered:after")
    assert await plugins.deliver_due(ready, now=now + timedelta(minutes=6)) == {"skipped": 1}
    re_enabled = await plugins.enable("acme.crm", plugins.EnableIn(version="1.0.0", capabilities=["users.read"], events=["user.registered"]), ready, ADMIN)
    assert re_enabled["state"] == "enabled" and re_enabled["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_revoking_publisher_stops_its_plugins(ready):
    await install(ready)
    publisher = (await plugins.admin_plugins(ready, ADMIN))["publishers"][0]
    result = await plugins.revoke_publisher(publisher["id"], ready, ADMIN)
    assert result["stopped"] == ["acme.crm"]
    assert (await ready.get(PluginInstall, "acme.crm")).state == "disabled"
    with pytest.raises(HTTPException) as error:
        await plugins.enable("acme.crm", plugins.EnableIn(version="1.0.0", capabilities=["users.read"], events=["user.registered"]), ready, ADMIN)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_notifications_capability_dedupes_and_rate_limits(ready, monkeypatch):
    m = manifest(capabilities=["notifications.send"], events=[])
    view = await install(ready, m)
    token = view["credentials"]["api_token"]
    body = plugins.PluginNotificationIn(user_id=1, title="Бонус", body="Вам начислен бонус", dedupe_key="bonus-1")
    first = await plugins.plugin_notify(body, bearer(token), ready)
    assert (await plugins.plugin_notify(body, bearer(token), ready)) == {"id": first["id"], "duplicate": True}
    note = await ready.get(Notification, first["id"])
    assert note.kind == "plugin.acme.crm" and note.dedupe_key == "plugin:acme.crm:bonus-1"
    monkeypatch.setattr(plugins, "NOTIFY_PER_MINUTE", 1)
    with pytest.raises(HTTPException) as error:
        await plugins.plugin_notify(plugins.PluginNotificationIn(user_id=1, title="x", body="y", dedupe_key="bonus-2"), bearer(token), ready)
    assert error.value.status_code == 429


@pytest.mark.asyncio
async def test_rotate_and_uninstall_revoke_access(ready):
    view = await install(ready)
    old = view["credentials"]["api_token"]
    rotated = await plugins.rotate("acme.crm", ready, ADMIN)
    new = rotated["credentials"]["api_token"]
    with pytest.raises(HTTPException):
        await plugins.plugin_me(bearer(old), ready)
    assert (await plugins.plugin_me(bearer(new), ready))["id"] == "acme.crm"
    await queue_event(ready)
    await plugins.uninstall("acme.crm", ready, ADMIN)
    with pytest.raises(HTTPException):
        await plugins.plugin_me(bearer(new), ready)
    assert await ready.scalar(select(func.count(PluginDelivery.id))) == 0
    assert await ready.scalar(select(func.count(PluginPackage.id))) == 0


def test_package_digest_ignores_signature_and_order():
    a = plugins.package_digest({"manifest.json": b"{}", "README.md": b"x", "signature.json": b"1"})
    b = plugins.package_digest({"README.md": b"x", "manifest.json": b"{}"})
    assert a == b
    assert plugins.version_key("1.10.0") > plugins.version_key("1.9.9")


def test_signing_script_produces_packages_the_shop_accepts(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("sign_plugin", Path(__file__).resolve().parents[1] / "scripts/sign-plugin.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    key_path = tmp_path / "publisher.key"
    tool.keygen(key_path)
    assert oct(key_path.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(SystemExit):
        tool.keygen(key_path)
    out = tmp_path / "example.zip"
    tool.sign(key_path, Path(__file__).resolve().parents[1] / "docs/examples/plugin", out)
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    files = plugins.read_package(out.read_bytes())
    publisher = SimpleNamespace(public_key=tool.public_key(key), revoked_at=None, fingerprint="x")
    assert plugins.verify_signature(files, [publisher]) is publisher
    assert json.loads(files["manifest.json"])["id"] == "example.crm-sync"
