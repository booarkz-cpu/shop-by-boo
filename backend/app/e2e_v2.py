"""Staging E2E v2: the end-to-end proof that opens real payments.

Two sides of one contract:

* **Staging** (``APP_ENV=staging``) runs a real order per provider through the
  ordinary checkout and records every stage from the shop's own tables:
  checkout and its idempotent retry, the signed provider webhook, independent
  provider reconciliation, VPN delivery checked by the remote user ID, replay of
  the very same signed webhook (twice, concurrently), forged webhooks, refund
  through the ordinary admin refund code, access revocation, and a late success
  after the refund. The result is computed by the server and signed with the
  staging Ed25519 key.
* **Production** accepts only an attestation signed by the configured staging
  key, carrying the nonce it issued for its current configuration revision,
  produced by the same distribution tag and at most 24 hours old. Only then can
  an administrator open the production payment gate.

Nothing here accepts check names from a client, and a missing, unknown or
interrupted stage fails closed.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import (AdminUser, E2ECase, E2ERun, E2EWebhookCapture, FinancialLedger, Payment, PaymentProviderEvent, Plan,
                     ProvisioningOperation, RefundRequest, Subscription, User)
from .release_identity import DISTRIBUTION_TAG, RUNTIME_VERSION
from .security import decrypt_secret, encrypt_secret, require_permission

logger = logging.getLogger(__name__)
router = APIRouter()

CONTRACT_VERSION = 2
PROVIDERS = ("yookassa", "platega", "rollypay")
REQUIRED_CHECKS = (
    "checkout", "idempotent_checkout", "signed_webhook", "provider_match", "fulfilled", "duplicate_ignored",
    "tamper_rejected", "refund_confirmed", "refund_idempotent", "access_revoked", "late_success_ignored",
)
CHECK_LABELS = {
    "checkout": "Заказ через обычный checkout",
    "idempotent_checkout": "Повтор с тем же ключом не создал второй заказ",
    "signed_webhook": "Получен подписанный webhook провайдера",
    "provider_match": "Независимая сверка с провайдером",
    "fulfilled": "Выдача: одна подписка, пользователь Remnawave по ID",
    "duplicate_ignored": "Повтор того же webhook (дважды одновременно) ничего не изменил",
    "tamper_rejected": "Поддельные webhook отклонены без изменений",
    "refund_confirmed": "Возврат подтверждён провайдером",
    "refund_idempotent": "Повторный возврат не создал вторую операцию",
    "access_revoked": "Доступ в Remnawave отозван",
    "late_success_ignored": "Успех после возврата не вернул оплату и доступ",
}
WEBHOOK_PATHS = {p: f"/api/webhooks/{p}" for p in PROVIDERS}
# A forged copy that must be refused outright (HTTP 4xx), per provider.
REJECT_VARIANT = {"yookassa": "foreign_peer", "platega": "bad_credentials", "rollypay": "bad_credentials"}
ATTESTATION_PREFIX = "e2e2"
NONCE_PREFIX = "e2e2n."
NONCE_RE = re.compile(r"^e2e2n\.[A-Za-z0-9]{8,32}\.[A-Za-z0-9]{16,48}$")
MAX_AGE_HOURS = 24
CLOCK_SKEW = timedelta(minutes=2)
HEARTBEAT_STALE = timedelta(minutes=3)
SIGNING_KEY_SETTING = "e2e_v2.signing_key"
ADMISSION_CONFIG_KEY = "staging_e2e.v2.config"
ADMISSION_STATUS_KEY = "staging_e2e.v2.status"
BUYER_EMAIL = "e2e-buyer@staging.invalid"
# The buyer session is bound to its user agent like any customer session.
BUYER_AGENT = "staging-e2e-v2"
_TASKS: dict[str, asyncio.Task] = {}


def staging_enabled() -> bool:
    return (settings.app_env or "").strip().lower() == "staging"


def _now() -> datetime:
    return datetime.utcnow()


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Attestation
# ---------------------------------------------------------------------------

class AttestationError(ValueError):
    """The attestation cannot authorize payments; the message is shown to the operator."""


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def public_key_text(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64e(raw)


def parse_public_key(text: str) -> Ed25519PublicKey:
    try:
        raw = _b64d(str(text or "").strip())
        if len(raw) != 32:
            raise ValueError
        return Ed25519PublicKey.from_public_bytes(raw)
    except Exception as exc:
        raise AttestationError("Открытый ключ стенда указан неверно") from exc


def sign_attestation(payload: dict, key: Ed25519PrivateKey) -> str:
    body = canonical(payload)
    return f"{ATTESTATION_PREFIX}.{_b64e(body)}.{_b64e(key.sign(body))}"


def provider_result(case: E2ECase) -> dict:
    checks = [c for c in REQUIRED_CHECKS if c in (case.checks or [])]
    passed = case.status == "passed" and len(checks) == len(REQUIRED_CHECKS)
    return {"provider": case.provider, "status": "passed" if passed else "failed", "payment_id": case.payment_id,
            "order_id": case.order_id, "provider_payment_id": case.provider_payment_id, "checks": checks,
            "error": None if passed else (case.error or "не все этапы пройдены")}


def run_passed(providers: list[str], results: list[dict]) -> bool:
    by = {r.get("provider"): r for r in results}
    return bool(providers) and all(
        by.get(p, {}).get("status") == "passed" and set(REQUIRED_CHECKS) <= set(by[p].get("checks") or []) for p in providers)


def verify_attestation(text: str, public_key: str, *, nonce: str, issued_at: datetime, now: datetime,
                       providers: list[str], distribution_tag: str = DISTRIBUTION_TAG) -> dict:
    """Return the attested payload or raise AttestationError with the exact reason."""
    parts = str(text or "").strip().split(".")
    if len(parts) != 3 or parts[0] != ATTESTATION_PREFIX:
        raise AttestationError("Это не результат E2E v2: ожидается строка вида e2e2.…")
    key = parse_public_key(public_key)
    try:
        body, signature = _b64d(parts[1]), _b64d(parts[2])
    except Exception as exc:
        raise AttestationError("Результат повреждён") from exc
    try:
        key.verify(signature, body)
    except InvalidSignature as exc:
        raise AttestationError("Подпись не совпадает с ключом стенда") from exc
    try:
        payload = json.loads(body)
    except Exception as exc:
        raise AttestationError("Результат повреждён") from exc
    if not isinstance(payload, dict) or payload.get("contract_version") != CONTRACT_VERSION:
        raise AttestationError("Неверная версия контракта")
    if payload.get("environment") != "staging":
        raise AttestationError("Результат получен не на стенде APP_ENV=staging")
    if payload.get("nonce") != nonce:
        raise AttestationError("Код запуска не совпадает: получите новый код и запустите проверку с ним")
    if payload.get("distribution_tag") != distribution_tag:
        raise AttestationError(f"Стенд работает на {payload.get('distribution_tag')}, а этот сервер — на {distribution_tag}")
    if payload.get("status") != "passed" or payload.get("full_e2e") is not True:
        raise AttestationError("Проверка на стенде не пройдена")
    results = payload.get("provider_results")
    if not isinstance(results, list) or not run_passed(list(providers), results):
        raise AttestationError("Не все выбранные платёжные системы прошли все этапы")
    try:
        finished = datetime.fromisoformat(str(payload["finished_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise AttestationError("Нет времени завершения") from exc
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    issued = issued_at if issued_at.tzinfo else issued_at.replace(tzinfo=timezone.utc)
    if finished > now + CLOCK_SKEW:
        raise AttestationError("Время завершения в будущем: проверьте часы стенда")
    if finished < issued - CLOCK_SKEW:
        raise AttestationError("Проверка завершена раньше, чем выдан код запуска")
    if now - finished > timedelta(hours=MAX_AGE_HOURS):
        raise AttestationError("Результату больше 24 часов")
    return payload


async def signing_key(db: AsyncSession) -> Ed25519PrivateKey:
    from . import main
    stored = await main.setting_value(db, SIGNING_KEY_SETTING, "")
    if stored:
        return Ed25519PrivateKey.from_private_bytes(_b64d(decrypt_secret(stored)))
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    await main.set_setting(db, SIGNING_KEY_SETTING, encrypt_secret(_b64e(raw)))
    await db.commit()
    return key


# ---------------------------------------------------------------------------
# Hooks called from checkout and webhook handlers
# ---------------------------------------------------------------------------

async def checkout_allowed(db: AsyncSession, request: Request, payload: dict) -> bool:
    """On staging only: the run's own buyer may check out while its run is active."""
    if not staging_enabled():
        return False
    run_id = request.headers.get("X-E2E-Run", "")
    if not run_id:
        return False
    run = await db.get(E2ERun, run_id)
    if not run or not run.active or run.status != "running":
        return False
    if str(payload.get("provider") or "") not in (run.providers or []):
        return False
    from . import main
    try:
        user = await main.user_from_token(request, db)
    except HTTPException:
        return False
    return bool(user and user.id == run.buyer_user_id)


