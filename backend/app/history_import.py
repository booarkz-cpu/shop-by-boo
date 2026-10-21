"""Versioned historical import of VPN subscriptions and payments from another shop.

Flow: inspect -> preview (no writes to customer data) -> apply -> optional rollback.

* Adapters are versioned (`generic-sqlite-v1`); the normalized payload and the
  adapter version are stored encrypted with the preview, so apply replays exactly
  what was reviewed (immutable snapshot, fingerprinted with current DB state).
* Customers are resolved only through identities created by the profile import of
  the same namespace; unknown or deleted customers block the preview.
* Reconciliation: the operator enters control totals taken from the old system.
  Any count/amount mismatch or blocked row makes apply impossible.
* Repeating a snapshot never duplicates rows: payments are keyed by source payment
  id, subscriptions by Remnawave UUID; identical rows report `already_imported`,
  changed ones are `conflict`.
* Imported payments are history only. They are never fulfilled, refunded,
  rewarded or counted as revenue. Subscriptions reuse existing Remnawave users.
* Rollback removes what one job created, but only while none of it has been used
  or changed since; otherwise it refuses and lists the blocking records.
"""
import asyncio
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .admin_customer_operations import advisory, digest, identity_key, uploaded
from .config import settings
from .db import get_db
from .models import (CustomerImportIdentity, EntitlementOperation, EntitlementQuote, GiftRedemption, HistoryImportJob,
    ImportedPayment, ImportedSubscriptionLink, Payment, Plan, Subscription, TrialGrant, User, UserDevice)
from .security import decrypt_secret, encrypt_secret, require_permission
from .sqlite_import import MAX_ROWS, read_table

ADAPTER = "generic-sqlite-v1"
COLUMN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
MAX_TOTAL = Decimal("100000000")


