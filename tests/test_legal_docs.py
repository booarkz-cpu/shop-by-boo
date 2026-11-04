"""v28.73 (stage 14): drafts of the offer, the privacy policy and the terms of use filled with the seller's details,
written into «Документы» switched off, never over a page edited by hand unless asked; nothing invented for empty
details."""
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import info_pages
from app import legal_docs as ld
from app.legal_texts import TEMPLATES
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@example.com", role="owner")
SELLER = dict(form="ip", name="Иванов Иван Иванович", inn="770123456789", ogrn="312774600000012", address="Москва, ул. Примерная, 1",
              email="support@corgi.example", site="https://corgi.example", rkn_number="77-23-012345", receipts=True)


def test_every_template_fills_without_leftover_placeholders():
    for lang in ("ru", "en", "uk"):
        for kind in ld.KINDS:
            text = ld.render(kind, lang, SELLER, "Корги Люси", 30, date(2026, 11, 4))
            assert "{" not in text and "}" not in text, (lang, kind)
            assert "support@corgi.example" in text, (lang, kind)
    offer = ld.render("offer", "ru", SELLER, "Корги Люси", 30, date(2026, 11, 4))
    assert "индивидуального предпринимателя Иванов Иван Иванович" in offer and "ОГРНИП: 312774600000012" in offer
    assert "ст. 32 Закона РФ «О защите прав потребителей»" in offer and "54-ФЗ" in offer and "04.11.2026" in offer
    privacy = ld.render("privacy", "ru", SELLER, "Корги Люси", 45, date(2026, 11, 4))
    assert "152-ФЗ" in privacy and "не дольше 45 дней" in privacy and "77-23-012345" in privacy
    assert "149-ФЗ" in ld.render("rules", "ru", SELLER, "Корги Люси")
    assert "Russian version prevails" in ld.render("offer", "en", SELLER, "Corgi Lucy")
    assert set(TEMPLATES) == {"ru", "en", "uk"} and all(set(v) == set(ld.KINDS) for v in TEMPLATES.values())


def test_empty_details_are_marked_not_invented():
    text = ld.render("offer", "ru", {**ld.DEFAULT}, "Корги Люси")
    assert "[укажите ФИО или название]" in text and "[укажите e-mail]" in text and "самозанятого" in text
    assert ld.missing(ld.DEFAULT) == ["ФИО или название", "ИНН", "e-mail для обращений", "адрес сайта или кабинета"]
    assert "ОГРН" in ld.missing({**SELLER, "form": "company", "ogrn": ""})
    with pytest.raises(ValidationError):
        ld.SellerIn(inn="12345")


@pytest.mark.asyncio
async def test_apply_writes_switched_off_pages_and_keeps_hand_edited_ones(database):  # noqa: F811
    db = database
    state = await ld.get_legal(db, ADMIN)
    assert state["missing"] and not state["pages"]["offer"]["exists"]
    await ld.put_legal(ld.SellerIn(**SELLER), db, ADMIN)
    # The privacy policy was already written by hand: it stays.
    await info_pages.admin_save("privacy", info_pages.PageIn(enabled=True, ru=info_pages.Translation(body="Своя политика")), db, ADMIN)
    result = await ld.apply_legal(ld.ApplyIn(), db, ADMIN)
    assert result["written"] == ["offer", "rules"] and result["kept"] == ["privacy"] and result["missing"] == []
    offer = await info_pages.load(db, "offer")
    assert offer["enabled"] is False and offer["generated"] and "Иванов" in offer["ru"]["body"] and offer["en"]["body"] and offer["uk"]["body"]
    assert info_pages.localized("offer", offer, "ru") is None  # switched off: not shown to customers yet
    assert (await info_pages.load(db, "privacy"))["ru"]["body"] == "Своя политика"
    again = await ld.apply_legal(ld.ApplyIn(kinds=["offer"]), db, ADMIN)  # a generated page is refreshed
    assert again["written"] == ["offer"] and (await info_pages.load(db, "offer"))["version"] == offer["version"] + 1
    forced = await ld.apply_legal(ld.ApplyIn(kinds=["privacy"], overwrite=True), db, ADMIN)
    assert forced["written"] == ["privacy"] and "152-ФЗ" in (await info_pages.load(db, "privacy"))["ru"]["body"]
    with pytest.raises(HTTPException):
        await ld.apply_legal(ld.ApplyIn(kinds=["faq"]), db, ADMIN)
    state = await ld.get_legal(db, ADMIN)
    assert state["pages"]["offer"] == {"exists": True, "enabled": False, "generated": True} and "Иванов" in state["preview"]["offer"]


@pytest.mark.asyncio
async def test_corporate_invoice_details_prefill_the_seller(database):  # noqa: F811
    from app.corporate import SELLER_KEY
    from app.node_health import _save
    db = database
    await _save(db, SELLER_KEY, {"name": "ООО «Корги»", "inn": "7701234567", "kpp": "", "address": "Москва", "bank": "", "bik": "",
                                 "account": "", "corr_account": ""})
    await db.commit()
    seller = await ld.load(db)
    assert seller["name"] == "ООО «Корги»" and seller["inn"] == "7701234567" and seller["address"] == "Москва"
