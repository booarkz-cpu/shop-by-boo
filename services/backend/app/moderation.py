"""Moderation: who may register and who may stay.

* **Black list** — Telegram IDs, e-mails and e-mail domains that may not register (an existing customer on the list is
  restricted: shop access off, subscriptions paused — ``platform_api.suspend_access``).
* **Bulk ban** — a pasted list of Telegram IDs: known customers are restricted, unknown ones go to the black list.
* **Disposable e-mail** — registrations from throw-away mailboxes (built-in list + the owner's extra domains) are refused.
* **Invite-only registration** — new accounts need a one-time or limited invite code (bot ``/start inv_CODE``,
  cabinet and Mini App ``?invite=CODE``); existing customers are never affected.
* **Customers who blocked the bot** — a background scan asks Telegram (``sendChatAction``) for each customer,
  shows who blocked the bot and can clean up long-inactive ones: no live
  subscription, no balance, no payment for 90 days → the account is closed like a self-deletion.

Everything is in «Клиенты → Модерация» (web) and the «Модерация» card of the mobile admins.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.moderation")
router = APIRouter()

CONFIG_KEY = "moderation.config"
INVITES_KEY = "moderation.invites"
SCAN_KEY = "moderation.blocked_scan"
DEFAULT_CONFIG = {"block_disposable": True, "disposable_extra": [], "invite_only": False,
                  "blacklist": {"telegram_ids": [], "emails": [], "domains": []}}
MAX_LIST = 50000
DISPOSABLE = frozenset("""
10minutemail.com 10minutemail.net 1secmail.com 1secmail.net 1secmail.org 20minutemail.com 33mail.com burnermail.io
crazymailing.com discard.email dispostable.com dropmail.me emailfake.com emailondeck.com fakeinbox.com getnada.com
grr.la guerrillamail.biz guerrillamail.com guerrillamail.de guerrillamail.info guerrillamail.net guerrillamail.org
guerrillamailblock.com harakirimail.com inboxkitten.com incognitomail.org luxusmail.org mail.tm mail7.io mailcatch.com
maildrop.cc mailforspam.com mailinator.com mailinator.net mailnesia.com mailpoof.com mailsac.com mintemail.com
minutemail.com moakt.com mohmal.com mytemp.email nada.email sharklasers.com spam4.me spambox.us spamgourmet.com
temp-mail.io temp-mail.org tempail.com tempinbox.com tempmail.com tempmail.dev tempmail.net tempmailaddress.com
tempmailo.com tempr.email throwawaymail.com tmail.ws trashmail.com trashmail.de trashmail.net yopmail.com yopmail.fr
yopmail.net emailtemporanea.com tempmail.plus mail-temp.com internxt.com tmpmail.org tmpmail.net fakemail.net
""".split())
INVITE_RE = re.compile(r"^[A-Za-z0-9_-]{4,40}$")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _load(db, key, default):
    from .node_health import _load as load
    return await load(db, key, default)


async def _save(db, key, value):
    from .node_health import _save as save
    await save(db, key, value)


def _domain_and_parents(domain: str):
    parts = domain.lower().strip(".").split(".")
    for i in range(len(parts) - 1):
        yield ".".join(parts[i:])


def disposable(email: str, extra: list[str] | None = None) -> bool:
    domain = email.rsplit("@", 1)[-1].lower()
    extra_set = {d.lower().strip() for d in (extra or [])}
    return any(d in DISPOSABLE or d in extra_set for d in _domain_and_parents(domain))


def blacklisted(config: dict, *, telegram_id: int | None = None, email: str | None = None) -> bool:
    black = config.get("blacklist") or {}
    if telegram_id is not None and int(telegram_id) in {int(x) for x in black.get("telegram_ids", [])}:
        return True
    if email:
        email = email.lower().strip()
        if email in {e.lower() for e in black.get("emails", [])}:
            return True
        domains = {d.lower() for d in black.get("domains", [])}
        if any(d in domains for d in _domain_and_parents(email.rsplit("@", 1)[-1])):
            return True
    return False


async def registration_check(db: AsyncSession, *, telegram_id: int | None = None, email: str | None = None,
                             invite: str | None = None) -> None:
    """Called before a NEW account is created; raises 403 with a reason the customer can read."""
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    if blacklisted(config, telegram_id=telegram_id, email=email):
        raise HTTPException(403, "Регистрация недоступна")
    if email and config.get("block_disposable", True) and disposable(email, config.get("disposable_extra")):
        raise HTTPException(403, "Временные почтовые ящики не принимаются — укажите постоянный email")
    if config.get("invite_only"):
        if not invite or not INVITE_RE.match(invite):
            raise HTTPException(403, "Регистрация только по приглашению")
        invites = await _load(db, INVITES_KEY, {})
        row = invites.get(_hash(invite.strip()))
        now = datetime.utcnow()
        if (not row or row.get("disabled") or (row.get("expires_at") and datetime.fromisoformat(row["expires_at"]) < now)
                or (row.get("max_uses") and int(row.get("uses", 0)) >= int(row["max_uses"]))):
            raise HTTPException(403, "Приглашение недействительно или закончилось")
        row["uses"] = int(row.get("uses", 0)) + 1
        invites[_hash(invite.strip())] = row
        await _save(db, INVITES_KEY, invites)


def invite_from_start(arg: str) -> str | None:
    """``/start inv_CODE`` or ``…__inv_CODE`` next to a referral or a source."""
    for part in (arg or "").split("__"):
        if part.startswith("inv_"):
            return part[4:]
    return None


# ---------------------------------------------------------------- customers who blocked the bot

async def blocked_ids(db: AsyncSession) -> set[int]:
    state = await _load(db, SCAN_KEY, {})
    return {int(x) for x in state.get("blocked", [])}


async def scan_blocked(db_factory, *, client=None, pause: float = 0.05, limit: int | None = None) -> dict:
    """Ask Telegram about every customer with a Telegram account (sendChatAction «typing», invisible to them)."""
    from . import tg
    from .models import User
    async with db_factory() as db:
        ids = [row[0] for row in (await db.execute(select(User.telegram_id).where(
            User.telegram_id.is_not(None), User.deleted_at.is_(None)).order_by(User.id))).all()][:limit]
        await _save(db, SCAN_KEY, {**(await _load(db, SCAN_KEY, {})), "running": True, "total": len(ids), "checked": 0,
                                    "started_at": datetime.utcnow().isoformat()})
        await db.commit()
    blocked, errors = [], 0
    for index, telegram_id in enumerate(ids, 1):
        try:
            await tg.call("sendChatAction", {"chat_id": telegram_id, "action": "typing"}, client)
        except tg.TelegramError as exc:
            if exc.code == 429:
                await asyncio.sleep(int(re.findall(r"\d+", exc.description or "1")[-1] if re.findall(r"\d+", exc.description or "") else 1))
            elif exc.blocked:
                blocked.append(int(telegram_id))
            else:
                errors += 1
        except Exception:  # noqa: BLE001 — network: counted, the scan goes on
            errors += 1
        if index % 200 == 0:
            async with db_factory() as db:
                state = await _load(db, SCAN_KEY, {})
                state["checked"] = index
                await _save(db, SCAN_KEY, state)
                await db.commit()
        if pause:
            await asyncio.sleep(pause)
    async with db_factory() as db:
        result = {"running": False, "total": len(ids), "checked": len(ids), "blocked": blocked, "errors": errors,
                  "finished_at": datetime.utcnow().isoformat()}
        await _save(db, SCAN_KEY, result)
        await db.commit()
    return result


async def cleanup_candidates(db: AsyncSession, now: datetime | None = None) -> list[int]:
    """Blocked the bot, no live subscription, no balance, no payment in 90 days → user ids."""
    from .models import Payment, Subscription, User
    now = now or datetime.utcnow()
    ids = await blocked_ids(db)
    if not ids:
        return []
    users = (await db.execute(select(User).where(User.telegram_id.in_(ids), User.deleted_at.is_(None)))).scalars().all()
    out = []
    for user in users:
        if (user.wallet_balance or 0) > 0 or (user.referral_balance or 0) > 0:
            continue
        live = await db.scalar(select(func.count()).select_from(Subscription).where(
            Subscription.user_id == user.id, Subscription.expires_at > now))
        paid = await db.scalar(select(func.count()).select_from(Payment).where(
            Payment.user_id == user.id, Payment.created_at > now - timedelta(days=90)))
        if not live and not paid:
            out.append(user.id)
    return out


# ---------------------------------------------------------------- admin API

class ConfigIn(BaseModel):
    block_disposable: bool = True
    disposable_extra: list[str] = Field(default_factory=list, max_length=2000)
    invite_only: bool = False


class ListIn(BaseModel):
    telegram_ids: list[int] = Field(default_factory=list, max_length=MAX_LIST)
    emails: list[str] = Field(default_factory=list, max_length=MAX_LIST)
    domains: list[str] = Field(default_factory=list, max_length=5000)


class BanIn(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    unban: bool = False


class InviteIn(BaseModel):
    note: str = Field("", max_length=120)
    max_uses: int = Field(1, ge=0, le=100000)
    days: int = Field(30, ge=0, le=3650)


@router.get("/api/admin/moderation")
async def get_moderation(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.read"))):
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    invites = await _load(db, INVITES_KEY, {})
    scan = await _load(db, SCAN_KEY, {})
    black = config.get("blacklist") or {}
    return {"config": {k: v for k, v in config.items() if k != "blacklist"},
            "blacklist": {k: len(v) for k, v in black.items()}, "blacklist_items": {k: v[:200] for k, v in black.items()},
            "invites": [{"id": k[:12], **{f: v.get(f) for f in ("note", "uses", "max_uses", "expires_at", "disabled", "created_at")}}
                        for k, v in invites.items()],
            "scan": {k: (len(v) if k == "blocked" else v) for k, v in scan.items()},
            "cleanup_candidates": len(await cleanup_candidates(db)), "disposable_builtin": len(DISPOSABLE)}


@router.put("/api/admin/moderation")
async def put_moderation(payload: ConfigIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.write"))):
    from .main import audit
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    config.update(payload.model_dump())
    config["disposable_extra"] = sorted({d.lower().strip() for d in payload.disposable_extra if d.strip()})
    await _save(db, CONFIG_KEY, config)
    await audit(db, "moderation.config", admin.email, None, {k: v for k, v in config.items() if k != "blacklist"})
    await db.commit()
    return {"ok": True}


@router.put("/api/admin/moderation/blacklist")
async def put_blacklist(payload: ListIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.write"))):
    from .main import audit
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    config["blacklist"] = {"telegram_ids": sorted(set(payload.telegram_ids)),
                           "emails": sorted({e.lower().strip() for e in payload.emails if "@" in e}),
                           "domains": sorted({d.lower().strip().lstrip("@") for d in payload.domains if "." in d})}
    await _save(db, CONFIG_KEY, config)
    await audit(db, "moderation.blacklist", admin.email, None, {k: len(v) for k, v in config["blacklist"].items()})
    await db.commit()
    return {k: len(v) for k, v in config["blacklist"].items()}


@router.post("/api/admin/moderation/ban")
async def bulk_ban(payload: BanIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.write"))):
    """Telegram IDs in any text (one per line, commas, a CSV column): customers restricted, unknown IDs black-listed."""
    from .main import audit
    from .models import User
    from .platform_api import resume_access, suspend_access
    ids = sorted({int(x) for x in re.findall(r"(?<!\d)\d{5,15}(?!\d)", payload.text)})
    if not ids:
        raise HTTPException(400, "В тексте нет Telegram ID")
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    black = config.setdefault("blacklist", {"telegram_ids": [], "emails": [], "domains": []})
    current = set(black.get("telegram_ids", []))
    users = (await db.execute(select(User).where(User.telegram_id.in_(ids)))).scalars().all()
    changed = 0
    for user in users:
        if payload.unban and user.restricted_at:
            await resume_access(db, user)
            changed += 1
        elif not payload.unban and not user.restricted_at and not user.deleted_at:
            await suspend_access(db, user)
            changed += 1
    known = {u.telegram_id for u in users}
    if payload.unban:
        current -= set(ids)
    else:
        current |= set(ids) - known
    black["telegram_ids"] = sorted(current)[:MAX_LIST]
    await _save(db, CONFIG_KEY, config)
    await audit(db, "moderation.unban" if payload.unban else "moderation.ban", admin.email, None,
                {"ids": len(ids), "customers": changed})
    await db.commit()
    return {"ids": len(ids), "customers": changed, "blacklisted": 0 if payload.unban else len(set(ids) - known)}


@router.post("/api/admin/moderation/invites")
async def create_invite(payload: InviteIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.write"))):
    from .config import settings
    from .main import audit
    code = secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:12]
    invites = await _load(db, INVITES_KEY, {})
    now = datetime.utcnow()
    invites[_hash(code)] = {"note": payload.note.strip(), "uses": 0, "max_uses": payload.max_uses,
                            "expires_at": (now + timedelta(days=payload.days)).isoformat() if payload.days else None,
                            "disabled": False, "created_at": now.isoformat()}
    await _save(db, INVITES_KEY, invites)
    await audit(db, "moderation.invite", admin.email, _hash(code)[:12], {"note": payload.note, "max_uses": payload.max_uses})
    await db.commit()
    bot = f"https://t.me/{settings.bot_username}?start=inv_{code}" if settings.bot_username else ""
    cabinet = f"{(settings.cabinet_url or settings.mini_app_url or '').rstrip('/')}/?invite={code}"
    return {"code": code, "bot_link": bot, "cabinet_link": cabinet}


@router.delete("/api/admin/moderation/invites/{invite_id}")
async def disable_invite(invite_id: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.write"))):
    invites = await _load(db, INVITES_KEY, {})
    key = next((k for k in invites if k.startswith(invite_id)), None)
    if not key:
        raise HTTPException(404, "Приглашение не найдено")
    invites[key]["disabled"] = True
    await _save(db, INVITES_KEY, invites)
    await db.commit()
    return {"ok": True}


_scan_task: asyncio.Task | None = None


@router.post("/api/admin/moderation/blocked-scan")
async def start_scan(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.write"))):
    """Starts the scan in this process (one at a time); progress in GET /api/admin/moderation."""
    global _scan_task
    if _scan_task and not _scan_task.done():
        raise HTTPException(409, "Проверка уже идёт")
    from .db import SessionLocal
    _scan_task = asyncio.create_task(scan_blocked(SessionLocal))
    return {"started": True}


@router.post("/api/admin/moderation/blocked-cleanup")
async def blocked_cleanup(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.write"))):
    """Close the accounts of long-inactive customers who blocked the bot (no subscription, balance or payment)."""
    from .main import audit
    from .models import User
    ids = await cleanup_candidates(db)
    now = datetime.utcnow()
    for user in (await db.execute(select(User).where(User.id.in_(ids)))).scalars():
        user.deleted_at = now
        user.auto_renew_enabled = False
    await audit(db, "moderation.blocked_cleanup", admin.email, None, {"closed": len(ids)})
    await db.commit()
    return {"closed": len(ids)}
