"""Prices and gateways by the customer's country (v28.47).

«Тарифы → Цены по странам». Off by default. A region is a set of countries with:

* ``percent`` — a markup or discount to every plan (−90…+300 %), or ``plan_prices`` — an exact price per plan;
* ``providers`` — gateways tried first for customers of this region (the rest of the queue follows).

Prices stay in the shop currency: payment gateways settle in it, so «local price» means the amount, not the currency.

The country comes from the request: ``CF-IPCountry`` when the shop is behind Cloudflare, else the registry country of
the client address (RIPEstat, cached in ``network_intel``). A customer already connected through one of the shop's own
servers is not placed in that server's country: the server addresses are skipped and the base price applies. The
plans list (cabinet, Mini App, apps) and checkout use the same calculation, so the price shown is the price charged; the
bot (its requests come from the server) shows and charges the base price.
"""
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.regional_pricing")
router = APIRouter()
CONFIG_KEY = "pricing.regions"
DEFAULT = {"enabled": False, "regions": []}


class RegionIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    countries: list[str] = Field(min_length=1, max_length=80)
    percent: int = Field(0, ge=-90, le=300)
    plan_prices: dict[str, Decimal] = Field(default_factory=dict)
    providers: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("countries")
    @classmethod
    def _cc(cls, v):
        out = sorted({c.strip().upper() for c in v if c.strip()})
        if any(len(c) != 2 or not c.isalpha() for c in out):
            raise ValueError("Страны — двухбуквенные коды ISO, например KZ, BY, AM")
        return out

    @field_validator("plan_prices")
    @classmethod
    def _prices(cls, v):
        for k, price in v.items():
            if not str(k).isdigit() or Decimal(str(price)) <= 0:
                raise ValueError("Цена тарифа — положительная сумма для номера тарифа")
        return {str(k): Decimal(str(p)).quantize(Decimal("0.01")) for k, p in v.items()}


class PricingIn(BaseModel):
    enabled: bool = False
    regions: list[RegionIn] = Field(default_factory=list, max_length=30)


async def load(db: AsyncSession) -> dict:
    from .node_health import _load
    return await _load(db, CONFIG_KEY, DEFAULT)


def region_for(cfg: dict, country: str | None) -> dict | None:
    if not cfg.get("enabled") or not country:
        return None
    cc = country.upper()
    return next((r for r in cfg.get("regions") or [] if cc in (r.get("countries") or [])), None)


def price_for(region: dict | None, plan_id: int, base: Decimal) -> Decimal:
    base = Decimal(str(base))
    if not region:
        return base
    exact = (region.get("plan_prices") or {}).get(str(plan_id))
    if exact is not None:
        return Decimal(str(exact)).quantize(Decimal("0.01"))
    pct = Decimal(int(region.get("percent") or 0))
    return max(Decimal("1.00"), (base * (Decimal(100) + pct) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


async def _own_addresses() -> set[str]:
    try:
        from .node_health import node_snapshot
        return {str(n.get("address") or "") for n in (await node_snapshot()).get("nodes") or [] if n.get("address")}
    except Exception:  # noqa: BLE001
        return set()


async def country_of(request: Request | None, db: AsyncSession) -> str | None:
    if request is None:
        return None
    cf = str(request.headers.get("cf-ipcountry") or "").upper()
    if len(cf) == 2 and cf.isalpha() and cf not in {"XX", "T1"}:
        return cf
    from . import main as shop
    try:
        ip = shop._client_ip(request)
    except Exception:  # noqa: BLE001
        return None
    if not ip or ip in await _own_addresses():
        return None
    from .vpn_sessions import _geo
    try:
        _, _, cc = await _geo(db, ip, [1])
    except Exception as exc:  # noqa: BLE001 — no country means the base price
        logger.debug("Country lookup failed: %s", exc)
        return None
    return cc.upper() or None


async def for_request(request: Request | None, db: AsyncSession) -> tuple[dict | None, str | None]:
    cfg = await load(db)
    if not cfg.get("enabled"):
        return None, None
    country = await country_of(request, db)
    return region_for(cfg, country), country


def order_providers(region: dict | None, providers: list[str]) -> list[str]:
    """The region's gateways first (in its order), then the rest of the queue as it was."""
    if not region or not region.get("providers"):
        return providers
    first = [p for p in region["providers"] if p in providers]
    return first + [p for p in providers if p not in first]


@router.get("/api/admin/pricing/regions")
async def get_regions(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    return await load(db)


@router.put("/api/admin/pricing/regions")
async def put_regions(body: PricingIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_plans"))):
    from . import main as shop
    from .node_health import _save
    data = body.model_dump(mode="json")
    await _save(db, CONFIG_KEY, data)
    await shop.audit(db, "pricing.regions.updated", admin.email, None, data)
    await db.commit()
    return data


@router.get("/api/admin/pricing/regions/preview")
async def preview(country: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    """What a customer from ``country`` sees: the region and the price of every plan."""
    from sqlalchemy import select
    from .models import Plan
    cfg = await load(db)
    region = region_for({**cfg, "enabled": True}, country)
    plans = (await db.execute(select(Plan).where(Plan.enabled.is_(True)).order_by(Plan.id))).scalars().all()
    return {"country": country.upper(), "region": region["name"] if region else None, "enabled": cfg.get("enabled"),
            "plans": [{"id": p.id, "name": p.name, "base": str(p.price), "price": str(price_for(region, p.id, p.price))} for p in plans],
            "providers_first": (region or {}).get("providers") or []}


@router.get("/api/me/region")
async def my_region(request: Request, db: AsyncSession = Depends(get_db)):
    region, country = await for_request(request, db)
    return {"country": country, "region": region["name"] if region else None}
