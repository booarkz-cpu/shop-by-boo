"""Receipts to the Russian tax service for paid orders («Тарифы и оплата → Чеки в налоговую»).

Three ways, chosen in the admin panel:

* ``npd`` — самозанятый (налог на профессиональный доход): a receipt in «Мой налог»
  (lknpd.nalog.ru) for every payment, cancelled with «Возврат средств» on a refund.
  «Мой налог» has no public partner API for small sellers: the shop signs in with the INN and the
  password of the taxpayer's account, as the official web cabinet does.
* ``atol`` — ИП/ООО with an online cash register: a 54-ФЗ receipt (ФФД 1.2) through АТОЛ Онлайн
  v5, «возврат прихода» on a refund.
* ``yookassa`` — ИП/ООО with «Чеки от ЮKassa»: a separate payment receipt (POST /v3/receipts)
  after the payment, a refund receipt for a refund.

Receipts are created by the worker (fiscal_scheduler) for payments paid after the moment the
mode was switched on, so switching it on never sends old orders. Each payment gets at most one
income and one refund receipt; a failed send is retried with backoff and can be retried by hand.
Secrets (password, API keys) are stored encrypted and never returned to the browser.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import AppSetting, FiscalReceipt, Payment, Plan, RefundRequest, User
from .security import decrypt_secret, encrypt_secret, require_permission

logger = logging.getLogger(__name__)
router = APIRouter()
SETTING_KEY = "fiscal_config"
MSK = timezone(timedelta(hours=3))
NPD_API = "https://lknpd.nalog.ru/api/v1"
ATOL_API = "https://online.atol.ru/possystem/v5"
MODES = {"off": "Выключено", "npd": "Самозанятый — «Мой налог»", "atol": "ИП/ООО — АТОЛ Онлайн (54-ФЗ)",
         "yookassa": "ИП/ООО — чеки ЮKassa (54-ФЗ)"}
TAXATION = {"osn": "ОСН", "usn_income": "УСН «доходы»", "usn_income_outcome": "УСН «доходы минус расходы»",
            "esn": "ЕСХН", "patent": "Патент"}
# ATOL vat type → YooKassa vat_code. 2026: НДС 22% (22/122), УСН-ставки 5% и 7%.
VAT = {"none": ("Без НДС", 1), "vat0": ("НДС 0%", 2), "vat5": ("НДС 5%", 7), "vat7": ("НДС 7%", 8),
       "vat10": ("НДС 10%", 3), "vat22": ("НДС 22%", 11), "vat105": ("НДС 5/105", 9), "vat107": ("НДС 7/107", 10),
       "vat110": ("НДС 10/110", 5), "vat122": ("НДС 22/122", 12)}
YOOKASSA_TAX = {"osn": 1, "usn_income": 2, "usn_income_outcome": 3, "esn": 5, "patent": 6}
DEFAULT_PROVIDERS = ["yookassa", "platega", "rollypay"]
SECRETS = ("npd_password", "atol_password", "yookassa_secret_key")
MAX_ATTEMPTS = 12

__all__ = ["router", "MODES", "VAT", "TAXATION", "FiscalConfig", "load_config", "service_name", "enqueue_due",
           "send_receipt", "process_due", "fiscal_scheduler", "npd_income_payload", "atol_sell_payload",
           "yookassa_receipt_payload"]


class FiscalConfig(BaseModel):
    mode: str = Field(default="off", pattern=r"^(off|npd|atol|yookassa)$")
    enabled_at: datetime | None = None
    service_name: str = Field(default="Подписка VPN «{plan}» на {days} дн.", min_length=3, max_length=128)
    topup_name: str = Field(default="Пополнение баланса сервиса VPN", min_length=3, max_length=128)
    providers: list[str] = Field(default_factory=lambda: list(DEFAULT_PROVIDERS), max_length=12)
    refunds: bool = True
    # 54-ФЗ
    inn: str = Field(default="", pattern=r"^(|\d{10}|\d{12})$")
    taxation: str = Field(default="usn_income", pattern=r"^(osn|usn_income|usn_income_outcome|esn|patent)$")
    vat: str = Field(default="none", pattern=r"^(none|vat0|vat5|vat7|vat10|vat22|vat105|vat107|vat110|vat122)$")
    company_email: str = Field(default="", max_length=254)
    payment_address: str = Field(default="", max_length=256)
    fallback_email: str = Field(default="", max_length=254)
    # «Мой налог»
    npd_inn: str = Field(default="", pattern=r"^(|\d{12})$")
    npd_password: str = ""
    npd_device_id: str = ""
    # АТОЛ Онлайн
    atol_login: str = Field(default="", max_length=128)
    atol_password: str = ""
    atol_group: str = Field(default="", max_length=128)
    atol_api: str = Field(default=ATOL_API, max_length=256)
    # ЮKassa (empty: the shop's YOOKASSA_SHOP_ID / YOOKASSA_SECRET_KEY)
    yookassa_shop_id: str = Field(default="", max_length=64)
    yookassa_secret_key: str = ""

    @field_validator("providers")
    @classmethod
    def _providers(cls, value):
        clean = []
        for item in value:
            item = str(item).strip().lower()
            if item in {"wallet"}:
                continue  # paying from the balance is not new money: the top-up had its receipt
            if item and item.replace("_", "").isalnum() and item not in clean:
                clean.append(item)
        return clean

    @field_validator("atol_api", "payment_address")
    @classmethod
    def _https(cls, value):
        value = value.strip().rstrip("/") if value else value
        if value and not value.startswith("https://"):
            raise ValueError("Только адрес https://")
        return value

    @field_validator("company_email", "fallback_email")
    @classmethod
    def _email(cls, value):
        value = value.strip()
        if value and ("@" not in value or " " in value):
            raise ValueError("Укажите e-mail")
        return value


class FiscalIn(FiscalConfig):
    """Admin form: empty secret fields keep the stored value, clear_secrets removes them."""
    clear_secrets: list[str] = Field(default_factory=list)


async def load_config(db: AsyncSession) -> FiscalConfig:
    row = await db.get(AppSetting, SETTING_KEY)
    if not row or not row.value:
        return FiscalConfig()
    try:
        return FiscalConfig.model_validate(json.loads(row.value))
    except Exception:
        logger.warning("fiscal config unreadable; receipts are off until it is saved again")
        return FiscalConfig()


def _secret(config: FiscalConfig, name: str) -> str:
    value = getattr(config, name)
    if not value:
        return ""
    try:
        return decrypt_secret(value)
    except Exception:
        return ""


def public_config(config: FiscalConfig) -> dict:
    data = config.model_dump(mode="json")
    for name in SECRETS:
        data[name] = ""
        data[name + "_set"] = bool(getattr(config, name))
    return data


def service_name(config: FiscalConfig, payment: Payment, plan: Plan | None) -> str:
    if payment.purpose == "topup":
        return config.topup_name[:128]
    days = payment.duration_days_snapshot or (plan.duration_days if plan else 30)
    name = (plan.name if plan else "VPN")
    try:
        text = config.service_name.format(plan=name, days=days)
    except (KeyError, IndexError, ValueError):
        text = config.service_name
    return " ".join(text.split())[:128]


def _ts(value: datetime | None) -> datetime:
    value = value or datetime.utcnow()
    return value.replace(tzinfo=timezone.utc).astimezone(MSK)


def npd_income_payload(name: str, amount: Decimal, paid_at: datetime | None, now: datetime | None = None) -> dict:
    total = f"{Decimal(amount):.2f}"
    return {"operationTime": _ts(paid_at).isoformat(timespec="seconds"), "requestTime": _ts(now).isoformat(timespec="seconds"),
            "services": [{"name": name, "amount": total, "quantity": 1}], "totalAmount": total,
            "client": {"contactPhone": None, "displayName": None, "incomeType": "FROM_INDIVIDUAL", "inn": None},
            "paymentType": "ACCOUNT", "ignoreMaxTotalIncomeRestriction": False}


def atol_sell_payload(config: FiscalConfig, external_id: str, name: str, amount: Decimal, email: str, now: datetime | None = None) -> dict:
    total = float(Decimal(amount).quantize(Decimal("0.01")))
    return {"external_id": external_id, "timestamp": _ts(now).strftime("%d.%m.%Y %H:%M:%S"),
            "receipt": {"client": {"email": email},
                        "company": {"email": config.company_email, "sno": config.taxation, "inn": config.inn,
                                    "payment_address": config.payment_address},
                        "items": [{"name": name, "price": total, "quantity": 1.0, "sum": total, "measure": 0,
                                   "payment_method": "full_payment", "payment_object": 4, "vat": {"type": config.vat}}],
                        "payments": [{"type": 1, "sum": total}], "total": total}}


def yookassa_receipt_payload(config: FiscalConfig, kind: str, payment: Payment, name: str, email: str, refund_id: str = "") -> dict:
    value = {"value": f"{Decimal(payment.amount):.2f}", "currency": payment.currency or "RUB"}
    body = {"customer": {"email": email}, "type": kind, "send": True, "tax_system_code": YOOKASSA_TAX[config.taxation],
            "items": [{"description": name, "quantity": "1.00", "amount": value, "vat_code": VAT[config.vat][1],
                       "payment_mode": "full_payment", "payment_subject": "service"}],
            "settlements": [{"type": "cashless", "amount": value}]}
    if kind == "refund":
        body["refund_id"] = refund_id
    else:
        body["payment_id"] = payment.provider_payment_id
    return body


# ------------------------------------------------------------------ providers

class FiscalError(RuntimeError):
    def __init__(self, message: str, final: bool = False):
        super().__init__(message)
        self.final = final


def _client():
    import httpx
    from .main import _pinned_public_http_client

    try:
        return _pinned_public_http_client(20)
    except Exception:
        return httpx.AsyncClient(timeout=20, trust_env=False)


_NPD_TOKENS: dict[str, tuple[str, datetime]] = {}


def _device(config: FiscalConfig) -> dict:
    return {"sourceType": "WEB", "sourceDeviceId": config.npd_device_id or "corgi-lusi-shop", "appVersion": "1.0.0",
            "metaDetails": {"userAgent": "Mozilla/5.0 CorgiLusiShop"}}


async def _npd_token(client, config: FiscalConfig) -> str:
    cached = _NPD_TOKENS.get(config.npd_inn)
    if cached and cached[1] > datetime.utcnow():
        return cached[0]
    password = _secret(config, "npd_password")
    if not config.npd_inn or not password:
        raise FiscalError("Не указаны ИНН и пароль «Мой налог»", final=True)
    r = await client.post(f"{NPD_API}/auth/lkfl", json={"username": config.npd_inn, "password": password, "deviceInfo": _device(config)},
                          headers={"Referrer": "https://lknpd.nalog.ru/auth/login"})
    if r.status_code in (401, 403, 422):
        raise FiscalError("«Мой налог» не принял ИНН или пароль", final=True)
    if r.status_code >= 400:
        raise FiscalError(f"«Мой налог»: HTTP {r.status_code}")
    token = r.json().get("token")
    if not token:
        raise FiscalError("«Мой налог» не вернул токен")
    _NPD_TOKENS[config.npd_inn] = (token, datetime.utcnow() + timedelta(minutes=50))
    return token


async def _atol_token(client, config: FiscalConfig) -> str:
    password = _secret(config, "atol_password")
    if not config.atol_login or not password or not config.atol_group:
        raise FiscalError("Не указаны логин, пароль и группа АТОЛ Онлайн", final=True)
    r = await client.post(f"{config.atol_api}/getToken", json={"login": config.atol_login, "pass": password})
    data = r.json() if r.content else {}
    if r.status_code >= 400 or not data.get("token"):
        raise FiscalError(f"АТОЛ Онлайн не выдал токен: {((data.get('error') or {}).get('text') or r.status_code)}", final=r.status_code in (400, 401, 403))
    return data["token"]


def _yookassa_auth(config: FiscalConfig):
    from .config import settings

    shop_id = config.yookassa_shop_id or settings.yookassa_shop_id
    secret = _secret(config, "yookassa_secret_key") or settings.yookassa_secret_key
    if not shop_id or not secret:
        raise FiscalError("Не указаны shopId и секретный ключ ЮKassa", final=True)
    return shop_id, secret


async def check_connection(config: FiscalConfig) -> dict:
    async with _client() as client:
        if config.mode == "npd":
            _NPD_TOKENS.pop(config.npd_inn, None)
            await _npd_token(client, config)
            return {"ok": True, "message": "«Мой налог»: вход выполнен"}
        if config.mode == "atol":
            await _atol_token(client, config)
            return {"ok": True, "message": "АТОЛ Онлайн: токен получен"}
        if config.mode == "yookassa":
            from .config import settings
            r = await client.get(f"{settings.yookassa_api_url}/v3/me", auth=_yookassa_auth(config))
            if r.status_code >= 400:
                raise FiscalError(f"ЮKassa: HTTP {r.status_code}")
            fiscal = (r.json() or {}).get("fiscalization_enabled")
            return {"ok": True, "message": "ЮKassa: магазин доступен" + ("" if fiscal is not False else "; включите «Чеки от ЮKassa» в личном кабинете")}
    return {"ok": False, "message": "Чеки выключены"}


async def _email(db: AsyncSession, config: FiscalConfig, payment: Payment) -> str:
    user = await db.get(User, payment.user_id)
    return (user.email if user and user.email and user.email_verified_at else "") or config.fallback_email or config.company_email


class _NpdAnswerLost(Exception):
    """The income request left but no answer came back: it may already be registered."""


async def _npd_income_once(client, auth: dict, body: dict):
    """«Мой налог» has no idempotency key. Only a refused connection is retried blindly; an answer
    lost after the request left turns the receipt to «check», and the next pass looks the income
    up in the list of incomes before sending anything again."""
    import httpx

    try:
        return await client.post(f"{NPD_API}/income", headers=auth, json=body)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        raise
    except httpx.TransportError as exc:
        raise _NpdAnswerLost() from exc


def _npd_time(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def _same_second(value, moment: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MSK)
    return abs((parsed - moment).total_seconds()) < 1


async def npd_find_income(client, auth: dict, name: str, amount: Decimal, operation_time: datetime,
                          taken: set[str] = frozenset()) -> str | None:
    """UUID of a registered (not cancelled) income with this name, amount and sale second that no
    other receipt of the shop already owns. Raises FiscalError when the list cannot be read."""
    moment = _ts(operation_time).replace(microsecond=0)
    total = Decimal(amount).quantize(Decimal("0.01"))
    for offset in range(0, 500, 100):
        r = await client.get(f"{NPD_API}/incomes", headers=auth, params={
            "from": _npd_time(moment - timedelta(minutes=1)), "to": _npd_time(moment + timedelta(minutes=1)),
            "offset": offset, "limit": 100, "sortBy": "operation_time:desc"})
        if r.status_code >= 400:
            raise FiscalError(f"«Мой налог»: список доходов недоступен (HTTP {r.status_code})")
        data = r.json() or {}
        for item in data.get("content") or []:
            try:
                same_amount = Decimal(str(item.get("totalAmount"))).quantize(Decimal("0.01")) == total
            except (ArithmeticError, ValueError):
                continue
            uuid_ = item.get("approvedReceiptUuid")
            if (same_amount and uuid_ and uuid_ not in taken and item.get("name") == name and not item.get("cancellationInfo")
                    and _same_second(item.get("operationTime"), moment)):
                return uuid_
        if not data.get("hasMore"):
            return None
    return None


async def send_receipt(db: AsyncSession, receipt: FiscalReceipt, config: FiscalConfig, now: datetime | None = None) -> FiscalReceipt:
    """Send (or poll) one receipt and record the outcome."""
    now = now or datetime.utcnow()
    payment = await db.get(Payment, receipt.payment_id)
    plan = await db.get(Plan, payment.plan_id) if payment and payment.plan_id else None
    receipt.attempts += 1
    receipt.updated_at = now
    was_checking = receipt.status == "check"
    try:
        if not payment:
            raise FiscalError("Платёж не найден", final=True)
        name = receipt.name or service_name(config, payment, plan)
        receipt.name = name
        async with _client() as client:
            if receipt.provider == "npd":
                token = await _npd_token(client, config)
                auth = {"Authorization": f"Bearer {token}"}
                if receipt.kind == "income":
                    sold_at = payment.paid_at or payment.created_at
                    if was_checking or receipt.attempts > 1 or receipt.last_error:
                        # Any earlier attempt may have reached the tax service: look before sending.
                        taken = set((await db.execute(select(FiscalReceipt.external_id).where(
                            FiscalReceipt.provider == "npd", FiscalReceipt.kind == "income", FiscalReceipt.id != receipt.id,
                            FiscalReceipt.external_id.is_not(None)))).scalars().all())
                        found = await npd_find_income(client, auth, name, payment.amount, sold_at, taken)
                        if found:
                            receipt.external_id = found
                            receipt.receipt_url = f"{NPD_API}/receipt/{config.npd_inn}/{found}/print"
                            receipt.status = "done"
                            receipt.last_error = None
                            receipt.next_attempt_at = None
                            return receipt
                    try:
                        r = await _npd_income_once(client, auth, npd_income_payload(name, payment.amount, sold_at, now))
                    except _NpdAnswerLost:
                        receipt.status = "check"
                        receipt.last_error = "«Мой налог» не ответил после отправки: магазин проверит список доходов и отправит чек, только если его там нет"
                        receipt.next_attempt_at = now + timedelta(minutes=2)
                        return receipt
                    if r.status_code >= 400:
                        raise FiscalError(f"«Мой налог»: {(r.json() or {}).get('message') if r.content else r.status_code}", final=r.status_code == 422)
                    uuid_ = r.json().get("approvedReceiptUuid")
                    if not uuid_:
                        raise FiscalError("«Мой налог» не вернул номер чека")
                    receipt.external_id = uuid_
                    receipt.receipt_url = f"{NPD_API}/receipt/{config.npd_inn}/{uuid_}/print"
                else:
                    income = await _income_of(db, payment.id)
                    if not income or not income.external_id:
                        raise FiscalError("Нет чека прихода для аннулирования", final=True)
                    r = await client.post(f"{NPD_API}/cancel", headers=auth, json={
                        "operationTime": _ts(now).isoformat(timespec="seconds"), "requestTime": _ts(now).isoformat(timespec="seconds"),
                        "comment": "Возврат средств", "receiptUuid": income.external_id, "partnerCode": None})
                    if r.status_code >= 400:
                        raise FiscalError(f"«Мой налог»: HTTP {r.status_code}")
                    receipt.external_id = income.external_id
                    receipt.receipt_url = income.receipt_url
                receipt.status = "done"
            elif receipt.provider == "atol":
                token = await _atol_token(client, config)
                headers = {"Token": token}
                if receipt.external_id:  # sent earlier: read the report
                    r = await client.get(f"{config.atol_api}/{config.atol_group}/report/{receipt.external_id}", headers=headers)
                else:
                    operation = "sell" if receipt.kind == "income" else "sell_refund"
                    body = atol_sell_payload(config, f"corgi-{receipt.kind}-{payment.id}", name, payment.amount, await _email(db, config, payment), now)
                    r = await client.post(f"{config.atol_api}/{config.atol_group}/{operation}", headers=headers, json=body)
                data = r.json() if r.content else {}
                if data.get("uuid"):
                    receipt.external_id = data["uuid"]
                status = data.get("status")
                if status == "done":
                    payload = data.get("payload") or {}
                    receipt.status = "done"
                    receipt.receipt_url = payload.get("ofd_receipt_url") or ""
                    receipt.fiscal_data = {k: payload.get(k) for k in ("fiscal_receipt_number", "fiscal_document_number",
                                                                     "fiscal_document_attribute", "fn_number", "receipt_datetime") if payload.get(k) is not None}
                elif status == "fail" or r.status_code >= 400:
                    error = (data.get("error") or {}).get("text") or f"HTTP {r.status_code}"
                    if status == "fail":
                        receipt.external_id = None  # the next attempt sends it again
                    raise FiscalError(f"АТОЛ Онлайн: {error}", final=r.status_code in (400, 401))
                else:
                    receipt.status = "sent"  # wait: polled by the next pass
            elif receipt.provider == "yookassa":
                from .config import settings
                refund_id = ""
                if receipt.kind == "refund":
                    rr = (await db.execute(select(RefundRequest).where(RefundRequest.payment_id == payment.id))).scalar_one_or_none()
                    refund_id = (rr.provider_refund_id if rr else "") or ""
                    if not refund_id:
                        raise FiscalError("Нет идентификатора возврата ЮKassa", final=True)
                elif not payment.provider_payment_id:
                    raise FiscalError("Нет идентификатора платежа ЮKassa", final=True)
                body = yookassa_receipt_payload(config, "payment" if receipt.kind == "income" else "refund", payment, name,
                                                await _email(db, config, payment), refund_id)
                r = await client.post(f"{settings.yookassa_api_url}/v3/receipts", auth=_yookassa_auth(config), json=body,
                                      headers={"Idempotence-Key": f"corgi-receipt-{receipt.kind}-{payment.id}"})
                data = r.json() if r.content else {}
                if r.status_code >= 400:
                    raise FiscalError(f"ЮKassa: {data.get('description') or r.status_code}", final=r.status_code == 400)
                receipt.external_id = data.get("id")
                receipt.status = "done" if data.get("status") == "succeeded" else "sent"
            else:
                raise FiscalError("Способ отправки чеков не выбран", final=True)
        receipt.last_error = None
        receipt.next_attempt_at = now + timedelta(minutes=1) if receipt.status == "sent" else None
    except FiscalError as exc:
        receipt.last_error = str(exc)[:500]
        _fail(receipt, now, exc.final)
        if receipt.status == "retry" and was_checking:
            receipt.status = "check"  # still unknown whether the income exists: never send blindly
    except Exception as exc:  # network, JSON
        receipt.last_error = f"{type(exc).__name__}: {exc}"[:500]
        _fail(receipt, now, False)
        if receipt.status == "retry" and was_checking:
            receipt.status = "check"
    return receipt


def _fail(receipt: FiscalReceipt, now: datetime, final: bool):
    if final or receipt.attempts >= MAX_ATTEMPTS:
        receipt.status = "failed"
        receipt.next_attempt_at = None
    else:
        receipt.status = "retry"
        receipt.next_attempt_at = now + timedelta(minutes=min(240, 2 ** receipt.attempts))


async def _income_of(db: AsyncSession, payment_id: int) -> FiscalReceipt | None:
    return (await db.execute(select(FiscalReceipt).where(FiscalReceipt.payment_id == payment_id, FiscalReceipt.kind == "income"))).scalar_one_or_none()


PAID = ("paid", "fulfilled")
REFUNDED = ("refunded", "refunded_pending_revoke")


async def enqueue_due(db: AsyncSession, config: FiscalConfig, now: datetime | None = None, limit: int = 100) -> int:
    """Queue income receipts of new paid payments and refund receipts of refunded ones."""
    if config.mode == "off" or not config.enabled_at:
        return 0
    now = now or datetime.utcnow()
    since = config.enabled_at.replace(tzinfo=None)
    has_income = exists().where(FiscalReceipt.payment_id == Payment.id, FiscalReceipt.kind == "income")
    base = [Payment.provider.in_(config.providers or ["none"]), Payment.amount > 0, func.coalesce(Payment.paid_at, Payment.created_at) >= since]
    rows = (await db.execute(select(Payment).where(*base, Payment.status.in_(PAID + REFUNDED), ~has_income).order_by(Payment.id).limit(limit))).scalars().all()
    created = 0
    for p in rows:
        db.add(FiscalReceipt(payment_id=p.id, kind="income", provider=config.mode, status="queued", amount=p.amount, created_at=now, updated_at=now, next_attempt_at=now))
        created += 1
    if config.refunds:
        has_refund = exists().where(FiscalReceipt.payment_id == Payment.id, FiscalReceipt.kind == "refund")
        done_income = exists().where(FiscalReceipt.payment_id == Payment.id, FiscalReceipt.kind == "income", FiscalReceipt.status == "done")
        refunds = (await db.execute(select(Payment).where(*base, Payment.status.in_(REFUNDED), done_income, ~has_refund).order_by(Payment.id).limit(limit))).scalars().all()
        for p in refunds:
            income = await _income_of(db, p.id)
            db.add(FiscalReceipt(payment_id=p.id, kind="refund", provider=income.provider if income else config.mode, status="queued",
                                 amount=p.amount, created_at=now, updated_at=now, next_attempt_at=now))
            created += 1
    await db.commit()
    return created


async def process_due(db: AsyncSession, config: FiscalConfig, now: datetime | None = None, limit: int = 20) -> dict[str, int]:
    now = now or datetime.utcnow()
    due = (await db.execute(select(FiscalReceipt).where(FiscalReceipt.status.in_(("queued", "retry", "sent", "check")), FiscalReceipt.next_attempt_at <= now)
                            .order_by(FiscalReceipt.next_attempt_at, FiscalReceipt.id).limit(limit).with_for_update(skip_locked=True))).scalars().all()
    stats: dict[str, int] = {}
    for receipt in due:
        if receipt.kind == "refund":
            income = await _income_of(db, receipt.payment_id)
            if not income or income.status != "done":
                continue
        await send_receipt(db, receipt, config, now)
        stats[receipt.status] = stats.get(receipt.status, 0) + 1
    await db.commit()
    return stats


async def fiscal_scheduler():
    from .db import engine

    while True:
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                config = await load_config(db)
                if config.mode != "off":
                    await enqueue_due(db, config)
                    await process_due(db, config)
        except Exception as exc:
            logger.warning("Fiscal receipts unavailable; retrying: %s", type(exc).__name__)
        await asyncio.sleep(60)


# ------------------------------------------------------------------ API

def _row(r: FiscalReceipt) -> dict:
    return {"id": r.id, "payment_id": r.payment_id, "kind": r.kind, "provider": r.provider, "status": r.status, "amount": str(r.amount),
            "name": r.name, "external_id": r.external_id, "receipt_url": r.receipt_url, "attempts": r.attempts, "last_error": r.last_error,
            "fiscal_data": r.fiscal_data or {}, "created_at": r.created_at, "updated_at": r.updated_at}


@router.get("/api/admin/fiscal")
async def admin_fiscal(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("payments.read"))):
    config = await load_config(db)
    rows = (await db.execute(select(FiscalReceipt).order_by(FiscalReceipt.id.desc()).limit(100))).scalars().all()
    counts = dict((await db.execute(select(FiscalReceipt.status, func.count(FiscalReceipt.id)).group_by(FiscalReceipt.status))).all())
    return {"config": public_config(config), "modes": MODES, "taxation": TAXATION, "vat": {k: v[0] for k, v in VAT.items()},
            "counts": {k: int(v) for k, v in counts.items()}, "items": [_row(r) for r in rows]}


@router.put("/api/admin/fiscal")
async def admin_fiscal_save(payload: FiscalIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("payments.write"))):
    from .main import audit

    current = await load_config(db)
    data = payload.model_dump(exclude={"clear_secrets"})
    for name in SECRETS:
        if name in payload.clear_secrets:
            data[name] = ""
        elif data[name]:
            data[name] = encrypt_secret(data[name])
        else:
            data[name] = getattr(current, name)
    if payload.mode == "npd" and not data["npd_inn"]:
        raise HTTPException(422, "Укажите ИНН самозанятого (12 цифр)")
    if payload.mode in ("atol", "yookassa") and not data["inn"]:
        raise HTTPException(422, "Укажите ИНН продавца")
    if payload.mode == "atol" and not (data["company_email"] and data["payment_address"]):
        raise HTTPException(422, "Укажите e-mail продавца и адрес сайта для чека")
    # Turning receipts on (or switching the way) starts from now: old orders are never sent.
    data["enabled_at"] = None if payload.mode == "off" else (current.enabled_at if current.mode == payload.mode and current.enabled_at else datetime.utcnow())
    if not data["npd_device_id"]:
        data["npd_device_id"] = current.npd_device_id or uuid.uuid4().hex[:21]
    config = FiscalConfig.model_validate(data)
    row = await db.get(AppSetting, SETTING_KEY)
    text = config.model_dump_json()
    if row:
        row.value = text
    else:
        db.add(AppSetting(key=SETTING_KEY, value=text))
    _NPD_TOKENS.clear()
    await audit(db, "fiscal.config.updated", admin.email, None, {"mode": config.mode, "providers": config.providers, "taxation": config.taxation, "vat": config.vat})
    await db.commit()
    return {"config": public_config(config)}


@router.post("/api/admin/fiscal/test")
async def admin_fiscal_test(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("payments.write"))):
    try:
        return await check_connection(await load_config(db))
    except FiscalError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:
        return {"ok": False, "message": f"Нет связи: {type(exc).__name__}"}


@router.post("/api/admin/fiscal/receipts/{receipt_id}/retry")
async def admin_fiscal_retry(receipt_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("payments.write"))):
    from .main import audit

    receipt = (await db.execute(select(FiscalReceipt).where(FiscalReceipt.id == receipt_id).with_for_update())).scalar_one_or_none()
    if not receipt:
        raise HTTPException(404, "Чек не найден")
    if receipt.status == "done":
        raise HTTPException(409, "Чек уже сформирован")
    receipt.attempts = 0
    await send_receipt(db, receipt, await load_config(db))
    await audit(db, "fiscal.receipt.retry", admin.email, str(receipt.id), {"status": receipt.status})
    await db.commit()
    return _row(receipt)


@router.get("/api/me/receipts")
async def my_receipts(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token

    user = await user_from_token(request, db)
    rows = (await db.execute(select(FiscalReceipt).join(Payment, Payment.id == FiscalReceipt.payment_id)
                             .where(Payment.user_id == user.id, FiscalReceipt.status == "done").order_by(FiscalReceipt.id.desc()).limit(50))).scalars().all()
    return [{"payment_id": r.payment_id, "kind": r.kind, "amount": str(r.amount), "name": r.name, "receipt_url": r.receipt_url,
             "created_at": r.created_at} for r in rows]