async def capture_webhook(provider: str, request: Request, raw: bytes, payment_id: int | None) -> None:
    """Keep the first *verified* webhook of an active case, encrypted, to replay it later.

    Called after the handler verified the webhook; never raises into the handler."""
    if not staging_enabled() or not payment_id:
        return
    try:
        from . import main
        async with AsyncSession(main.engine, expire_on_commit=False) as db:
            case = (await db.execute(select(E2ECase).join(E2ERun, E2ERun.id == E2ECase.run_id).where(
                E2ECase.payment_id == payment_id, E2ECase.provider == provider, E2ERun.active.is_(True)))).scalar_one_or_none()
            if not case:
                return
            if await db.scalar(select(func.count()).select_from(E2EWebhookCapture).where(E2EWebhookCapture.case_id == case.id)):
                return
            client = request.client
            data = {"body": base64.b64encode(raw).decode(), "headers": [[k, v] for k, v in request.headers.items()],
                    "peer": [client.host, client.port] if client else ["127.0.0.1", 0], "path": request.url.path,
                    "host": request.headers.get("host") or "localhost"}
            db.add(E2EWebhookCapture(case_id=case.id, provider=provider, path=request.url.path,
                                     body_sha256=hashlib.sha256(raw).hexdigest(),
                                     data_encrypted=encrypt_secret(json.dumps(data)), received_at=_now()))
            await db.commit()
    except IntegrityError:
        return
    except Exception as exc:  # the webhook itself must not fail because of the recorder
        logger.warning("E2E webhook capture failed: %s", type(exc).__name__)


# ---------------------------------------------------------------------------
# Operations against the running shop (replaced by fakes in tests)
# ---------------------------------------------------------------------------

class CheckFailed(Exception):
    """A stage of the case failed; the message is shown to the operator."""


