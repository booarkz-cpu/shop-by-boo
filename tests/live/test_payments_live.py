"""Acceptance of the extra gateways against their real APIs (workflow «Payments acceptance»).

For every gateway whose keys are in the environment (GitHub secrets with the same names as in ``.env``; test-mode
keys where the gateway has them): the probe passes, a payment page is created for a small amount, the payment is read
back and is **not** paid. Nobody pays, so no money moves; an unpaid page expires on the gateway's side. A gateway
without keys is skipped. The money path itself (pay → notification → delivery) needs a person with a test card:
docs/ru/PAYMENTS_LIVE_CHECKLIST.md."""
import os
from datetime import datetime
from decimal import Decimal

import pytest

from app.gateways import GATEWAYS

AMOUNT = Decimal(os.environ.get("ACCEPTANCE_AMOUNT", "10"))


def _summary(name: str, text: str, ok: bool) -> None:
    print(f"::{'notice' if ok else 'error'} title={name}::{text}")


@pytest.mark.parametrize("name", sorted(GATEWAYS))
@pytest.mark.asyncio
async def test_gateway_accepts_keys_creates_a_page_and_reads_it_back(name):
    g = GATEWAYS[name]
    if not g.configured():
        pytest.skip(f"{g.title}: no keys ({', '.join(g.missing_keys())})")
    provider = g.cls()
    error = await provider.probe()
    if error:
        _summary(g.title, f"проба: {error}", False)
    assert not error, f"{g.title}: probe — {error}"
    order_id = f"acc-{name}-{datetime.utcnow():%Y%m%d%H%M%S}"
    out = await provider.create(AMOUNT, order_id, "Проверка приёмки", os.environ.get("ACCEPTANCE_RETURN_URL", "https://example.com/paid"))
    assert out.get("id") and str(out.get("url") or "").startswith("https://"), f"{g.title}: no payment page — {out}"
    paid = await provider.verify_succeeded(out["id"], AMOUNT, os.environ.get("DEFAULT_CURRENCY", "RUB"), order_id)
    assert paid is False, f"{g.title}: an unpaid page reads as paid"
    _summary(g.title, f"ключи приняты, страница оплаты создана ({out['url'][:60]}…), статус «не оплачен» читается", True)
