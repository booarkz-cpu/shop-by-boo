"""Native push: device registry, session binding, FCM/APNs delivery, retries and token loss."""
import base64
import json
from datetime import datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import HTTPException
from sqlalchemy import select

from app import push
from app.config import settings
from app.models import Notification, PushDelivery, PushDevice, User, UserSession
from test_subscription_commerce import database

RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
EC_KEY = ec.generate_private_key(ec.SECP256R1())
RSA_PEM = RSA_KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
EC_PEM = EC_KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
FCM_TOKEN = "fcm-registration-token-" + "a" * 40
APNS_TOKEN = "ab" * 32


class Recorder:
    """httpx MockTransport that records requests and answers from a per-host script."""

    def __init__(self):
        self.calls = []
        self.fcm_status = [(200, {"name": "projects/p/messages/1"})]
        self.apns_status = [(200, {})]

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "oauth-access", "expires_in": 3600})
        if req.url.host == "fcm.googleapis.com":
            status, body = self.fcm_status.pop(0) if len(self.fcm_status) > 1 else self.fcm_status[0]
            return httpx.Response(status, json=body)
        status, body = self.apns_status.pop(0) if len(self.apns_status) > 1 else self.apns_status[0]
        return httpx.Response(status, json=body) if body else httpx.Response(status)

    def sends(self, host):
        return [c for c in self.calls if c.url.host == host]


@pytest.fixture
def providers(monkeypatch):
    recorder = Recorder()
    account = {"type": "service_account", "client_email": "push@p.iam.gserviceaccount.com", "private_key": RSA_PEM, "private_key_id": "kid-1", "token_uri": "https://oauth2.googleapis.com/token"}
    monkeypatch.setattr(settings, "fcm_project_id", "corgi-test")
    monkeypatch.setattr(settings, "fcm_service_account_json", base64.b64encode(json.dumps(account).encode()).decode())
    monkeypatch.setattr(settings, "apns_key_id", "KEY1234567")
    monkeypatch.setattr(settings, "apns_team_id", "TEAM123456")
    monkeypatch.setattr(settings, "apns_bundle_id", "shop.remnawave.user")
    monkeypatch.setattr(settings, "apns_private_key", EC_PEM.replace("\n", "\\n"))
    monkeypatch.setattr(settings, "apns_environment", "sandbox")
    monkeypatch.setattr(push, "client_factory", lambda http2: httpx.AsyncClient(transport=httpx.MockTransport(recorder.handler)))
    push.reset_provider_cache()
    yield recorder
    push.reset_provider_cache()


@pytest.fixture
def sessions(monkeypatch, database):
    """Bind API calls to a chosen (user, session) pair instead of a bearer token."""
    state = {}

    async def make(user_id=1):
        row = UserSession(user_id=user_id, jti_hash=f"jti-{user_id}-{len(state)}".ljust(64, "0"), expires_at=datetime.utcnow() + timedelta(days=1))
        database.add(row)
        await database.commit()
        state["current"] = row
        return row

    async def current(request, db):
        row = state["current"]
        return await db.get(User, row.user_id), row

    monkeypatch.setattr(push, "_session", current)
    return make


async def register(db, platform="android", token=FCM_TOKEN, **extra):
    return await push.register_device(push.DeviceIn(platform=platform, token=token, app_version="1.0", locale="ru", **extra), None, db)