class ShopOps:
    """Drives the real shop: ASGI calls to its own routes and the admin refund code."""

    def __init__(self, session_factory: Callable[[], AsyncSession]):
        self.session_factory = session_factory

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def _client(self, peer: tuple[str, int], host: str = "localhost"):
        import httpx
        from . import main
        transport = httpx.ASGITransport(app=main.app, client=peer, raise_app_exceptions=False)
        return httpx.AsyncClient(transport=transport, base_url=f"http://{host}", timeout=120)

    async def buyer(self, db: AsyncSession) -> User:
        user = (await db.execute(select(User).where(User.email == BUYER_EMAIL))).scalar_one_or_none()
        if not user:
            user = User(email=BUYER_EMAIL, username="E2E buyer", referral_code="E2E" + secrets.token_hex(5).upper())
            db.add(user)
            await db.commit()
        return user

    async def buyer_token(self, db: AsyncSession, user: User) -> str:
        from starlette.requests import Request as StarletteRequest
        from . import main
        scope = {"type": "http", "method": "POST", "path": "/e2e", "headers": [(b"user-agent", BUYER_AGENT.encode())], "client": ("127.0.0.1", 0)}
        return await main.create_user_session(db, user, StarletteRequest(scope), ttl_minutes=240)

    async def checkout(self, provider: str, plan_id: int, key: str, token: str, run_id: str) -> tuple[int, dict]:
        async with self._client(("127.0.0.1", 50000)) as client:
            response = await client.post("/api/payments/create", json={"plan_id": plan_id, "provider": provider},
                                         headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key, "X-E2E-Run": run_id,
                                                  "User-Agent": BUYER_AGENT})
        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text[:300]}
        return response.status_code, body if isinstance(body, dict) else {"detail": body}

    async def verify_provider(self, provider: str, provider_payment_id: str, amount: Decimal, currency: str, order_id: str) -> bool:
        from . import main
        cls = {"yookassa": main.YooKassaProvider, "platega": main.PlategaProvider, "rollypay": main.RollyPayProvider}[provider]
        return bool(await cls().verify_succeeded(provider_payment_id, amount, currency, order_id))

    async def remote_state(self, uuid_: str) -> dict | None:
        from . import main
        rw = main.RemnawaveClient()
        try:
            user = await rw.get_user(uuid_)
        except Exception:
            return None
        if not user:
            return None
        try:
            expiry = await rw.get_expiry(uuid_)
        except Exception:
            expiry = None
        status = str(user.get("status") or user.get("state") or "").lower()
        return {"status": status, "expires_at": expiry.replace(tzinfo=None) if isinstance(expiry, datetime) and expiry.tzinfo else expiry}

    async def replay(self, capture: dict, variant: str | None = None) -> int:
        body = base64.b64decode(capture["body"])
        skip = {"host", "content-length", "cookie", "authorization", "transfer-encoding"}
        headers = [(k, v) for k, v in capture["headers"] if k.lower() not in skip]
        peer = (str(capture["peer"][0]), int(capture["peer"][1] or 0))
        if variant == "foreign_peer":
            peer = ("198.51.100.23", 40000)
            headers = [(k, v) for k, v in headers if k.lower() not in {"x-forwarded-for", "x-real-ip", "forwarded"}]
        elif variant == "bad_credentials":
            headers = [(k, _corrupt(v) if k.lower() in {"x-secret", "x-signature", "x-rollypay-signature"} else v) for k, v in headers]
        elif variant == "altered_body":
            body = _alter_body(body)
        async with self._client(peer, capture.get("host") or "localhost") as client:
            response = await client.post(capture["path"], content=body, headers=headers)
        return response.status_code

    async def refund(self, db: AsyncSession, admin: AdminUser, payment_id: int) -> dict:
        from . import main
        request = await main.request_refund(payment_id, main.RefundIn(reason="Staging E2E v2"), db, admin)
        refund_id = int(request["id"])
        refund = await db.get(RefundRequest, refund_id)
        if refund and refund.status == "requested":
            await main.approve_refund(refund_id, db, admin)
        refund = await db.get(RefundRequest, refund_id, populate_existing=True)
        if refund and refund.status in {"requested", "approved", "review"} and not refund.provider_refund_id:
            await main.execute_refund(refund_id, db, admin)
        return {"id": refund_id}

    async def reconcile(self, db: AsyncSession, admin: AdminUser, refund_id: int) -> None:
        from . import main
        refund = await db.get(RefundRequest, refund_id, populate_existing=True)
        if refund and refund.provider_refund_id and refund.status == "processing":
            await main.reconcile_refund(refund_id, db, admin)
        elif refund and refund.status == "refunded_pending_revoke":
            await main.retry_refund_revoke(refund_id, db, admin)

    async def repeat_refund(self, db: AsyncSession, admin: AdminUser, payment_id: int, refund_id: int) -> bool:
        """A second request returns the same refund and a second execution is refused."""
        from . import main
        again = await main.request_refund(payment_id, main.RefundIn(reason="Staging E2E v2 repeat"), db, admin) \
            if (await db.get(Payment, payment_id, populate_existing=True)).status in {"paid", "fulfilled"} else {"id": refund_id}
        if int(again["id"]) != refund_id:
            return False
        try:
            await main.execute_refund(refund_id, db, admin)
        except HTTPException as exc:
            return 400 <= exc.status_code < 500
        return False


def _corrupt(value: str) -> str:
    value = str(value or "")
    if not value:
        return "forged"
    last = value[-1]
    return value[:-1] + ("0" if last != "0" else "1")