def private(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(prefix="/api/admin/customer-operations/history", dependencies=[Depends(private)])


class PaymentMap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str = Field(pattern=COLUMN)
    id: str = Field(pattern=COLUMN)
    user: str = Field(pattern=COLUMN)
    amount: str = Field(pattern=COLUMN)
    amount_unit: Literal["decimal", "minor"] = "decimal"
    currency: str | None = Field(default=None, pattern=COLUMN)
    status: str | None = Field(default=None, pattern=COLUMN)
    paid_values: list[str] = Field(default_factory=lambda: ["paid", "succeeded", "success", "completed", "confirmed"], min_length=1, max_length=20)
    refunded_values: list[str] = Field(default_factory=lambda: ["refunded"], max_length=20)
    paid_at: str | None = Field(default=None, pattern=COLUMN)
    description: str | None = Field(default=None, pattern=COLUMN)


class SubscriptionMap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str = Field(pattern=COLUMN)
    user: str = Field(pattern=COLUMN)
    expires_at: str = Field(pattern=COLUMN)
    remnawave_uuid: str = Field(pattern=COLUMN)
    subscription_url: str | None = Field(default=None, pattern=COLUMN)
    plan: str | None = Field(default=None, pattern=COLUMN)
    traffic_gb: str | None = Field(default=None, pattern=COLUMN)
    devices: str | None = Field(default=None, pattern=COLUMN)


class ControlIn(BaseModel):
    """Totals copied from the old system; apply requires an exact match."""
    model_config = ConfigDict(extra="forbid")
    payments_count: int | None = Field(default=None, ge=0, le=MAX_ROWS)
    payments_total: Decimal | None = Field(default=None, ge=0, le=MAX_TOTAL, decimal_places=2)
    subscriptions_count: int | None = Field(default=None, ge=0, le=MAX_ROWS)


class HistoryMappingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adapter: Literal["generic-sqlite-v1"] = ADAPTER
    namespace: str = Field(pattern=r"^[A-Za-z0-9_-]{3,64}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    default_plan_id: int | None = Field(default=None, ge=1)
    payments: PaymentMap | None = None
    subscriptions: SubscriptionMap | None = None
    control: ControlIn

    @model_validator(mode="after")
    def complete(self):
        if not self.payments and not self.subscriptions:
            raise ValueError("Выберите таблицу платежей и/или подписок")
        if self.payments and (self.control.payments_count is None or self.control.payments_total is None):
            raise ValueError("Укажите контрольные количество и сумму платежей")
        if self.subscriptions and self.control.subscriptions_count is None:
            raise ValueError("Укажите контрольное количество подписок")
        return self


def payment_key(namespace: str, source_id: str) -> str:
    return digest(["history-payment-v1", namespace, source_id])


def subscription_key(namespace: str, remnawave_uuid: str) -> str:
    return digest(["history-subscription-v1", namespace, remnawave_uuid.lower()])


def _text(value, limit: int, index: int, field: str, required=True) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise HTTPException(422, f"Строка {index}: пустое поле {field}")
        return None
    if isinstance(value, (bytes, bool, float)) or not isinstance(value, (str, int)):
        raise HTTPException(422, f"Строка {index}: поле {field} должно быть строкой или целым числом")
    value = str(value).strip()
    if len(value) > limit or any(ord(ch) < 32 for ch in value):
        raise HTTPException(422, f"Строка {index}: поле {field} слишком длинное или содержит управляющие символы")
    return value


def _date(value, index: int, field: str, required: bool) -> str | None:
    """ISO-8601 text or Unix seconds/milliseconds -> naive UTC ISO string."""
    if value is None or value == "":
        if required:
            raise HTTPException(422, f"Строка {index}: пустая дата {field}")
        return None
    try:
        if isinstance(value, bool) or isinstance(value, bytes):
            raise ValueError
        if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d{9,13}", value.strip())):
            number = float(value)
            moment = datetime.fromtimestamp(number / 1000 if number > 10**11 else number, tz=timezone.utc)
        else:
            moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00").replace(" ", "T", 1))
            if moment.tzinfo:
                moment = moment.astimezone(timezone.utc)
        moment = moment.replace(tzinfo=None, microsecond=0)
        if not datetime(2000, 1, 1) <= moment <= datetime(2100, 1, 1):
            raise ValueError
        return moment.isoformat()
    except (ValueError, OverflowError, OSError):
        raise HTTPException(422, f"Строка {index}: неверная дата {field}") from None


def _amount(value, unit: str, index: int) -> Decimal:
    try:
        if value is None or isinstance(value, (bytes, bool)):
            raise ValueError
        amount = Decimal(str(value).strip()) / (100 if unit == "minor" else 1)
        if not amount.is_finite() or not Decimal("0") < amount <= Decimal("1000000") or amount != amount.quantize(Decimal(".01")):
            raise ValueError
        return amount.quantize(Decimal(".01"))
    except (ValueError, InvalidOperation):
        raise HTTPException(422, f"Строка {index}: сумма должна быть 0.01–1000000 с точностью до 0.01") from None


def _int(value, index: int, field: str, low: int, high: int) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not re.fullmatch(r"\d{1,7}", str(value).strip()) or not low <= int(str(value).strip()) <= high:
        raise HTTPException(422, f"Строка {index}: поле {field} должно быть целым {low}–{high}")
    return int(str(value).strip())


def extract(data: bytes, mapping: HistoryMappingIn) -> dict:
    """Pure function: snapshot bytes -> normalized rows. Never touches the shop database."""
    out = {"payments": [], "subscriptions": [], "skipped_payments": 0}
    if mapping.payments:
        p = mapping.payments
        columns = [p.id, p.user, p.amount] + [c for c in (p.currency, p.status, p.paid_at, p.description) if c]
        _, rows = read_table(data, p.table, list(dict.fromkeys(columns)))
        if len(rows) > MAX_ROWS:
            raise HTTPException(422, f"Не больше {MAX_ROWS} платежей за один перенос")
        position = {name: i for i, name in enumerate(dict.fromkeys(columns))}
        paid = {v.strip().lower() for v in p.paid_values}
        refunded = {v.strip().lower() for v in p.refunded_values}
        seen = set()
        for index, row in enumerate(rows, 1):
            status = "paid"
            if p.status:
                raw = str(row[position[p.status]] or "").strip().lower()
                if raw in refunded:
                    status = "refunded"
                elif raw not in paid:
                    out["skipped_payments"] += 1
                    continue
            source_id = _text(row[position[p.id]], 128, index, "id")
            if source_id in seen:
                raise HTTPException(422, f"Строка {index}: повтор ID платежа")
            seen.add(source_id)
            currency = _text(row[position[p.currency]], 3, index, "currency").upper() if p.currency else mapping.currency
            if currency != mapping.currency:
                raise HTTPException(422, f"Строка {index}: валюта {currency} отличается от валюты переноса")
            out["payments"].append({
                "source_id": source_id,
                "user": _text(row[position[p.user]], 128, index, "user"),
                "amount": str(_amount(row[position[p.amount]], p.amount_unit, index)),
                "currency": currency,
                "status": status,
                "paid_at": _date(row[position[p.paid_at]], index, "paid_at", False) if p.paid_at else None,
                "description": _text(row[position[p.description]], 255, index, "description", False) if p.description else None,
            })
    if mapping.subscriptions:
        s = mapping.subscriptions
        columns = [s.user, s.expires_at, s.remnawave_uuid] + [c for c in (s.subscription_url, s.plan, s.traffic_gb, s.devices) if c]
        _, rows = read_table(data, s.table, list(dict.fromkeys(columns)))
        if len(rows) > MAX_ROWS:
            raise HTTPException(422, f"Не больше {MAX_ROWS} подписок за один перенос")
        position = {name: i for i, name in enumerate(dict.fromkeys(columns))}
        seen = set()
        for index, row in enumerate(rows, 1):
            uuid = _text(row[position[s.remnawave_uuid]], 64, index, "remnawave_uuid")
            if not re.fullmatch(r"[0-9A-Fa-f-]{8,64}", uuid):
                raise HTTPException(422, f"Строка {index}: неверный UUID Remnawave")
            if uuid.lower() in seen:
                raise HTTPException(422, f"Строка {index}: повтор UUID Remnawave")
            seen.add(uuid.lower())
            url = _text(row[position[s.subscription_url]], 2048, index, "subscription_url", False) if s.subscription_url else None
            if url and not url.startswith("https://"):
                raise HTTPException(422, f"Строка {index}: ссылка подписки должна начинаться с https://")
            out["subscriptions"].append({
                "user": _text(row[position[s.user]], 128, index, "user"),
                "remnawave_uuid": uuid.lower(),
                "expires_at": _date(row[position[s.expires_at]], index, "expires_at", True),
                "subscription_url": url,
                "plan": _text(row[position[s.plan]], 255, index, "plan", False) if s.plan else None,
                "traffic_gb": _int(row[position[s.traffic_gb]], index, "traffic_gb", 0, 1_000_000) if s.traffic_gb else None,
                "devices": _int(row[position[s.devices]], index, "devices", 1, 100) if s.devices else None,
            })
    out["payments"].sort(key=lambda r: r["source_id"])
    out["subscriptions"].sort(key=lambda r: r["remnawave_uuid"])
    return out


def reconciliation(mapping: HistoryMappingIn, rows: dict) -> dict:
    paid_total = sum((Decimal(r["amount"]) for r in rows["payments"] if r["status"] == "paid"), Decimal("0.00"))
    checks = []
    if mapping.payments:
        checks.append({"name": "payments_count", "expected": mapping.control.payments_count, "actual": len(rows["payments"])})
        checks.append({"name": "payments_total", "expected": str(mapping.control.payments_total.quantize(Decimal(".01"))), "actual": str(paid_total.quantize(Decimal(".01")))})
    if mapping.subscriptions:
        checks.append({"name": "subscriptions_count", "expected": mapping.control.subscriptions_count, "actual": len(rows["subscriptions"])})
    for check in checks:
        check["ok"] = str(check["expected"]) == str(check["actual"])
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "skipped_payments": rows["skipped_payments"],
            "refunded_payments": sum(r["status"] == "refunded" for r in rows["payments"])}


async def plan_lookup(db: AsyncSession) -> dict[str, Plan]:
    plans = (await db.scalars(select(Plan).order_by(Plan.id))).all()
    return {p.name.strip().lower(): p for p in plans} | {f"#{p.id}": p for p in plans}


async def evaluate(db: AsyncSession, payload: dict, lock=False):
    """Classify every row against the current shop state and fingerprint that state."""
    mapping = HistoryMappingIn.model_validate(payload["mapping"])
    rows = payload["rows"]
    if mapping.currency != settings.default_currency:
        raise HTTPException(409, "Валюта переноса отличается от валюты магазина")
    users_by_source = {}
    sources = {r["user"] for r in rows["payments"]} | {r["user"] for r in rows["subscriptions"]}
    if sources:
        keys = {identity_key(mapping.namespace, source): source for source in sources}
        identities = (await db.scalars(select(CustomerImportIdentity).where(CustomerImportIdentity.key.in_(list(keys))))).all()
        ids = {row.key: row.user_id for row in identities}
        statement = select(User).where(User.id.in_(list(ids.values()) or [0])).order_by(User.id).execution_options(populate_existing=True)
        if lock:
            statement = statement.with_for_update()
        loaded = {user.id: user for user in (await db.scalars(statement)).all()}
        users_by_source = {source: loaded.get(ids.get(key)) for key, source in keys.items()}
    plans = await plan_lookup(db)
    default_plan = await db.get(Plan, mapping.default_plan_id) if mapping.default_plan_id else None
    if mapping.default_plan_id and not default_plan:
        raise HTTPException(422, "Тариф по умолчанию не найден")

    pay_keys = [payment_key(mapping.namespace, r["source_id"]) for r in rows["payments"]]
    existing_payments = {row.source_key: row for row in (await db.scalars(select(ImportedPayment).where(ImportedPayment.source_key.in_(pay_keys or [""])))).all()}
    sub_keys = [subscription_key(mapping.namespace, r["remnawave_uuid"]) for r in rows["subscriptions"]]
    existing_links = {row.source_key: row for row in (await db.scalars(select(ImportedSubscriptionLink).where(ImportedSubscriptionLink.source_key.in_(sub_keys or [""])))).all()}
    uuids = [r["remnawave_uuid"] for r in rows["subscriptions"]]
    occupied = {row.remnawave_uuid.lower(): row for row in (await db.scalars(select(Subscription).where(func.lower(Subscription.remnawave_uuid).in_(uuids or [""])))).all()}

    payments, subscriptions, state = [], [], []
    for row, key in zip(rows["payments"], pay_keys):
        user = users_by_source.get(row["user"])
        prior = existing_payments.get(key)
        if prior:
            same = (prior.user_id == (user.id if user else None) and str(prior.amount) == row["amount"]
                    and prior.currency == row["currency"] and prior.status == row["status"])
            status, reason = ("already_imported", None) if same else ("conflict", "Платёж уже перенесён с другими данными")
        elif not user:
            status, reason = "blocked", "Клиент не найден: сначала перенесите профили этого источника"
        elif user.deleted_at:
            status, reason = "blocked", "Клиент удалён"
        else:
            status, reason = "new", None
        payments.append({**row, "status_import": status, "reason": reason, "user_id": user.id if user else None})
        state.append(["p", key, status, user.id if user else None, str(user.deleted_at) if user else None])
    for row, key in zip(rows["subscriptions"], sub_keys):
        user = users_by_source.get(row["user"])
        link = existing_links.get(key)
        plan = plans.get((row["plan"] or "").strip().lower()) if row["plan"] else None
        plan = plan or default_plan
        if link:
            snap = link.snapshot or {}
            same = (snap.get("expires_at") == row["expires_at"] and snap.get("user_id") == (user.id if user else None))
            status, reason = ("already_imported", None) if same else ("conflict", "Подписка уже перенесена с другими данными")
        elif not user:
            status, reason = "blocked", "Клиент не найден: сначала перенесите профили этого источника"
        elif user.deleted_at:
            status, reason = "blocked", "Клиент удалён"
        elif row["remnawave_uuid"] in occupied:
            status, reason = "blocked", "UUID Remnawave уже привязан к подписке магазина"
        elif not plan:
            status, reason = "blocked", "Тариф не найден; выберите тариф по умолчанию"
        else:
            status, reason = "new", None
        subscriptions.append({**row, "status_import": status, "reason": reason, "user_id": user.id if user else None,
                              "plan_id": plan.id if plan else None})
        holder = occupied.get(row["remnawave_uuid"])
        state.append(["s", key, status, user.id if user else None, plan.id if plan else None, holder.id if holder else None])
    report = reconciliation(mapping, rows)
    fingerprint = digest({"adapter": mapping.adapter, "payload": payload, "state": state, "currency": settings.default_currency})
    return mapping, payments, subscriptions, report, fingerprint, users_by_source


def counts(rows: list[dict]) -> dict:
    return {s: sum(r["status_import"] == s for r in rows) for s in ("new", "already_imported", "conflict", "blocked")}


def summary(job: HistoryImportJob, payments, subscriptions, report) -> dict:
    return {"id": job.id, "adapter": job.adapter, "namespace": job.namespace, "fingerprint": job.fingerprint,
            "source_sha256": job.source_sha256, "expires_at": job.expires_at, "reconciliation": report,
            "payments": {"counts": counts(payments), "rows": payments[:200]},
            "subscriptions": {"counts": counts(subscriptions), "rows": subscriptions[:200]},
            "can_apply": report["ok"] and not any(r["status_import"] in ("blocked", "conflict") for r in payments + subscriptions)}


@router.post("/inspect")
async def inspect(file: UploadFile = File(...), table: str = Form(...), admin=Depends(require_permission("users.import"))):
    columns, _ = await asyncio.to_thread(read_table, await uploaded(file), table)
    return {"table": table, "columns": columns, "currency": settings.default_currency, "adapter": ADAPTER, "max_rows": MAX_ROWS}


@router.get("")
async def history_jobs(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.import"))):
    rows = (await db.scalars(select(HistoryImportJob).where(HistoryImportJob.actor == admin.email).order_by(HistoryImportJob.created_at.desc()).limit(50))).all()
    return [{"id": r.id, "namespace": r.namespace, "adapter": r.adapter, "status": r.status, "source_sha256": r.source_sha256,
             "created_at": r.created_at, "applied_at": r.applied_at, "rolled_back_at": r.rolled_back_at, "result": r.result} for r in rows]


@router.post("/preview")
async def preview(file: UploadFile = File(...), mapping: str = Form(...), db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.import"))):
    try:
        configuration = HistoryMappingIn.model_validate_json(mapping)
    except ValidationError as error:
        raise HTTPException(422, "Проверьте mapping полей и контрольные суммы") from error
    data = await uploaded(file)
    rows = await asyncio.to_thread(extract, data, configuration)
    payload = {"mapping": json.loads(configuration.model_dump_json()), "rows": rows}
    _, payments, subscriptions, report, fingerprint, _ = await evaluate(db, payload)
    job = HistoryImportJob(id=secrets.token_hex(24), namespace=configuration.namespace, adapter=configuration.adapter,
                           source_sha256=hashlib.sha256(data).hexdigest(), actor=admin.email, fingerprint=fingerprint,
                           payload_encrypted=encrypt_secret(json.dumps(payload, ensure_ascii=False)),
                           control=json.loads(configuration.control.model_dump_json()), status="preview",
                           expires_at=datetime.utcnow() + timedelta(minutes=30))
    db.add(job)
    await db.commit()
    return summary(job, payments, subscriptions, report)


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(pattern="^[a-f0-9]{64}$")


@router.post("/{job_id}/apply")
async def apply(job_id: str, body: ApplyIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.import"))):
    from .main import audit
    job = await db.scalar(select(HistoryImportJob).where(HistoryImportJob.id == job_id).with_for_update().execution_options(populate_existing=True))
    if not job or job.actor != admin.email:
        raise HTTPException(404, "Preview не найден")
    if job.fingerprint != body.fingerprint:
        raise HTTPException(409, "Fingerprint не совпадает")
    if job.status == "applied":
        return job.result
    if job.status != "preview" or job.expires_at <= datetime.utcnow():
        raise HTTPException(409, "Preview истёк, отменён или откатан")
    payload = json.loads(decrypt_secret(job.payload_encrypted))
    await advisory(db, digest(["history-import", job.namespace]))
    mapping, payments, subscriptions, report, fingerprint, _ = await evaluate(db, payload, lock=True)
    if fingerprint != job.fingerprint:
        raise HTTPException(409, "Данные магазина изменились; создайте новый preview")
    if not report["ok"]:
        raise HTTPException(409, "Контрольные суммы не совпадают с переносом")
    if any(r["status_import"] in ("blocked", "conflict") for r in payments + subscriptions):
        raise HTTPException(409, "Preview содержит конфликты")
    now = datetime.utcnow()
    created_payments, created_subscriptions = [], []
    try:
        for row in payments:
            if row["status_import"] != "new":
                continue
            item = ImportedPayment(source_key=payment_key(mapping.namespace, row["source_id"]), job_id=job.id, user_id=row["user_id"],
                                   source_payment_id=row["source_id"], amount=Decimal(row["amount"]), currency=row["currency"],
                                   status=row["status"], paid_at=datetime.fromisoformat(row["paid_at"]) if row["paid_at"] else None,
                                   description=row["description"])
            db.add(item)
            await db.flush()
            created_payments.append(item.id)
        primaries = set((await db.scalars(select(Subscription.user_id).where(Subscription.user_id.in_(
            [r["user_id"] for r in subscriptions if r["user_id"]] or [0]), Subscription.is_primary.is_(True)))).all())
        for row in subscriptions:
            if row["status_import"] != "new":
                continue
            plan = await db.get(Plan, row["plan_id"])
            expires = datetime.fromisoformat(row["expires_at"])
            primary = row["user_id"] not in primaries
            primaries.add(row["user_id"])
            sub = Subscription(user_id=row["user_id"], is_primary=primary, name=(row["plan"] or plan.name)[:80], plan_id=plan.id,
                               remnawave_uuid=row["remnawave_uuid"], subscription_url=row["subscription_url"], expires_at=expires,
                               traffic_limit_gb_snapshot=row["traffic_gb"] if row["traffic_gb"] is not None else plan.traffic_limit_gb,
                               device_limit_snapshot=row["devices"] if row["devices"] is not None else plan.device_limit,
                               remnawave_profile_id_snapshot=plan.remnawave_profile_id,
                               lifecycle_status="active" if expires > now else "expired")
            db.add(sub)
            await db.flush()
            snapshot = {"user_id": row["user_id"], "plan_id": plan.id, "remnawave_uuid": row["remnawave_uuid"],
                        "expires_at": row["expires_at"], "lifecycle_status": sub.lifecycle_status, "is_primary": primary}
            db.add(ImportedSubscriptionLink(source_key=subscription_key(mapping.namespace, row["remnawave_uuid"]), job_id=job.id,
                                            subscription_id=sub.id, user_id=row["user_id"], snapshot=snapshot))
            created_subscriptions.append(sub.id)
        job.result = {"ok": True, "payments_created": len(created_payments), "subscriptions_created": len(created_subscriptions),
                      "payments_already_imported": counts(payments)["already_imported"],
                      "subscriptions_already_imported": counts(subscriptions)["already_imported"],
                      "paid_total": next((c["actual"] for c in report["checks"] if c["name"] == "payments_total"), "0.00"),
                      "subscription_ids": created_subscriptions}
        job.status = "applied"
        job.applied_at = now
        job.payload_encrypted = ""
        await audit(db, "customers.history_import.applied", admin.email, job.id, {k: v for k, v in job.result.items() if k != "subscription_ids"})
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, "Данные изменились во время переноса; создайте новый preview") from error
    return job.result


@router.post("/{job_id}/cancel")
async def cancel(job_id: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.import"))):
    job = await db.scalar(select(HistoryImportJob).where(HistoryImportJob.id == job_id).with_for_update())
    if not job or job.actor != admin.email:
        raise HTTPException(404, "Preview не найден")
    if job.status != "preview":
        raise HTTPException(409, "Отменить можно только неприменённый preview")
    job.status = "cancelled"
    job.payload_encrypted = ""
    await db.commit()
    return {"ok": True}


class RollbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=500)


async def rollback_blockers(db: AsyncSession, job: HistoryImportJob) -> tuple[list[ImportedSubscriptionLink], list[dict]]:
    links = (await db.scalars(select(ImportedSubscriptionLink).where(ImportedSubscriptionLink.job_id == job.id)
                              .order_by(ImportedSubscriptionLink.subscription_id))).all()
    ids = [link.subscription_id for link in links]
    subs = {s.id: s for s in (await db.scalars(select(Subscription).where(Subscription.id.in_(ids or [0])).with_for_update()
                                               .execution_options(populate_existing=True))).all()}
    used = set()
    for model in (Payment, EntitlementQuote, EntitlementOperation, GiftRedemption, TrialGrant, UserDevice):
        used |= set((await db.scalars(select(model.subscription_id).where(model.subscription_id.in_(ids or [0])))).all())
    blockers = []
    for link in links:
        sub = subs.get(link.subscription_id)
        snap = link.snapshot or {}
        current = None if not sub else {"user_id": sub.user_id, "plan_id": sub.plan_id, "remnawave_uuid": (sub.remnawave_uuid or "").lower(),
                                        "expires_at": sub.expires_at.replace(microsecond=0).isoformat() if sub.expires_at else None,
                                        "lifecycle_status": sub.lifecycle_status}
        if not sub or any(current[k] != snap.get(k) for k in current):
            blockers.append({"subscription_id": link.subscription_id, "reason": "Подписка изменена после переноса"})
        elif link.subscription_id in used:
            blockers.append({"subscription_id": link.subscription_id, "reason": "Подписка уже используется (платёж, изменение, устройство)"})
    return links, blockers


@router.post("/{job_id}/rollback")
async def rollback(job_id: str, body: RollbackIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.import"))):
    from .main import audit
    job = await db.scalar(select(HistoryImportJob).where(HistoryImportJob.id == job_id).with_for_update().execution_options(populate_existing=True))
    if not job or job.actor != admin.email:
        raise HTTPException(404, "Перенос не найден")
    if job.status == "rolled_back":
        return job.result
    if job.status != "applied":
        raise HTTPException(409, "Откатить можно только применённый перенос")
    await advisory(db, digest(["history-import", job.namespace]))
    links, blockers = await rollback_blockers(db, job)
    if blockers:
        listed = ", ".join(f"#{b['subscription_id']}" for b in blockers[:20])
        raise HTTPException(409, f"Откат заблокирован: подписки {listed} изменены или уже используются")
    removed_payments = (await db.execute(delete(ImportedPayment).where(ImportedPayment.job_id == job.id))).rowcount or 0
    ids = [link.subscription_id for link in links]
    await db.execute(delete(ImportedSubscriptionLink).where(ImportedSubscriptionLink.job_id == job.id))
    await db.execute(delete(Subscription).where(Subscription.id.in_(ids or [0])))
    job.result = {**(job.result or {}), "rolled_back": True, "payments_removed": removed_payments, "subscriptions_removed": len(ids)}
    job.status = "rolled_back"
    job.rolled_back_at = datetime.utcnow()
    await audit(db, "customers.history_import.rolled_back", admin.email, job.id,
                {"payments_removed": removed_payments, "subscriptions_removed": len(ids), "reason": body.reason})
    await db.commit()
    return job.result


async def cleanup_history_previews(db: AsyncSession):
    await db.execute(update(HistoryImportJob).where(HistoryImportJob.status == "preview", HistoryImportJob.expires_at <= datetime.utcnow())
                     .values(status="expired", payload_encrypted=""))


async def customer_imported_payments(db: AsyncSession, user_id: int) -> list[dict]:
    rows = (await db.scalars(select(ImportedPayment).where(ImportedPayment.user_id == user_id)
                             .order_by(ImportedPayment.paid_at.desc(), ImportedPayment.id.desc()).limit(100))).all()
    return [{"id": r.id, "amount": str(r.amount), "currency": r.currency, "status": r.status, "paid_at": r.paid_at,
             "description": r.description} for r in rows]