async def notify(db, user_id=1, kind="payment_success", body="Заказ оплачен", **extra):
    row = Notification(user_id=user_id, channel="in_app", kind=kind, title="Оплата подтверждена", body=body, status="queued", dedupe_key=f"{kind}:{datetime.utcnow().timestamp()}", **extra)
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
async def test_registration_stores_only_hash_and_ciphertext_and_is_idempotent(database, sessions):
    await sessions()
    first = await register(database)
    again = await register(database)
    assert first["device"]["id"] == again["device"]["id"]
    assert first["device"]["current"] is True
    assert first["push_available"] is False
    row = await database.get(PushDevice, first["device"]["id"])
    assert row.token_hash == push.token_hash(FCM_TOKEN)
    assert FCM_TOKEN not in row.token_encrypted
    assert row.provider == "fcm"
    assert len((await database.execute(select(PushDevice))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_apns_tokens_must_be_hex_and_are_normalised(database, sessions):
    await sessions()
    with pytest.raises(HTTPException) as error:
        await register(database, platform="ios", token="not-a-hex-token-" * 5)
    assert error.value.status_code == 422
    data = await register(database, platform="ios", token=APNS_TOKEN.upper())
    row = await database.get(PushDevice, data["device"]["id"])
    assert row.token_hash == push.token_hash(APNS_TOKEN) and row.provider == "apns"


@pytest.mark.asyncio
async def test_token_moving_to_another_account_is_revoked_for_previous_owner(database, sessions):
    await sessions(1)
    device_id = (await register(database))["device"]["id"]
    await notify(database, user_id=1)
    await sessions(2)
    moved = await register(database)
    assert moved["device"]["id"] == device_id
    row = await database.get(PushDevice, device_id)
    assert row.user_id == 2 and row.revoked_at is None
    assert (await push.list_devices(None, database))["items"][0]["id"] == device_id


@pytest.mark.asyncio
async def test_active_device_limit_revokes_oldest_and_replacement_revokes_old_token(database, sessions):
    await sessions()
    for index in range(push.MAX_ACTIVE_DEVICES + 2):
        await register(database, token=f"token-{index:02d}-" + "x" * 20)
    active = (await database.execute(select(PushDevice).where(PushDevice.revoked_at.is_(None)))).scalars().all()
    assert len(active) == push.MAX_ACTIVE_DEVICES
    limited = (await database.execute(select(PushDevice).where(PushDevice.revoke_reason == "limit"))).scalars().all()
    assert len(limited) == 2
    await register(database, token="fresh-token-" + "y" * 20, replaces="token-11-" + "x" * 20)
    old = await database.scalar(select(PushDevice).where(PushDevice.token_hash == push.token_hash("token-11-" + "x" * 20)))
    assert old.revoke_reason == "replaced"


@pytest.mark.asyncio
async def test_fcm_delivery_signs_service_account_and_hides_support_text(database, sessions, providers):
    await sessions()
    await register(database)
    payment = await notify(database)
    support = await notify(database, kind="support.reply", body="Ваш пароль от роутера: 1234")
    assert await push.fanout(database) == 2
    stats = await push.deliver_due(database)
    assert stats == {"sent": 2}

    oauth = providers.sends("oauth2.googleapis.com")
    assert len(oauth) == 1, "OAuth token must be cached between sends"
    form = dict(item.split("=", 1) for item in oauth[0].content.decode().split("&"))
    claims = jwt.decode(form["assertion"], RSA_KEY.public_key(), algorithms=["RS256"], audience="https://oauth2.googleapis.com/token")
    assert claims["iss"] == "push@p.iam.gserviceaccount.com"
    assert claims["scope"] == "https://www.googleapis.com/auth/firebase.messaging"

    sent = providers.sends("fcm.googleapis.com")
    assert sent[0].url.path == "/v1/projects/corgi-test/messages:send"
    assert sent[0].headers["authorization"] == "Bearer oauth-access"
    messages = [json.loads(call.content)["message"] for call in sent]
    assert messages[0]["token"] == FCM_TOKEN
    # Styled data messages (push_style.py): the app draws title, picture, buttons and channel itself.
    data = messages[0]["data"]
    assert (data["notification_id"], data["kind"], data["style"], data["channel"], data["section"]) == (str(payment.id), "payment_success", "payment", "important", "vpn")
    assert data["title"].startswith("✅ ") and json.loads(data["buttons"]) == [{"label": "Подключить", "section": "vpn"}]
    assert all(isinstance(v, str) for v in data.values()), "FCM data values are strings"
    assert "notification" not in messages[0] and messages[0]["android"]["priority"] == "HIGH"
    assert messages[1]["data"]["body"] == push.PRIVATE_KINDS["support.reply"]
    assert "1234" not in sent[1].content.decode()
    rows = (await database.execute(select(PushDelivery))).scalars().all()
    assert {row.status for row in rows} == {"sent"} and all(row.sent_at for row in rows)
    assert await push.fanout(database) == 0, "fan-out happens once per notification"


@pytest.mark.asyncio
async def test_fcm_unregistered_token_revokes_device_and_pending_deliveries(database, sessions, providers):
    await sessions()
    device_id = (await register(database))["device"]["id"]
    await notify(database)
    await notify(database)
    providers.fcm_status = [(404, {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}})]
    await push.fanout(database)
    stats = await push.deliver_due(database, limit=1)
    assert stats == {"failed": 1}
    device = await database.get(PushDevice, device_id)
    assert device.revoke_reason == "invalid_token"
    statuses = sorted(row.status for row in (await database.execute(select(PushDelivery))).scalars().all())
    assert statuses == ["failed", "skipped"]


@pytest.mark.asyncio
async def test_apns_delivery_uses_es256_provider_token_topic_and_sandbox(database, sessions, providers):
    await sessions()
    await register(database, platform="ios", token=APNS_TOKEN)
    row = await notify(database, body="x" * 400)
    await push.fanout(database)
    assert await push.deliver_due(database) == {"sent": 1}
    call = providers.sends("api.sandbox.push.apple.com")[0]
    assert call.url.path == f"/3/device/{APNS_TOKEN}"
    assert call.headers["apns-topic"] == "shop.remnawave.user"
    assert call.headers["apns-push-type"] == "alert"
    assert call.headers["apns-collapse-id"] == f"n{row.id}"
    bearer = call.headers["authorization"].removeprefix("bearer ")
    assert jwt.get_unverified_header(bearer)["kid"] == "KEY1234567"
    assert jwt.decode(bearer, EC_KEY.public_key(), algorithms=["ES256"])["iss"] == "TEAM123456"
    body = json.loads(call.content)
    assert len(body["aps"]["alert"]["body"]) <= push.BODY_LIMIT
    assert body["notification_id"] == str(row.id)


@pytest.mark.asyncio
async def test_apns_gone_revokes_device(database, sessions, providers):
    await sessions()
    device_id = (await register(database, platform="ios", token=APNS_TOKEN))["device"]["id"]
    providers.apns_status = [(410, {"reason": "Unregistered"})]
    await notify(database)
    await push.fanout(database)
    assert await push.deliver_due(database) == {"failed": 1}
    assert (await database.get(PushDevice, device_id)).revoke_reason == "invalid_token"


@pytest.mark.asyncio
async def test_transient_errors_back_off_then_fail_after_max_attempts(database, sessions, providers):
    await sessions()
    device_id = (await register(database))["device"]["id"]
    providers.fcm_status = [(503, {"error": {"status": "UNAVAILABLE"}})]
    await notify(database)
    await push.fanout(database)
    now = datetime.utcnow()
    assert await push.deliver_due(database, now=now) == {"retry": 1}
    delivery = (await database.execute(select(PushDelivery))).scalar_one()
    assert delivery.status == "queued" and delivery.next_attempt_at == now + timedelta(seconds=30)
    assert await push.deliver_due(database, now=now) == {}, "not due before the backoff elapses"
    for attempt in range(2, push.MAX_ATTEMPTS + 1):
        now = delivery.next_attempt_at
        await push.deliver_due(database, now=now)
        await database.refresh(delivery)
    assert delivery.status == "failed" and delivery.attempts == push.MAX_ATTEMPTS
    device = await database.get(PushDevice, device_id)
    assert device.revoked_at is None and device.failures == 1


@pytest.mark.asyncio
async def test_signed_out_session_stops_delivery_without_calling_provider(database, sessions, providers):
    session = await sessions()
    device_id = (await register(database))["device"]["id"]
    await notify(database)
    await push.fanout(database)
    session.revoked_at = datetime.utcnow()
    await database.commit()
    assert await push.deliver_due(database) == {"skipped": 1}
    assert providers.calls == []
    assert (await database.get(PushDevice, device_id)).revoke_reason == "session_ended"
    await notify(database)
    assert await push.fanout(database) == 0, "revoked devices receive nothing new"


@pytest.mark.asyncio
async def test_deleted_account_and_read_or_stale_notifications_are_not_pushed(database, sessions, providers):
    await sessions()
    await register(database)
    stale = await notify(database, created_at=datetime.utcnow() - timedelta(hours=2))
    read = await notify(database, read_at=datetime.utcnow())
    assert await push.fanout(database) == 0
    assert (await database.get(Notification, stale.id)).push_fanout_at is not None
    assert (await database.get(Notification, read.id)).push_fanout_at is not None
    await notify(database)
    await push.fanout(database)
    user = await database.get(User, 1)
    user.deleted_at = datetime.utcnow()
    await database.commit()
    assert await push.deliver_due(database) == {"skipped": 1}
    assert providers.calls == []


@pytest.mark.asyncio
async def test_without_provider_keys_nothing_is_queued(database, sessions, monkeypatch):
    for key in ("fcm_project_id", "fcm_service_account_json", "apns_key_id", "apns_team_id", "apns_private_key"):
        monkeypatch.setattr(settings, key, "")
    await sessions()
    await register(database)
    row = await notify(database)
    assert await push.fanout(database) == 0
    assert (await database.get(Notification, row.id)).push_fanout_at is not None
    with pytest.raises(HTTPException) as error:
        await push.test_push(None, database)
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_invalid_service_account_is_config_error_not_token_loss(database, sessions, providers, monkeypatch):
    monkeypatch.setattr(settings, "fcm_service_account_json", "%%%not-json%%%")
    await sessions()
    device_id = (await register(database))["device"]["id"]
    await notify(database)
    await push.fanout(database)
    assert await push.deliver_due(database) == {"retry": 1}
    delivery = (await database.execute(select(PushDelivery))).scalar_one()
    assert "FCM_SERVICE_ACCOUNT_JSON" in delivery.last_error
    assert (await database.get(PushDevice, device_id)).revoked_at is None


@pytest.mark.asyncio
async def test_unregister_delete_and_test_push_are_owner_scoped(database, sessions, providers):
    await sessions(2)
    foreign = (await register(database, token="foreign-token-" + "z" * 20))["device"]["id"]
    await sessions(1)
    with pytest.raises(HTTPException) as error:
        await push.test_push(None, database)
    assert error.value.status_code == 409
    own = (await register(database))["device"]["id"]
    assert (await push.unregister_device(push.TokenIn(token="foreign-token-" + "z" * 20), None, database))["revoked"] == 0
    with pytest.raises(HTTPException) as error:
        await push.delete_device(foreign, None, database)
    assert error.value.status_code == 404
    assert (await push.test_push(None, database)) == {"queued": True}
    with pytest.raises(HTTPException) as error:
        await push.test_push(None, database)
    assert error.value.status_code == 429
    await push.fanout(database)
    assert await push.deliver_due(database) == {"sent": 1}
    assert (await push.unregister_device(push.TokenIn(token=FCM_TOKEN), None, database))["revoked"] == 1
    assert (await database.get(PushDevice, own)).revoke_reason == "unregistered"
    assert (await database.get(PushDevice, foreign)).revoked_at is None


@pytest.mark.asyncio
async def test_admin_status_reports_configuration_and_counts_without_tokens(database, sessions, providers):
    await sessions()
    await register(database)
    await register(database, platform="ios", token=APNS_TOKEN)
    await notify(database)
    await push.fanout(database)
    await push.deliver_due(database)
    status = await push.admin_push_status(database, None)
    assert status["providers"]["fcm"]["configured"] and status["providers"]["apns"]["environment"] == "sandbox"
    assert status["devices"] == {"android": 1, "ios": 1}
    assert status["deliveries_24h"] == {"sent": 2}
    assert FCM_TOKEN not in json.dumps(status) and APNS_TOKEN not in json.dumps(status)


@pytest.mark.asyncio
async def test_cleanup_removes_old_revoked_devices_and_deliveries(database, sessions, providers):
    await sessions()
    device_id = (await register(database))["device"]["id"]
    await notify(database)
    await push.fanout(database)
    await push.deliver_due(database)
    device = await database.get(PushDevice, device_id)
    device.revoked_at = datetime.utcnow() - timedelta(days=40)
    await database.commit()
    await push.cleanup(database, now=datetime.utcnow() + timedelta(days=31))
    assert (await database.execute(select(PushDevice))).scalars().all() == []
    assert (await database.execute(select(PushDelivery))).scalars().all() == []


def test_push_content_clips_whitespace_and_length():
    row = Notification(id=7, kind="admin.bulk", title="  Новая\n акция  " + "т" * 100, body="a  b\n" * 100)
    title, body = push.push_content(row)
    assert title.startswith("Новая акция") and len(title) == push.TITLE_LIMIT and title.endswith("…")
    assert "\n" not in body and len(body) == push.BODY_LIMIT