def _alter_body(raw: bytes) -> bytes:
    """Change the payment identity or amount but keep the original signature headers."""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw + b" "
    forged = "e2e-forged-" + secrets.token_hex(6)

    def walk(node):
        if isinstance(node, dict):
            for key in list(node):
                if key in {"id", "payment_id", "transactionId", "Id"} and isinstance(node[key], (str, int)):
                    node[key] = forged
                elif key in {"amount", "value", "Amount"} and isinstance(node[key], (str, int, float)):
                    node[key] = "1.00"
                else:
                    walk(node[key])
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(data)
    return json.dumps(data).encode()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class Runner:
    payment_poll = 5.0
    fulfillment_timeout = 300.0
    webhook_grace = 60.0
    refund_timeout = 900.0
    refund_poll = 10.0

    def __init__(self, session_factory: Callable[[], AsyncSession], ops: ShopOps | None = None):
        self.session_factory = session_factory
        self.ops = ops or ShopOps(session_factory)

    async def _update_case(self, case_id: int, **fields) -> None:
        async with self.session_factory() as db:
            case = await db.get(E2ECase, case_id)
            for key, value in fields.items():
                setattr(case, key, value)
            case.updated_at = _now()
            await db.commit()

    async def _add_check(self, case_id: int, check: str) -> None:
        async with self.session_factory() as db:
            case = await db.get(E2ECase, case_id)
            case.checks = [c for c in REQUIRED_CHECKS if c in set(case.checks or []) | {check}]
            case.updated_at = _now()
            await db.commit()

    async def _alive(self, run_id: str) -> bool:
        async with self.session_factory() as db:
            run = await db.get(E2ERun, run_id)
            if not run or run.status != "running":
                return False
            run.heartbeat_at = _now()
            await db.commit()
            return True

    async def _wait(self, run_id: str, timeout: float, poll: float, probe):
        """Poll ``probe`` until it returns a truthy value; stop on timeout or cancellation."""
        waited = 0.0
        while True:
            value = await probe()
            if value:
                return value
            if waited >= timeout:
                return None
            if not await self._alive(run_id):
                raise CheckFailed("Проверка остановлена")
            await self.ops.sleep(poll)
            waited += poll

    async def _payment(self, payment_id: int) -> Payment:
        async with self.session_factory() as db:
            return await db.get(Payment, payment_id, populate_existing=True)

    async def snapshot(self, case_id: int) -> dict:
        async with self.session_factory() as db:
            case = await db.get(E2ECase, case_id)
            p = await db.get(Payment, case.payment_id, populate_existing=True)
            sub = await db.get(Subscription, p.subscription_id, populate_existing=True) if p.subscription_id else None
            data = {
                "payment_status": p.status, "fulfillment_status": p.fulfillment_status,
                "payments": await db.scalar(select(func.count()).select_from(Payment).where(Payment.user_id == p.user_id)),
                "subscriptions": await db.scalar(select(func.count()).select_from(Subscription).where(Subscription.user_id == p.user_id)),
                "ledger": await db.scalar(select(func.count()).select_from(FinancialLedger).where(FinancialLedger.user_id == p.user_id)),
                "operations": await db.scalar(select(func.count()).select_from(ProvisioningOperation).where(ProvisioningOperation.payment_id == p.id)),
                "refunds": await db.scalar(select(func.count()).select_from(RefundRequest).where(RefundRequest.payment_id == p.id)),
                "subscription_expires_at": _iso(sub.expires_at) if sub else None,
            }
        remote = await self.ops.remote_state(case.remote_user_id) if case.remote_user_id else None
        data["remote"] = {"status": remote.get("status"), "expires_at": _iso(remote.get("expires_at"))} if remote else None
        return data

    async def _capture(self, case_id: int) -> dict | None:
        async with self.session_factory() as db:
            row = (await db.execute(select(E2EWebhookCapture).where(E2EWebhookCapture.case_id == case_id))).scalar_one_or_none()
            if not row or not row.data_encrypted:
                return None
            return json.loads(decrypt_secret(row.data_encrypted))

    async def run(self, run_id: str) -> None:
        try:
            async with self.session_factory() as db:
                run = await db.get(E2ERun, run_id)
                run.status = "running"; run.started_at = _now(); run.heartbeat_at = _now()
                buyer = await self.ops.buyer(db)
                run.buyer_user_id = buyer.id
                await db.commit()
                token = await self.ops.buyer_token(db, buyer)
                cases = (await db.execute(select(E2ECase).where(E2ECase.run_id == run_id).order_by(E2ECase.id))).scalars().all()
                case_ids = [(c.id, c.provider) for c in cases]
            for case_id, provider in case_ids:
                if not await self._alive(run_id):
                    break
                await self._update_case(case_id, status="running")
                try:
                    await self.case(run_id, case_id, provider, token)
                    await self._update_case(case_id, status="passed", stage="done", error=None)
                except CheckFailed as exc:
                    await self._update_case(case_id, status="failed", error=str(exc)[:2000])
                except Exception as exc:
                    logger.exception("E2E v2 case %s failed", case_id)
                    await self._update_case(case_id, status="failed", error=f"Внутренняя ошибка: {type(exc).__name__}: {str(exc)[:500]}")
        except Exception as exc:
            logger.exception("E2E v2 run %s failed", run_id)
            async with self.session_factory() as db:
                run = await db.get(E2ERun, run_id)
                run.error = f"{type(exc).__name__}: {str(exc)[:500]}"
                await db.commit()
        await self.finish(run_id)

    async def finish(self, run_id: str) -> None:
        async with self.session_factory() as db:
            run = await db.get(E2ERun, run_id, populate_existing=True)
            cases = (await db.execute(select(E2ECase).where(E2ECase.run_id == run_id).order_by(E2ECase.id))).scalars().all()
            results = [provider_result(c) for c in cases]
            cancelled = run.status == "cancelled"
            passed = not cancelled and not run.error and run_passed(list(run.providers), results)
            run.status = "cancelled" if cancelled else ("passed" if passed else "failed")
            run.finished_at = _now(); run.active = None
            payload = {"contract_version": CONTRACT_VERSION, "environment": "staging" if staging_enabled() else (settings.app_env or ""),
                       "distribution_tag": run.distribution_tag, "runtime_version": RUNTIME_VERSION, "nonce": run.nonce,
                       "run_id": run.id, "status": run.status, "full_e2e": passed, "started_at": _iso(run.started_at),
                       "finished_at": _iso(run.finished_at), "providers": list(run.providers), "provider_results": results}
            run.attestation = sign_attestation(payload, await signing_key(db))
            # The captured bodies were only needed for replay inside this run.
            await db.execute(update(E2EWebhookCapture).where(E2EWebhookCapture.case_id.in_([c.id for c in cases])).values(data_encrypted=None))
            from . import main
            await main.audit(db, "staging_e2e.v2.finished", run.admin_email, run.id, {"status": run.status, "providers": list(run.providers)})
            await db.commit()

    async def case(self, run_id: str, case_id: int, provider: str, token: str) -> None:
        async with self.session_factory() as db:
            run = await db.get(E2ERun, run_id)
            plan_id, buyer_id, timeout = run.plan_id, run.buyer_user_id, run.payment_timeout_seconds
        key = f"e2e-{run_id}-{provider}"

        # 1. Real checkout through the ordinary route, then the same request again.
        await self._update_case(case_id, stage="checkout", idempotency_key=key)
        started = _now()
        status, body = await self.ops.checkout(provider, plan_id, key, token, run_id)
        if status != 200 or not body.get("id"):
            raise CheckFailed(f"Checkout ответил HTTP {status}: {json.dumps(body.get('detail', body), ensure_ascii=False)[:300]}")
        async with self.session_factory() as db:
            payments = (await db.execute(select(Payment).where(Payment.user_id == buyer_id, Payment.idempotency_key == key))).scalars().all()
        if len(payments) != 1 or payments[0].provider != provider:
            raise CheckFailed("Checkout не создал ровно один заказ этой платёжной системы")
        payment = payments[0]
        if not str(payment.checkout_url or "").startswith("https://"):
            raise CheckFailed("Провайдер не вернул HTTPS-страницу оплаты")
        await self._update_case(case_id, payment_id=payment.id, order_id=payment.order_id, provider_payment_id=payment.provider_payment_id,
                                amount=payment.amount, currency=payment.currency, checkout_url=payment.checkout_url, checkout_at=started)
        await self._add_check(case_id, "checkout")
        status2, body2 = await self.ops.checkout(provider, plan_id, key, token, run_id)
        async with self.session_factory() as db:
            count = await db.scalar(select(func.count()).select_from(Payment).where(Payment.user_id == buyer_id, Payment.idempotency_key == key))
        if status2 != 200 or body2.get("id") != body.get("id") or count != 1:
            raise CheckFailed("Повтор checkout с тем же ключом дал другой результат")
        await self._add_check(case_id, "idempotent_checkout")

        # 2. The buyer pays on the provider's sandbox page; only the webhook may mark it paid.
        await self._update_case(case_id, stage="awaiting_payment")

        async def paid():
            p = await self._payment(payment.id)
            if p.status in {"failed", "canceled", "cancelled", "creation_unknown", "refunded"}:
                raise CheckFailed(f"Заказ перешёл в состояние {p.status}")
            return p if p.status in {"paid", "fulfilled"} else None
        if not await self._wait(run_id, timeout, self.payment_poll, paid):
            raise CheckFailed("Оплата не завершена за отведённое время: оплатите заказ на странице провайдера")

        # 3. The verified provider webhook of this very order, received during this run.
        await self._update_case(case_id, stage="webhook")

        async def webhook():
            async with self.session_factory() as db:
                event = (await db.execute(select(PaymentProviderEvent).where(
                    PaymentProviderEvent.provider == provider, PaymentProviderEvent.payment_id == payment.id,
                    PaymentProviderEvent.status == "processed", PaymentProviderEvent.received_at >= started - CLOCK_SKEW)
                    .order_by(PaymentProviderEvent.id))).scalars().first()
            capture = await self._capture(case_id)
            return (event, capture) if event and capture else None
        found = await self._wait(run_id, self.webhook_grace, 2.0, webhook)
        if not found:
            raise CheckFailed("Нет подписанного webhook провайдера для этого заказа: оплата отмечена другим путём")
        event, capture = found
        await self._update_case(case_id, webhook_event_id=event.event_id)
        await self._add_check(case_id, "signed_webhook")

        p = await self._payment(payment.id)
        if p.provider_payment_id != payment.provider_payment_id and payment.provider_payment_id:
            raise CheckFailed("ID платежа у провайдера изменился")
        if not await self.ops.verify_provider(provider, str(p.provider_payment_id), Decimal(str(p.amount)), p.currency, p.order_id):
            raise CheckFailed("Провайдер не подтвердил оплату с этой суммой, валютой и номером заказа")
        if Decimal(str(p.amount)) != Decimal(str(payment.amount)) or p.currency != payment.currency:
            raise CheckFailed("Сумма или валюта заказа изменились")
        await self._add_check(case_id, "provider_match")

        # 4. Delivery: one provisioning operation, the subscription and the remote user by its ID.
        await self._update_case(case_id, stage="fulfillment")

        async def fulfilled():
            q = await self._payment(payment.id)
            if q.fulfillment_status == "failed" and q.fulfillment_terminal:
                raise CheckFailed("Выдача окончательно не удалась: смотрите очередь задач")
            return q if q.fulfillment_status == "completed" else None
        p = await self._wait(run_id, self.fulfillment_timeout, 3.0, fulfilled)
        if not p:
            raise CheckFailed("Выдача VPN не завершилась за 5 минут")
        async with self.session_factory() as db:
            ops = (await db.execute(select(ProvisioningOperation).where(ProvisioningOperation.payment_id == p.id))).scalars().all()
            sub = await db.get(Subscription, p.subscription_id) if p.subscription_id else None
        if len(ops) != 1 or not sub or not sub.remnawave_uuid or ops[0].remote_user_id not in {None, sub.remnawave_uuid}:
            raise CheckFailed("Выдача не связана ровно с одной операцией и подпиской")
        remote = await self.ops.remote_state(sub.remnawave_uuid)
        if not remote or remote.get("status") in {"disabled", "expired", "limited"}:
            raise CheckFailed("Пользователь Remnawave не найден или не активен")
        expiry = remote.get("expires_at")
        if not expiry or not sub.expires_at or abs((expiry - sub.expires_at).total_seconds()) > 86400 or expiry <= _now():
            raise CheckFailed("Срок в Remnawave не совпадает со сроком подписки")
        await self._update_case(case_id, subscription_id=sub.id, remote_user_id=sub.remnawave_uuid)
        await self._add_check(case_id, "fulfilled")

        # 5. The same signed webhook, twice at once: nothing may change.
        await self._update_case(case_id, stage="duplicate")
        before = await self.snapshot(case_id)
        statuses = await asyncio.gather(self.ops.replay(capture), self.ops.replay(capture))
        after = await self.snapshot(case_id)
        if any(s >= 500 for s in statuses):
            raise CheckFailed(f"Повтор webhook ответил {statuses}")
        if before != after:
            raise CheckFailed("Повтор webhook изменил заказ, подписку, журнал или срок")
        await self._add_check(case_id, "duplicate_ignored")

        # 6. Forged copies: wrong sender or credentials, altered identity or amount.
        await self._update_case(case_id, stage="tamper")
        for variant in (REJECT_VARIANT[provider], "altered_body"):
            code = await self.ops.replay(capture, variant)
            if variant == REJECT_VARIANT[provider] and not 400 <= code < 500:
                raise CheckFailed(f"Поддельный webhook ({variant}) не отклонён: HTTP {code}")
            if await self.snapshot(case_id) != after:
                raise CheckFailed(f"Поддельный webhook ({variant}) изменил состояние")
        await self._add_check(case_id, "tamper_rejected")

        # 7. Refund through the ordinary admin refund code, confirmed by the provider.
        await self._update_case(case_id, stage="refund")
        async with self.session_factory() as db:
            run = await db.get(E2ERun, run_id)
            admin = await db.get(AdminUser, run.admin_id)
            if not admin or admin.disabled or admin.role != "admin":
                raise CheckFailed("Администратор, запустивший проверку, недоступен")
            try:
                refund_id = (await self.ops.refund(db, admin, payment.id))["id"]
            except HTTPException as exc:
                raise CheckFailed(f"Возврат не выполнен: {exc.detail}")

        async def refunded():
            async with self.session_factory() as db:
                admin = await db.get(AdminUser, run.admin_id)
                try:
                    await self.ops.reconcile(db, admin, refund_id)
                except HTTPException as exc:
                    # The provider status is not readable yet; poll again until the timeout.
                    logger.info("E2E v2 refund %s not reconciled yet: %s", refund_id, exc.detail)
                r = await db.get(RefundRequest, refund_id, populate_existing=True)
                q = await db.get(Payment, payment.id, populate_existing=True)
                if r.status == "failed":
                    raise CheckFailed("Провайдер отклонил возврат")
                return r if r.status == "refunded" and q.status == "refunded" else None
        refund = await self._wait(run_id, self.refund_timeout, self.refund_poll, refunded)
        if not refund:
            raise CheckFailed("Возврат не подтверждён провайдером за 15 минут")
        async with self.session_factory() as db:
            ledger = await db.scalar(select(func.count()).select_from(FinancialLedger).where(
                FinancialLedger.payment_id == payment.id, FinancialLedger.kind == "refund"))
        if ledger != 1:
            raise CheckFailed(f"В финансовом журнале {ledger} записей возврата вместо одной")
        await self._update_case(case_id, refund_id=refund_id, provider_refund_id=refund.provider_refund_id)
        await self._add_check(case_id, "refund_confirmed")

        async with self.session_factory() as db:
            admin = await db.get(AdminUser, run.admin_id)
            same = await self.ops.repeat_refund(db, admin, payment.id, refund_id)
            r = await db.get(RefundRequest, refund_id, populate_existing=True)
            ledger = await db.scalar(select(func.count()).select_from(FinancialLedger).where(
                FinancialLedger.payment_id == payment.id, FinancialLedger.kind == "refund"))
        if not same or r.provider_refund_id != refund.provider_refund_id or ledger != 1:
            raise CheckFailed("Повторный возврат создал вторую операцию")
        await self._add_check(case_id, "refund_idempotent")

        # 8. Access revoked in Remnawave and in the shop.
        remote = await self.ops.remote_state(sub.remnawave_uuid)
        async with self.session_factory() as db:
            sub_now = await db.get(Subscription, sub.id, populate_existing=True)
        if remote and remote.get("status") not in {"disabled", "expired", "limited"}:
            raise CheckFailed("Доступ в Remnawave не отозван после возврата")
        if not sub_now.expires_at or sub_now.expires_at > _now() + timedelta(minutes=1):
            raise CheckFailed("Подписка магазина не закрыта после возврата")
        await self._add_check(case_id, "access_revoked")

        # 9. The old success webhook after the refund must not restore anything.
        await self._update_case(case_id, stage="late_success")
        before = await self.snapshot(case_id)
        code = await self.ops.replay(capture)
        after = await self.snapshot(case_id)
        if code == 403 and provider == "rollypay":
            raise CheckFailed("Подпись RollyPay действует 5 минут, а возврат подтвердился позже: повторите проверку")
        if code >= 400:
            raise CheckFailed(f"Повтор успеха после возврата ответил HTTP {code}")
        if after != before or after["payment_status"] != "refunded":
            raise CheckFailed("Успех после возврата изменил заказ или вернул доступ")
        await self._add_check(case_id, "late_success_ignored")


