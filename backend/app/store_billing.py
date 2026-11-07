"""v28.89.0 (BACKLOG A5): subscriptions bought in Google Play and App Store.

Off until the owner turns on «Покупки в магазинах приложений» (``mobile_store_purchases_enabled``).

- The app sends its purchase to ``POST /api/payments/mobile/verify`` (payment_platform_api): the shop asks Google
  (Android Publisher API) or Apple (App Store Server API) itself, maps the product to a plan and grants it through
  :func:`grant` — the same locked confirmation and fulfilment as every other payment.
- Renewals, refunds and revocations come from the stores' notifications:
  ``POST /api/webhooks/app-store`` (App Store Server Notifications V2; every JWS is checked up to Apple Root CA G3)
  and ``POST /api/webhooks/google-play?token=…`` (Real-time developer notifications through a Pub/Sub push
  subscription; the token is a secret of the shop, the state is always re-read from Google's API).
- A refund or revocation takes the access back like a refund from the admin panel: inside the customer and payment
  locks, and the referral reward is reversed only after the access is gone.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from decimal import Decimal

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db

router = APIRouter()

# Apple Root CA - G3, SHA-256 of the certificate (support.apple.com/105116, checked 2026-11-07).
APPLE_ROOT_G3_SHA256 = "63343abfb89a6a03ebb57e9b3f5fa7be7c4f5c756f3017b3a8c488c3653e9179"
APPLE_LEAF_OID = x509.ObjectIdentifier("1.2.840.113635.100.6.11.1")          # Apple's StoreKit signing certificate
APPLE_INTERMEDIATE_OID = x509.ObjectIdentifier("1.2.840.113635.100.6.2.1")   # Apple Worldwide Developer Relations
PROVIDERS = ("google_play", "apple_iap")
GOOGLE_RENEW = {1, 2, 4, 7}       # RECOVERED, RENEWED, PURCHASED, RESTARTED
GOOGLE_REVOKED = 12
GOOGLE_ENDED = {3, 5, 6, 10, 13}  # CANCELED, ON_HOLD, IN_GRACE_PERIOD, PAUSED, EXPIRED: the paid time stays
APPLE_RENEW = {"SUBSCRIBED", "DID_RENEW"}
APPLE_TAKE_BACK = {"REFUND", "REVOKE"}
APPLE_ENDED = {"EXPIRED", "DID_FAIL_TO_RENEW", "GRACE_PERIOD_EXPIRED"}


class StoreError(Exception):
    pass


def enabled() -> bool:
    return bool(settings.mobile_store_purchases_enabled)


def require_enabled():
    if not enabled():
        raise HTTPException(410, "Покупки через магазины приложений выключены. Владелец включает их в «Настройках без перезапуска» → «Покупки в магазинах приложений».")


def google_chain(purchase_token: str) -> str:
    return hashlib.sha256(purchase_token.encode()).hexdigest()


def verify_apple_jws(token: str, *, now: datetime | None = None) -> dict:
    """The payload of a JWS signed by Apple: ES256 with the leaf key of the x5c chain leaf → WWDR → Apple Root CA G3."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise StoreError(f"Apple JWS is malformed: {exc}") from exc
    if header.get("alg") != "ES256":
        raise StoreError("Apple JWS must be ES256")
    try:
        chain = [x509.load_der_x509_certificate(base64.b64decode(item)) for item in header.get("x5c") or []]
    except (ValueError, TypeError) as exc:
        raise StoreError("Apple JWS certificate chain is unreadable") from exc
    if len(chain) != 3:
        raise StoreError("Apple JWS needs a chain of three certificates")
    leaf, intermediate, root = chain
    if root.fingerprint(hashes.SHA256()).hex() != APPLE_ROOT_G3_SHA256:
        raise StoreError("Apple JWS is not rooted in Apple Root CA G3")
    moment = now or datetime.now(timezone.utc)
    for cert in chain:
        if not cert.not_valid_before_utc <= moment <= cert.not_valid_after_utc:
            raise StoreError("Apple JWS certificate is outside its validity")
    try:
        leaf.verify_directly_issued_by(intermediate)
        intermediate.verify_directly_issued_by(root)
        leaf.extensions.get_extension_for_oid(APPLE_LEAF_OID)
        intermediate.extensions.get_extension_for_oid(APPLE_INTERMEDIATE_OID)
    except (ValueError, TypeError, x509.ExtensionNotFound, Exception) as exc:  # InvalidSignature is not a ValueError
        raise StoreError("Apple JWS certificate chain is not Apple's") from exc
    try:
        return jwt.decode(token, leaf.public_key(), algorithms=["ES256"], options={"verify_aud": False, "verify_exp": False})
    except jwt.PyJWTError as exc:
        raise StoreError(f"Apple JWS signature is invalid: {exc}") from exc


