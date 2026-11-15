"""v28.73 (stage 14) «Юридические документы»: the offer, the privacy policy and the terms of use from the drafts in
``legal_texts.py`` with the seller's details.

* ``legal.seller`` keeps the seller details: legal form (self-employed, sole proprietor, company), name, INN, OGRN
  or OGRNIP, address, e-mail, site, the number in the Roskomnadzor register of personal data operators. Empty fields
  start from the corporate invoice details (``corporate.seller``) so nothing is typed twice.
* «Заполнить документы» writes the three pages into «Документы» (``info_pages``) on ru/en/uk **switched off**: the
  owner reads them, has a lawyer check them and switches each page on. A page already edited by hand is kept unless
  «Перезаписать» is chosen.
* Missing required details are listed and the texts keep a visible «[укажите …]» instead of an invented value.

Admin: «Контент → Документы → Юридические документы» and the mobile card. API: ``GET/PUT /api/admin/legal``,
``POST /api/admin/legal/apply``.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .legal_texts import NOTE_RU, NOTE_TR, TEMPLATES
from .security import require_permission

router = APIRouter()
KEY = "legal.seller"
FORMS = {"self_employed": "самозанятый (налог на профессиональный доход)", "ip": "индивидуальный предприниматель", "company": "юридическое лицо"}
DEFAULT = {"form": "self_employed", "name": "", "inn": "", "ogrn": "", "address": "", "email": "", "site": "", "rkn_number": "",
           "receipts": True}
REQUIRED = {"name": "ФИО или название", "inn": "ИНН", "email": "e-mail для обращений", "site": "адрес сайта или кабинета"}
KINDS = ("offer", "privacy", "rules")


class SellerIn(BaseModel):
    form: str = Field("self_employed", pattern=r"^(self_employed|ip|company)$")
    name: str = Field("", max_length=255)
    inn: str = Field("", max_length=12, pattern=r"^(\d{10}|\d{12})?$")
    ogrn: str = Field("", max_length=15, pattern=r"^(\d{13}|\d{15})?$")
    address: str = Field("", max_length=500)
    email: str = Field("", max_length=255)
    site: str = Field("", max_length=255)
    rkn_number: str = Field("", max_length=40)
    receipts: bool = True


class ApplyIn(BaseModel):
    kinds: list[str] = Field(default_factory=lambda: list(KINDS))
    overwrite: bool = False


async def load(db: AsyncSession) -> dict:
    from .corporate import SELLER_DEFAULT, SELLER_KEY
    from .node_health import _load
    seller = {**DEFAULT, **(await _load(db, KEY, DEFAULT) or {})}
    corp = await _load(db, SELLER_KEY, SELLER_DEFAULT)
    for ours, theirs in (("name", "name"), ("inn", "inn"), ("address", "address")):
        if not seller.get(ours) and corp.get(theirs):
            seller[ours] = corp[theirs]
    return seller


def missing(seller: dict) -> list[str]:
    out = [label for key, label in REQUIRED.items() if not str(seller.get(key) or "").strip()]
    if seller.get("form") in ("ip", "company") and not seller.get("ogrn"):
        out.append("ОГРН" if seller.get("form") == "company" else "ОГРНИП")
    return out


def _v(seller: dict, key: str, label: str) -> str:
    return str(seller.get(key) or "").strip() or f"[укажите {label}]"


def values(seller: dict, brand: str, lang: str, today: date | None = None) -> dict:
    today = today or date.today()
    name = _v(seller, "name", "ФИО или название")
    form = seller.get("form") or "self_employed"
    if form == "self_employed":
        genitive = f"самозанятого {name}, плательщика налога на профессиональный доход"
        nominative = f"{name} (самозанятый)"
        receipt = "или через приложение «Мой налог» (чек самозанятого)"
    elif form == "ip":
        genitive = f"индивидуального предпринимателя {name}"
        nominative = f"индивидуальный предприниматель {name}"
        receipt = "через онлайн-кассу Исполнителя"
    else:
        genitive = name
        nominative = name
        receipt = "через онлайн-кассу Исполнителя"
    if lang != "ru":
        genitive = nominative = name + {"self_employed": " (self-employed)" if lang == "en" else " (самозайнятий)",
                                        "ip": " (sole proprietor)" if lang == "en" else " (ФОП)", "company": ""}[form]
        receipt = {"self_employed": "through the «Мой налог» app" if lang == "en" else "через застосунок «Мой налог»",
                   "ip": "through the Provider's online cash register" if lang == "en" else "через онлайн-касу Виконавця",
                   "company": "through the Provider's online cash register" if lang == "en" else "через онлайн-касу Виконавця"}[form]
    if not seller.get("receipts", True):
        receipt = {"ru": "по требованию Пользователя", "en": "on the User's request", "uk": "на вимогу Користувача"}[lang]
    lines = [f"- {FORMS[form].capitalize()}: {name}" if lang == "ru" else f"- {name}",
             f"- ИНН: {_v(seller, 'inn', 'ИНН')}" if lang == "ru" else f"- INN: {_v(seller, 'inn', 'ИНН')}"]
    if form in ("ip", "company"):
        lines.append(f"- {'ОГРН' if form == 'company' else 'ОГРНИП'}: {_v(seller, 'ogrn', 'ОГРН')}")
    if seller.get("address"):
        lines.append(("- Адрес: " if lang == "ru" else "- Address: " if lang == "en" else "- Адреса: ") + seller["address"])
    lines.append(f"- E-mail: {_v(seller, 'email', 'e-mail')}")
    lines.append(("- Сайт: " if lang == "ru" else "- Site: " if lang == "en" else "- Сайт: ") + _v(seller, "site", "адрес сайта"))
    rkn = seller.get("rkn_number") or ""
    rkn_line = {"ru": f", регистрационный номер в реестре операторов персональных данных Роскомнадзора {rkn}",
                "en": f", Roskomnadzor register of personal data operators No. {rkn}",
                "uk": f", реєстраційний номер у реєстрі операторів персональних даних Роскомнадзору {rkn}"}[lang] if rkn else ""
    return {"brand": brand, "site": _v(seller, "site", "адрес сайта"), "email": _v(seller, "email", "e-mail"),
            "seller_genitive": genitive, "seller_nominative": nominative, "receipt_line": receipt, "rkn_line": rkn_line,
            "requisites": "\n".join(lines), "session_days": 30, "date": today.strftime("%d.%m.%Y")}


def render(kind: str, lang: str, seller: dict, brand: str, session_days: int = 30, today: date | None = None) -> str:
    v = values(seller, brand, lang, today)
    v["session_days"] = session_days
    body = TEMPLATES[lang][kind].format(**v)
    note = NOTE_RU.format(**v) if lang == "ru" else NOTE_TR[lang].format(**v)
    return f"**{note}**\n\n{body}"


async def _brand(db: AsyncSession) -> str:
    from .models import AppSetting
    row = await db.get(AppSetting, "app_name")
    return (row.value if row and row.value else "") or "Корги Люси"


async def _session_days(db: AsyncSession) -> int:
    from .node_health import _load
    from .vpn_sessions import CONFIG_KEY, DEFAULT as SESSIONS
    cfg = await _load(db, CONFIG_KEY, SESSIONS)
    return max(7, int(cfg.get("keep_days") or 30))


@router.get("/api/admin/legal")
async def get_legal(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    from .info_pages import load as load_page
    seller = await load(db)
    pages = {k: await load_page(db, k) for k in KINDS}
    return {"seller": seller, "forms": FORMS, "missing": missing(seller),
            "pages": {k: {"exists": bool(p and (p.get("ru") or {}).get("body")), "enabled": bool(p and p.get("enabled", True)),
                          "generated": bool(p and p.get("generated"))} for k, p in pages.items()},
            "preview": {k: render(k, "ru", seller, await _brand(db), await _session_days(db)) for k in KINDS},
            "disclaimer": "Это проект документов по законодательству РФ, подготовленный автоматически. Перед публикацией его проверяет юрист."}


@router.put("/api/admin/legal")
async def put_legal(payload: SellerIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("legal.write"))):
    from .main import audit
    from .node_health import _save
    await _save(db, KEY, payload.model_dump())
    await audit(db, "legal.seller", admin.email, None, {"form": payload.form, "fields": [k for k, v in payload.model_dump().items() if v]})
    await db.commit()
    seller = await load(db)
    return {"seller": seller, "missing": missing(seller)}


@router.post("/api/admin/legal/apply")
async def apply_legal(payload: ApplyIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("legal.write"))):
    """Write the drafts into «Документы» switched off; the owner switches each page on after reading it."""
    import json
    from datetime import datetime
    from .info_pages import PREFIX, load as load_page
    from .main import audit
    from .models import AppSetting
    kinds = [k for k in payload.kinds if k in KINDS]
    if not kinds:
        raise HTTPException(400, "Выберите документы")
    seller, brand, days = await load(db), await _brand(db), await _session_days(db)
    written, kept = [], []
    for kind in kinds:
        current = await load_page(db, kind)
        if current and (current.get("ru") or {}).get("body") and not current.get("generated") and not payload.overwrite:
            kept.append(kind)
            continue
        value = {"enabled": False, "generated": True, "version": int((current or {}).get("version", 0)) + 1,
                 "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
                 **{lang: {"title": "", "body": render(kind, lang, seller, brand, days), "items": []} for lang in ("ru", "en", "uk")}}
        row = await db.get(AppSetting, PREFIX + kind)
        if row:
            row.value = json.dumps(value, ensure_ascii=False)
        else:
            db.add(AppSetting(key=PREFIX + kind, value=json.dumps(value, ensure_ascii=False)))
        written.append(kind)
    await audit(db, "legal.apply", admin.email, None, {"written": written, "kept": kept})
    await db.commit()
    return {"written": written, "kept": kept, "missing": missing(seller),
            "next": "Документы записаны выключенными. Прочитайте их, дайте проверить юристу и включите в «Документы»."}