# ---------------------------------------------------------------------------
# Admin API — staging side
# ---------------------------------------------------------------------------

class RunIn(BaseModel):
    nonce: str = Field(min_length=10, max_length=128)
    plan_id: int = Field(gt=0)
    providers: list[str] = Field(min_length=1, max_length=3)
    payment_timeout_seconds: int = Field(default=1800, ge=300, le=7200)


def _provider_configured(provider: str) -> bool:
    return {"yookassa": bool(settings.yookassa_shop_id and settings.yookassa_secret_key and settings.yookassa_webhook_ip_allowlist),
            "platega": bool(settings.platega_merchant_id and settings.platega_secret),
            "rollypay": bool(settings.rollypay_api_key and settings.rollypay_signing_secret)}.get(provider, False)


async def _recover_stale(db: AsyncSession) -> None:
    """A run whose process died is failed explicitly; it can never become passed."""
    rows = (await db.execute(select(E2ERun).where(E2ERun.active.is_(True)))).scalars().all()
    limit = _now() - HEARTBEAT_STALE
    for run in rows:
        task = _TASKS.get(run.id)
        if task and not task.done():
            continue
        if (run.heartbeat_at or run.created_at) < limit:
            run.status = "failed"; run.active = None; run.finished_at = _now()
            run.error = "Проверка прервана: процесс сервера перезапущен"
    await db.commit()