def _ms(value) -> datetime | None:
    try:
        return datetime.utcfromtimestamp(int(value) / 1000)
    except (TypeError, ValueError):
        return None


def _iso(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


async def grant(db: AsyncSession, *, provider: str, user_id: int, plan, external_id: str, chain_key: str, product_id: str,
                expires_at: datetime | None, subscription_id: int | None) -> dict:
    """One store transaction → one paid shop payment, fulfilled through the shared locked path. Repeats are answered
    with the payment that already exists."""
    from . import main as shop
    from .models import Payment, StoreSubscription
    if not external_id:
        raise HTTPException(402, "Магазин не вернул номер транзакции")
    existing = (await db.execute(select(Payment).where(Payment.provider == provider, Payment.provider_payment_id == external_id))).scalar_one_or_none()
    if existing:
        if existing.user_id != user_id:
            raise HTTPException(409, "Эта покупка принадлежит другому аккаунту")
        return {"ok": True, "payment_id": existing.id, "status": existing.status, "repeat": True}
    link = (await db.execute(select(StoreSubscription).where(StoreSubscription.provider == provider, StoreSubscription.chain_key == chain_key))).scalar_one_or_none()
    if link and link.user_id != user_id:
        raise HTTPException(409, "Эта подписка магазина принадлежит другому аккаунту")
    renewal = link is not None
    if not link:
        link = StoreSubscription(provider=provider, chain_key=chain_key, user_id=user_id, subscription_id=subscription_id, plan_id=plan.id, product_id=product_id)
        db.add(link)
    link.plan_id, link.product_id, link.status, link.last_order_id, link.expires_at = plan.id, product_id, "active", external_id, expires_at
    if subscription_id is not None:
        link.subscription_id = subscription_id
    order = f"{provider}-{external_id}"[:255]
    price = Decimal(str(plan.price))
    payment = Payment(user_id=user_id, subscription_id=link.subscription_id, plan_id=plan.id, provider=provider, provider_payment_id=external_id,
                      order_id=order, amount=price, original_amount=price, discount_amount=0, duration_days_snapshot=plan.duration_days,
                      traffic_limit_gb_snapshot=plan.traffic_limit_gb, device_limit_snapshot=plan.device_limit,
                      remnawave_profile_id_snapshot=plan.remnawave_profile_id, currency=settings.default_currency, status="paid",
                      fulfillment_status="pending", idempotency_key=hashlib.sha256(order.encode()).hexdigest(), purpose="subscription",
                      paid_at=datetime.utcnow())
    db.add(payment)
    await db.flush()
    await shop._issue_invoice(db, payment)
    await shop.audit(db, "payment.store.granted", f"{provider}", str(payment.id), {"product_id": product_id, "plan_id": plan.id, "renewal": renewal})
    await db.commit()
    result = await shop._confirm_and_fulfill_payment(payment.id, db)
    return {"ok": True, "payment_id": payment.id, "provider": provider, "expires_at": expires_at.isoformat() if expires_at else None,
            "fulfilled": not (result or {}).get("ignored", False)}


async def take_back(db: AsyncSession, payment, reason: str) -> dict:
    """A refund or revocation by the store: the payment becomes refunded and the access is taken back, inside the same
    locks as fulfilment; the referral reward is reversed only once the access is gone."""
    from . import main as shop
    from .models import Payment, RefundRequest, StoreSubscription
    actor = payment.provider
    user_lock, user_token = await shop._acquire_user_fulfillment_lock(payment.user_id, ttl=300)
    payment_lock = payment_token = None
    try:
        payment_lock, payment_token = await shop._acquire_payment_side_effect_lock(payment.id)
        p = (await db.execute(select(Payment).where(Payment.id == payment.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
        if p.status in {"refunded", "refunded_pending_revoke"}:
            return {"ok": True, "status": p.status, "repeat": True}
        r = RefundRequest(payment_id=p.id, user_id=p.user_id, amount=Decimal(str(p.amount)), status="refunded",
                          provider_refund_id=f"{p.provider}-store-{p.id}", reason=reason[:500])
        db.add(r)
        p.status, p.fulfillment_terminal = "refunded", True
        await db.flush()
        await shop.record_financial_event(db, operation_key=f"payment:{p.id}:refund:{r.id}", user_id=p.user_id, payment_id=p.id, kind="refund",
                                          direction="debit", amount=Decimal(str(p.amount)), currency=p.currency,
                                          metadata={"provider": p.provider, "refund_id": r.id, "store": reason[:120]})
        try:
            revoke = await shop._safe_revoke_for_refunded_payment(db, p, actor, "subscription.revoked.store_refund")
        except Exception as exc:
            r.status = "refunded_pending_revoke"
            r.reason = (r.reason or "") + "\nRevoke pending: " + str(exc)[:500]
            revoke = {"revoked": False, "reason": "revoke_failed"}
        reversal = await shop._reverse_referral_reward_for_refund(db, p, actor) if r.status == "refunded" else {"reversed": False}
        link = (await db.execute(select(StoreSubscription).where(StoreSubscription.provider == p.provider, StoreSubscription.last_order_id == p.provider_payment_id))).scalar_one_or_none()
        if link:
            link.status = "refunded"
        await shop.audit(db, "payment.store.refunded", actor, str(p.id), {"reason": reason[:200], **revoke, **reversal})
        await db.commit()
        return {"ok": True, "status": r.status, **revoke}
    finally:
        if payment_lock and payment_token:
            await shop._release_payment_side_effect_lock(payment_lock, payment_token)
        await shop._release_payment_side_effect_lock(user_lock, user_token)


async def _link(db, provider: str, chain_key: str):
    from .models import StoreSubscription
    return (await db.execute(select(StoreSubscription).where(StoreSubscription.provider == provider, StoreSubscription.chain_key == chain_key))).scalar_one_or_none()


async def _plan_for(db, product_id: str):
    from . import main as shop
    from .payment_platform import PlatformProviderError, store_product_plan_id
    try:
        plan = await db.get(shop.Plan, store_product_plan_id(product_id))
    except PlatformProviderError as exc:
        raise StoreError(str(exc)) from exc
    if not plan:
        raise StoreError("The store product points at a missing plan")
    return plan


@router.post("/api/webhooks/app-store")
async def app_store_notification(request: Request, db: AsyncSession = Depends(get_db)):
    """App Store Server Notifications V2. Answers 200 once handled (or nothing to do); Apple retries anything else."""
    from .models import Payment
    require_enabled()
    try:
        body = await request.json()
        note = verify_apple_jws(str(body.get("signedPayload") or ""))
        data = note.get("data") or {}
        if not settings.apple_bundle_id or data.get("bundleId") != settings.apple_bundle_id:
            raise StoreError("Notification is for another app")
        tx = verify_apple_jws(data["signedTransactionInfo"]) if data.get("signedTransactionInfo") else {}
    except (StoreError, ValueError, KeyError, AttributeError) as exc:
        raise HTTPException(403, f"App Store notification refused: {exc}") from exc
    kind = str(note.get("notificationType") or "")
    original, transaction = str(tx.get("originalTransactionId") or ""), str(tx.get("transactionId") or "")
    if kind in APPLE_TAKE_BACK:
        payment = (await db.execute(select(Payment).where(Payment.provider == "apple_iap", Payment.provider_payment_id == transaction))).scalar_one_or_none()
        if not payment:
            return {"ok": True, "ignored": "unknown transaction"}
        return await take_back(db, payment, f"App Store {kind}")
    link = await _link(db, "apple_iap", original) if original else None
    if kind in APPLE_RENEW:
        if not link:
            return {"ok": True, "ignored": "the first purchase arrives from the app"}
        try:
            plan = await _plan_for(db, str(tx.get("productId") or ""))
        except StoreError as exc:
            raise HTTPException(409, str(exc)) from exc
        return await grant(db, provider="apple_iap", user_id=link.user_id, plan=plan, external_id=transaction, chain_key=original,
                           product_id=str(tx.get("productId") or ""), expires_at=_ms(tx.get("expiresDate")), subscription_id=link.subscription_id)
    if kind in APPLE_ENDED and link:
        link.status = "ended"
        await db.commit()
    return {"ok": True, "ignored": kind or "empty"}


@router.post("/api/webhooks/google-play")
async def google_play_notification(request: Request, db: AsyncSession = Depends(get_db)):
    """Real-time developer notifications through a Pub/Sub push subscription to ``…/google-play?token=<secret>``."""
    from . import main as shop
    from .models import Payment
    require_enabled()
    secret = settings.google_play_rtdn_token or ""
    if not secret:
        raise HTTPException(503, "Токен уведомлений Google Play не задан")
    if not hmac.compare_digest(str(request.query_params.get("token") or ""), secret):
        raise HTTPException(403, "Wrong token")
    try:
        body = await request.json()
        note = json.loads(base64.b64decode(body["message"]["data"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, "Not a Pub/Sub message") from exc
    if note.get("packageName") != settings.google_play_package:
        return {"ok": True, "ignored": "another package"}
    if note.get("testNotification"):
        return {"ok": True, "test": True}
    voided = note.get("voidedPurchaseNotification")
    if voided:
        payment = (await db.execute(select(Payment).where(Payment.provider == "google_play", Payment.provider_payment_id == str(voided.get("orderId") or "")))).scalar_one_or_none()
        if not payment:
            return {"ok": True, "ignored": "unknown order"}
        return await take_back(db, payment, "Google Play voided purchase")
    sub = note.get("subscriptionNotification") or {}
    token = str(sub.get("purchaseToken") or "")
    kind = int(sub.get("notificationType") or 0)
    link = await _link(db, "google_play", google_chain(token)) if token else None
    if not link:
        return {"ok": True, "ignored": "the first purchase arrives from the app"}
    if kind == GOOGLE_REVOKED:
        payment = (await db.execute(select(Payment).where(Payment.provider == "google_play", Payment.provider_payment_id == link.last_order_id))).scalar_one_or_none()
        return await take_back(db, payment, "Google Play revoked") if payment else {"ok": True, "ignored": "no payment"}
    if kind in GOOGLE_RENEW:
        try:
            data = await shop.GooglePlayPlatform().verify_subscription(token)
            plan = await _plan_for(db, str(data.get("productId") or ""))
        except (shop.PlatformProviderError, StoreError) as exc:
            raise HTTPException(409, str(exc)) from exc
        expiry = _iso(((data.get("lineItems") or [{}])[0]).get("expiryTime"))
        return await grant(db, provider="google_play", user_id=link.user_id, plan=plan, external_id=str(data.get("latestOrderId") or ""),
                           chain_key=link.chain_key, product_id=str(data.get("productId") or ""), expires_at=expiry, subscription_id=link.subscription_id)
    if kind in GOOGLE_ENDED:
        link.status = "ended" if kind in {3, 13} else "paused"
        await db.commit()
    return {"ok": True, "ignored": kind}