def _run_view(run: E2ERun, cases: list[E2ECase]) -> dict:
    return {"id": run.id, "status": run.status, "nonce": run.nonce, "providers": list(run.providers), "plan_id": run.plan_id,
            "admin": run.admin_email, "error": run.error, "created_at": _iso(run.created_at), "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at), "attestation": run.attestation,
            "cases": [{"provider": c.provider, "status": c.status, "stage": c.stage, "checks": list(c.checks or []),
                       "payment_id": c.payment_id, "order_id": c.order_id,
                       "checkout_url": c.checkout_url if c.stage == "awaiting_payment" else None,
                       "error": c.error} for c in cases]}


@router.get("/api/admin/e2e-v2/overview")
async def overview(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("staging_e2e.manage"))):
    data: dict[str, Any] = {"environment": (settings.app_env or "").lower(), "staging": staging_enabled(),
                            "distribution_tag": DISTRIBUTION_TAG, "checks": [{"id": c, "label": CHECK_LABELS[c]} for c in REQUIRED_CHECKS]}
    if staging_enabled():
        await _recover_stale(db)
        runs = (await db.execute(select(E2ERun).order_by(E2ERun.created_at.desc()).limit(10))).scalars().all()
        views = []
        for run in runs:
            cases = (await db.execute(select(E2ECase).where(E2ECase.run_id == run.id).order_by(E2ECase.id))).scalars().all()
            views.append(_run_view(run, cases))
        data["public_key"] = public_key_text(await signing_key(db))
        data["providers_configured"] = {p: _provider_configured(p) for p in PROVIDERS}
        data["runs"] = views
    else:
        from . import main
        cfg = await admission_config(db)
        data["admission"] = {"config": {k: cfg.get(k) for k in ("public_key", "providers", "staging_url")} if cfg else None,
                             "revision": (cfg or {}).get("revision"), "status": await admission_status(db),
                             "gate_enabled": await main.setting_value(db, main.PRODUCTION_PAYMENTS_GATE_KEY, "0") == "1",
                             "payments_allowed": await main.production_payments_allowed(db)}
    return data


@router.post("/api/admin/e2e-v2/runs")
async def start_run(payload: RunIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("staging_e2e.manage"))):
    if not staging_enabled():
        raise HTTPException(409, "Проверка запускается только на стенде с APP_ENV=staging")
    if admin.role != "admin":
        raise HTTPException(403, "Проверку запускает администратор: она выполняет возврат")
    nonce = payload.nonce.strip()
    if not NONCE_RE.match(nonce):
        raise HTTPException(400, "Код запуска указан неверно: скопируйте его с рабочего сервера")
    providers = list(dict.fromkeys(p for p in payload.providers if p in PROVIDERS))
    if not providers or len(providers) != len(payload.providers):
        raise HTTPException(400, "Неизвестная платёжная система")
    missing = [p for p in providers if not _provider_configured(p)]
    if missing:
        raise HTTPException(400, "На стенде не настроены ключи: " + ", ".join(missing))
    plan = await db.get(Plan, payload.plan_id)
    if not plan or not plan.enabled or Decimal(str(plan.price)) <= 0:
        raise HTTPException(400, "Нужен включённый тариф с положительной ценой")
    await _recover_stale(db)
    run = E2ERun(id=str(uuid.uuid4()), nonce=nonce, status="queued", active=True, providers=providers, plan_id=plan.id,
                 admin_id=admin.id, admin_email=admin.email, payment_timeout_seconds=payload.payment_timeout_seconds,
                 distribution_tag=DISTRIBUTION_TAG, created_at=_now(), heartbeat_at=_now())
    db.add(run)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Проверка уже выполняется")
    for provider in providers:
        db.add(E2ECase(run_id=run.id, provider=provider, checks=[], updated_at=_now()))
    from . import main
    await main.audit(db, "staging_e2e.v2.started", admin.email, run.id, {"providers": providers, "plan_id": plan.id})
    await db.commit()
    runner = Runner(lambda: AsyncSession(main.engine, expire_on_commit=False))
    _TASKS[run.id] = asyncio.create_task(runner.run(run.id))
    return {"id": run.id, "status": run.status}


@router.post("/api/admin/e2e-v2/runs/{run_id}/cancel")
async def cancel_run(run_id: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("staging_e2e.manage"))):
    run = await db.get(E2ERun, run_id)
    if not run or not run.active:
        raise HTTPException(404, "Активная проверка не найдена")
    run.status = "cancelled"
    from . import main
    await main.audit(db, "staging_e2e.v2.cancelled", admin.email, run.id)
    await db.commit()
    task = _TASKS.get(run_id)
    if not task or task.done():
        await Runner(lambda: AsyncSession(main.engine, expire_on_commit=False)).finish(run_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin API — production side
# ---------------------------------------------------------------------------

class AdmissionConfigIn(BaseModel):
    public_key: str = Field(min_length=40, max_length=64)
    providers: list[str] = Field(min_length=1, max_length=3)
    staging_url: str = Field(default="", max_length=2048)


class AttestationIn(BaseModel):
    attestation: str = Field(min_length=20, max_length=20000)


async def admission_config(db: AsyncSession) -> dict | None:
    from . import main
    try:
        cfg = json.loads(await main.setting_value(db, ADMISSION_CONFIG_KEY, "") or "null")
    except ValueError:
        return None
    return cfg if isinstance(cfg, dict) and cfg.get("revision") else None


async def admission_status(db: AsyncSession) -> dict:
    from . import main
    try:
        status = json.loads(await main.setting_value(db, ADMISSION_STATUS_KEY, "{}") or "{}")
    except ValueError:
        return {}
    return status if isinstance(status, dict) else {}


def _production_only():
    if staging_enabled():
        raise HTTPException(409, "Это стенд: допуск платежей настраивается на рабочем сервере")


@router.put("/api/admin/e2e-v2/admission/config")
async def save_admission_config(payload: AdmissionConfigIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("staging_e2e.manage"))):
    _production_only()
    from . import main
    await main._advisory_lock(db, 1300000013)
    try:
        parse_public_key(payload.public_key)
    except AttestationError as exc:
        raise HTTPException(400, str(exc))
    providers = list(dict.fromkeys(p for p in payload.providers if p in PROVIDERS))
    if not providers or len(providers) != len(payload.providers):
        raise HTTPException(400, "Неизвестная платёжная система")
    if payload.staging_url:
        main.validate_public_url(payload.staging_url, allow_empty=False)
    cfg = {"public_key": payload.public_key.strip(), "providers": providers, "staging_url": payload.staging_url.strip(),
           "revision": secrets.token_hex(16)}
    await main.set_setting(db, ADMISSION_CONFIG_KEY, json.dumps(cfg))
    await main.set_setting(db, ADMISSION_STATUS_KEY, json.dumps({"status": "never", "full_e2e": False, "config_revision": cfg["revision"]}))
    await main.set_setting(db, main.PRODUCTION_PAYMENTS_GATE_KEY, "0")
    await main.audit(db, "staging_e2e.v2.config.updated", admin.email, None, {"providers": providers, "staging_url": cfg["staging_url"]})
    await db.commit()
    return {"ok": True, "revision": cfg["revision"]}


@router.post("/api/admin/e2e-v2/admission/nonce")
async def issue_nonce(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("staging_e2e.manage"))):
    _production_only()
    from . import main
    await main._advisory_lock(db, 1300000013)
    cfg = await admission_config(db)
    if not cfg:
        raise HTTPException(400, "Сначала сохраните ключ стенда и платёжные системы")
    nonce = f"{NONCE_PREFIX}{cfg['revision'][:12]}.{secrets.token_hex(12)}"
    status = {"status": "awaiting_attestation", "full_e2e": False, "config_revision": cfg["revision"], "nonce": nonce,
              "issued_at": _iso(_now()), "providers": cfg["providers"]}
    await main.set_setting(db, ADMISSION_STATUS_KEY, json.dumps(status))
    await main.set_setting(db, main.PRODUCTION_PAYMENTS_GATE_KEY, "0")
    await main.audit(db, "staging_e2e.v2.nonce.issued", admin.email, None, {"revision": cfg["revision"]})
    await db.commit()
    return {"nonce": nonce}


@router.post("/api/admin/e2e-v2/admission/attestation")
async def accept_attestation(payload: AttestationIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("staging_e2e.manage"))):
    _production_only()
    from . import main
    await main._advisory_lock(db, 1300000013)
    cfg = await admission_config(db)
    status = await admission_status(db)
    if not cfg or status.get("status") != "awaiting_attestation" or status.get("config_revision") != cfg["revision"]:
        raise HTTPException(409, "Нет действующего кода запуска: получите новый код")
    try:
        attested = verify_attestation(payload.attestation, cfg["public_key"], nonce=status["nonce"],
                                      issued_at=datetime.fromisoformat(status["issued_at"]), now=datetime.now(timezone.utc),
                                      providers=cfg["providers"])
    except AttestationError as exc:
        await main.audit(db, "staging_e2e.v2.attestation.rejected", admin.email, None, {"reason": str(exc)})
        await db.commit()
        raise HTTPException(409, str(exc))
    result = {"status": "passed", "full_e2e": True, "contract_version": CONTRACT_VERSION, "config_revision": cfg["revision"],
              "run_id": attested["run_id"], "finished_at": attested["finished_at"], "distribution_tag": attested["distribution_tag"],
              "provider_results": attested["provider_results"], "accepted_at": _iso(_now()), "accepted_by": admin.email}
    await main.set_setting(db, ADMISSION_STATUS_KEY, json.dumps(result, ensure_ascii=False))
    await main.audit(db, "staging_e2e.v2.attestation.accepted", admin.email, attested["run_id"], {"finished_at": attested["finished_at"]})
    await db.commit()
    return result
