"""Subscription Portal: the customer's page at the subscription link (v28.67, stage 11; docs/ru/new/SUBSCRIPTION_PORTAL.md).

The link a customer gets — ``https://<portal domain>/<shortUuid>`` (sub_proxy) — answers two kinds of callers:
* a VPN client gets the subscription (sub_proxy proxies it from the panel, as before);
* a browser gets this page: the shop's branding (Corgi Lucy), whether the subscription is active and until when,
  traffic, devices under the limit, the link to copy, a QR code, «add to app» buttons and instructions for the
  clients of the owner's catalogue, notices, support and renewal links.

The page is rendered by the server (no framework, no inline script: the copy button is ``/sub/-/portal.js`` under
``script-src 'self'``) and holds no personal data beyond what the link itself already grants: no email, phone,
payment history or raw HWID. A browser request to a link that does not exist gets the neutral page of sub_proxy.

Template ``corgi`` (default) or ``minimal``; ``panel`` passes browsers to the panel's own subscription page (what the
panel's response rules — SRR — allow). All texts and the client list are edited in «Серверы → Портал подписки»."""
from __future__ import annotations

import html
import io
import logging
import re
from datetime import datetime
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings

logger = logging.getLogger("vpnshop.sub_portal")
DEFAULT_APPS = [
    {"name": "Happ", "platforms": "iOS, Android, Windows, macOS", "deeplink": "happ://add/{url}", "download": ""},
    {"name": "v2RayTun", "platforms": "iOS, Android, Windows", "deeplink": "v2raytun://import/{url}", "download": ""},
    {"name": "Hiddify", "platforms": "Android, iOS, Windows, macOS, Linux", "deeplink": "hiddify://import/{url}",
     "download": "https://github.com/hiddify/hiddify-app/releases"},
    {"name": "v2rayNG", "platforms": "Android", "deeplink": "v2rayng://install-config?url={url}",
     "download": "https://github.com/2dust/v2rayNG/releases"},
    {"name": "Clash Verge", "platforms": "Windows, macOS, Linux", "deeplink": "clash://install-config?url={url}",
     "download": "https://github.com/clash-verge-rev/clash-verge-rev/releases"},
]
DEFAULT = {
    "enabled": True,
    "template": "corgi",          # corgi | minimal | panel
    "title": "Ваша подписка",
    "notice": "",                 # a line at the top for every customer (works, maintenance…)
    "support_url": "",            # empty: the cabinet
    "show_traffic": True,
    "show_devices": True,
    "expiry_warning_days": 3,
    "apps": DEFAULT_APPS,
    "language": "ru",             # when the browser asks for none of ru / en / uk
    "texts": {},                  # {"ru": {"copy": "…"}, "en": {…}} — overrides of TEXTS
    "colors": {},                 # {"accent": "#…"} — overrides of COLORS
}
MINIMAL = ("card notice", "data-portal-status", "data-portal-link")
BROWSERS = ("mozilla", "chrome", "safari", "firefox", "edg/", "opera")


def settings_of(cfg: dict) -> dict:
    portal = cfg.get("portal") if isinstance(cfg.get("portal"), dict) else {}
    return {**DEFAULT, **portal}


def is_browser(request: Request, app: str) -> bool:
    """A person in a browser, not a VPN client: the client catalogue did not recognise the app, the User-Agent is a
    browser's and HTML is accepted. VPN clients send their own User-Agent and do not ask for text/html."""
    ua = request.headers.get("user-agent", "").lower()
    accept = request.headers.get("accept", "").lower()
    return app in ("", "Браузер") and any(b in ua for b in BROWSERS) and "text/html" in accept


def qr_svg(text: str) -> str:
    import qrcode
    import qrcode.image.svg
    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    image.save(buf)
    svg = buf.getvalue().decode()
    return svg[svg.index("<svg"):]


def _gb(value, unit: str = "ГБ") -> str:
    try:
        return f"{int(value) / 1024 ** 3:.1f} {unit}"
    except (TypeError, ValueError):
        return "—"


async def _panel_facts(sub) -> dict:
    """Traffic and devices from the panel; the page still renders without them."""
    out: dict = {}
    try:
        user_id = int(str(sub.remnawave_user_id))
    except (TypeError, ValueError):
        return out
    from .remnawave import RemnawaveClient
    try:
        panel = RemnawaveClient()
        user = await panel.get_user(user_id)
        out["used"] = user.get("usedTrafficBytes") or (user.get("userTraffic") or {}).get("usedTrafficBytes")
        out["limit"] = user.get("trafficLimitBytes")
        out["device_limit"] = user.get("hwidDeviceLimit")
        out["devices"] = [{"platform": d.get("platform") or "", "model": d.get("deviceModel") or "", "seen": d.get("updatedAt") or ""}
                          for d in await panel.hwid_devices(user_id)][:20]
    except Exception as exc:  # noqa: BLE001 — the portal never fails because the panel is slow
        logger.info("Portal: panel facts unavailable: %s", exc)
    return out


LANGS = ("ru", "en", "uk")
# Every text of the page, per language. The owner overrides any of them in «Портал подписки → Тексты»; placeholders
# in braces are filled by the server and are the only ones allowed (sub_proxy.PortalIn checks it).
TEXTS: dict[str, dict[str, str]] = {
    "ru": {"active": "Активна", "inactive": "Не активна", "until": "до {date} UTC", "no_expiry": "срок не указан",
           "plan_fallback": "Подписка", "traffic": "Трафик: {used} из {limit}", "unlimited": "без лимита",
           "days_left": "Осталось {days} дн. — продлите в личном кабинете.", "expired": "Подписка закончилась или приостановлена.",
           "renew": "Продлить", "link_title": "Ссылка подписки", "copy": "Копировать", "copied": "Скопировано",
           "link_hint": "Отсканируйте QR-код в приложении или добавьте подписку кнопкой ниже. Ссылка — ключ доступа: не пересылайте её.",
           "apps_title": "Как подключиться", "step1": "Установите приложение.", "step2": "Нажмите «Добавить» или отсканируйте QR-код.",
           "step3": "Выберите сервер и подключитесь.", "add_to": "Добавить в {app}", "download": "Скачать",
           "devices_title": "Устройства: {count}", "devices_of": " из {max}", "no_devices": "Устройств пока нет",
           "device_fallback": "Устройство", "devices_hint": "Удалить устройство можно в личном кабинете.",
           "help_title": "Помощь", "support": "Поддержка", "cabinet": "Личный кабинет", "footer": "", "gb": "ГБ"},
    "en": {"active": "Active", "inactive": "Inactive", "until": "until {date} UTC", "no_expiry": "no end date",
           "plan_fallback": "Subscription", "traffic": "Traffic: {used} of {limit}", "unlimited": "unlimited",
           "days_left": "{days} days left — renew in your account.", "expired": "The subscription has ended or is paused.",
           "renew": "Renew", "link_title": "Subscription link", "copy": "Copy", "copied": "Copied",
           "link_hint": "Scan the QR code in the app or add the subscription with a button below. The link is your access key: do not share it.",
           "apps_title": "How to connect", "step1": "Install the app.", "step2": "Tap «Add» or scan the QR code.",
           "step3": "Choose a server and connect.", "add_to": "Add to {app}", "download": "Download",
           "devices_title": "Devices: {count}", "devices_of": " of {max}", "no_devices": "No devices yet",
           "device_fallback": "Device", "devices_hint": "Remove a device in your account.",
           "help_title": "Help", "support": "Support", "cabinet": "My account", "footer": "", "gb": "GB"},
    "uk": {"active": "Активна", "inactive": "Неактивна", "until": "до {date} UTC", "no_expiry": "термін не вказано",
           "plan_fallback": "Підписка", "traffic": "Трафік: {used} з {limit}", "unlimited": "без ліміту",
           "days_left": "Залишилось {days} дн. — продовжте в особистому кабінеті.", "expired": "Підписка закінчилась або призупинена.",
           "renew": "Продовжити", "link_title": "Посилання підписки", "copy": "Копіювати", "copied": "Скопійовано",
           "link_hint": "Відскануйте QR-код у застосунку або додайте підписку кнопкою нижче. Посилання — ключ доступу: не пересилайте його.",
           "apps_title": "Як підключитися", "step1": "Встановіть застосунок.", "step2": "Натисніть «Додати» або відскануйте QR-код.",
           "step3": "Оберіть сервер і підключіться.", "add_to": "Додати в {app}", "download": "Завантажити",
           "devices_title": "Пристрої: {count}", "devices_of": " з {max}", "no_devices": "Пристроїв поки немає",
           "device_fallback": "Пристрій", "devices_hint": "Видалити пристрій можна в особистому кабінеті.",
           "help_title": "Допомога", "support": "Підтримка", "cabinet": "Особистий кабінет", "footer": "", "gb": "ГБ"},
}
PLACEHOLDERS = {"until": {"date"}, "traffic": {"used", "limit"}, "days_left": {"days"}, "add_to": {"app"},
                "devices_title": {"count"}, "devices_of": {"max"}}
COLORS = {"bg": "#090D16", "card": "#0F172A", "line": "#1E293B", "text": "#E2E8F0", "muted": "#94A3B8", "accent": "#3B82F6"}
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def language(request: Request | None, portal: dict) -> str:
    """ru, en or uk from Accept-Language (the first supported one), else the portal's default language."""
    header = (request.headers.get("accept-language", "") if request else "").lower()
    for part in header.split(","):
        code = part.split(";")[0].strip()[:2]
        if code in LANGS:
            return code
    return portal.get("language") if portal.get("language") in LANGS else "ru"


def texts_for(portal: dict, lang: str) -> dict[str, str]:
    own = (portal.get("texts") or {}).get(lang) or {}
    return {**TEXTS[lang], **{k: v for k, v in own.items() if k in TEXTS[lang] and isinstance(v, str)}}


def fill(text: str, **values) -> str:
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def css(portal: dict) -> str:
    colors = {**COLORS, **{k: v for k, v in (portal.get("colors") or {}).items() if k in COLORS and HEX.match(str(v))}}
    return (":root{" + "".join(f"--{k}:{v};" for k, v in colors.items()) + "--warn:#F59E0B}" + CSS_BODY)


CSS_BODY = """*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 Inter,system-ui,sans-serif}
main{max-width:720px;margin:0 auto;padding:24px 16px 48px}header{display:flex;align-items:center;gap:12px;margin-bottom:20px}
header img{width:44px;height:44px;border-radius:12px}h1{font-size:22px;margin:0}h2{font-size:17px;margin:0 0 12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;margin-bottom:14px}
.status{display:inline-block;padding:2px 10px;border-radius:99px;font-weight:600}.on{background:#14532d;color:#bbf7d0}.off{background:#7f1d1d;color:#fecaca}
.muted{color:var(--muted)}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}a{color:var(--accent)}
input{flex:1;min-width:0;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:10px;font:13px ui-monospace,monospace}
button,a.btn{background:var(--accent);color:#fff;border:0;border-radius:10px;padding:10px 14px;font:inherit;font-weight:600;text-decoration:none;cursor:pointer}
a.ghost{background:transparent;border:1px solid var(--line);color:var(--text)}.qr{background:#fff;border-radius:12px;padding:8px;width:200px;margin:12px auto 0}
.qr svg{width:100%;height:auto;display:block}.apps{display:grid;gap:10px}.app{border:1px solid var(--line);border-radius:12px;padding:12px}
.notice{border-color:var(--warn)}ul{margin:0;padding-left:18px}footer{text-align:center;margin-top:24px}"""


def render(portal: dict, brand: dict, view: dict, lang: str) -> str:
    """The page from settings and facts. ``view``: plan, active, expires_at, days, link, traffic (used, limit) or None,
    devices (list) or None, device_limit, cabinet, support. Every text comes from ``texts_for``; everything is escaped."""
    t = texts_for(portal, lang)
    e = html.escape
    cabinet, support, link = view["cabinet"], view["support"], view["link"]
    parts = []
    if portal.get("notice"):
        parts.append(f"<section class='card notice'>{e(portal['notice'])}</section>")
    active = view["active"]
    status = f"<span class='status {'on' if active else 'off'}'>{e(t['active'] if active else t['inactive'])}</span>"
    until = fill(t["until"], date=f"{view['expires_at']:%d.%m.%Y %H:%M}") if view.get("expires_at") else t["no_expiry"]
    warn = ""
    days = view.get("days")
    if active and days is not None and days < int(portal.get("expiry_warning_days") or 0):
        warn = f"<p class='muted'><a href='{e(cabinet)}'>{e(fill(t['days_left'], days=max(days, 0)))}</a></p>"
    if not active:
        warn = f"<p>{e(t['expired'])} <a class='btn' href='{e(cabinet)}'>{e(t['renew'])}</a></p>"
    traffic = ""
    if portal.get("show_traffic") and view.get("traffic") is not None:
        used, limit = view["traffic"]
        traffic = f"<p>{e(fill(t['traffic'], used=_gb(used, t['gb']), limit=t['unlimited'] if not limit else _gb(limit, t['gb'])))}</p>"
    parts.append(f"<section class='card' data-portal-status><h2>{e(view.get('plan') or t['plan_fallback'])}</h2>"
                 f"<div class='row'>{status}<span class='muted'>{e(until)}</span></div>{traffic}{warn}</section>")
    parts.append(f"<section class='card' data-portal-link><h2>{e(t['link_title'])}</h2>"
                 f"<div class='row'><input id='sub-link' readonly value='{e(link)}' aria-label='{e(t['link_title'])}'>"
                 f"<button type='button' data-copy='sub-link' data-copied='{e(t['copied'])}'>{e(t['copy'])}</button></div>"
                 f"<div class='qr' role='img' aria-label='QR'>{qr_svg(link)}</div><p class='muted'>{e(t['link_hint'])}</p></section>")
    apps = []
    for app in portal.get("apps") or []:
        if not isinstance(app, dict) or not app.get("name"):
            continue
        deeplink = str(app.get("deeplink") or "")
        add = (f"<a class='btn' href='{e(deeplink.replace('{url}', quote(link, safe='')))}'>{e(fill(t['add_to'], app=app['name']))}</a>"
               if "{url}" in deeplink else "")
        get = f"<a class='btn ghost' href='{e(app['download'])}' rel='noopener'>{e(t['download'])}</a>" if str(app.get("download") or "").startswith("https://") else ""
        apps.append(f"<div class='app'><b>{e(app['name'])}</b> <span class='muted'>{e(app.get('platforms') or '')}</span>"
                    f"<div class='row' style='margin-top:8px'>{add}{get}</div></div>")
    if apps:
        steps = "".join(f"<li>{e(t[k])}</li>" for k in ("step1", "step2", "step3") if t[k])
        parts.append(f"<section class='card' data-portal-apps><h2>{e(t['apps_title'])}</h2><ol>{steps}</ol>"
                     f"<div class='apps'>{''.join(apps)}</div></section>")
    if portal.get("show_devices") and view.get("devices") is not None:
        limit = view.get("device_limit")
        rows = "".join(f"<li>{e(d['platform'] or t['device_fallback'])} {e(d['model'])}</li>" for d in view["devices"]) \
            or f"<li class='muted'>{e(t['no_devices'])}</li>"
        title = fill(t["devices_title"], count=len(view["devices"])) + (fill(t["devices_of"], max=limit) if limit else "")
        parts.append(f"<section class='card' data-portal-devices><h2>{e(title)}</h2><ul>{rows}</ul>"
                     f"<p class='muted'><a href='{e(cabinet)}'>{e(t['devices_hint'])}</a></p></section>")
    parts.append(f"<section class='card'><h2>{e(t['help_title'])}</h2><div class='row'><a class='btn ghost' href='{e(support)}'>{e(t['support'])}</a>"
                 f"<a class='btn ghost' href='{e(cabinet)}'>{e(t['cabinet'])}</a></div></section>")
    logo = f"<img src='{e(brand['logo_url'])}' alt=''>" if str(brand.get("logo_url") or "").startswith(("https://", "/")) else ""
    minimal = portal.get("template") == "minimal"
    title = portal.get("title") or t["plan_fallback"]
    footer = t["footer"] or brand.get("name") or ""
    body = (f"<main data-portal-template='{e(portal.get('template'))}'><header>{logo}<div><h1>{e(title)}</h1>"
            f"<div class='muted'>{e(brand.get('name') or '')}</div></div></header>{''.join(p for p in parts if not minimal or any(k in p for k in MINIMAL))}"
            f"<footer class='muted'>{e(footer)}</footer></main>")
    return (f"<!doctype html><html lang={lang}><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<meta name=robots content='noindex,nofollow'><title>{e(title)}</title>"
            f"<style>{css(portal)}</style><script src='/sub/-/portal.js' defer></script></head><body>{body}</body></html>")


async def page(request: Request, db: AsyncSession, cfg: dict, short: str, info: dict | None, link: str) -> Response | None:
    """The portal for a browser, or None to fall back to the proxy (template «panel», portal off)."""
    portal = settings_of(cfg)
    if not portal.get("enabled") or portal.get("template") == "panel":
        return None
    from .models import Plan, Subscription
    from .content_branding_api import public_branding
    sub = await db.get(Subscription, info["subscription_id"]) if info else None
    if not sub:
        return None
    plan = await db.get(Plan, sub.plan_id) if sub.plan_id else None
    brand = await public_branding(db)
    facts = await _panel_facts(sub) if (portal.get("show_traffic") or portal.get("show_devices")) else {}
    now = datetime.utcnow()
    cabinet = f"https://{settings.cabinet_domain}"
    view = {"plan": plan.name if plan else "", "active": bool(info.get("active")), "expires_at": sub.expires_at,
            "days": (sub.expires_at - now).days if sub.expires_at else None, "link": link,
            "traffic": (facts.get("used"), facts.get("limit")) if "used" in facts else None,
            "devices": facts.get("devices"), "device_limit": facts.get("device_limit") or sub.device_limit_snapshot,
            "cabinet": cabinet, "support": portal.get("support_url") or cabinet}
    doc = render(portal, brand, view, language(request, portal))
    return HTMLResponse(doc, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                                      "X-Robots-Tag": "noindex, nofollow", "Content-Language": language(request, portal)})


def preview(portal: dict, brand: dict, lang: str) -> str:
    """The page with sample facts, for «Портал подписки → Предпросмотр» (no customer data)."""
    from datetime import timedelta
    cabinet = f"https://{settings.cabinet_domain}"
    view = {"plan": "Lucy Max", "active": True, "expires_at": datetime.utcnow() + timedelta(days=2), "days": 2,
            "link": "https://sub.example.com/AbCdEfGh12345678", "traffic": (12 * 1024 ** 3, 0),
            "devices": [{"platform": "iOS", "model": "iPhone 16"}, {"platform": "Android", "model": "Pixel 9"}],
            "device_limit": 2, "cabinet": cabinet, "support": portal.get("support_url") or cabinet}
    return render({**portal, "enabled": True}, brand, view, lang)


PORTAL_JS = """document.addEventListener('click',function(e){var b=e.target.closest('[data-copy]');if(!b)return;
var i=document.getElementById(b.getAttribute('data-copy'));if(!i)return;i.select();
(navigator.clipboard?navigator.clipboard.writeText(i.value):Promise.reject()).catch(function(){document.execCommand('copy')})
.finally(function(){var t=b.textContent;b.textContent=b.getAttribute('data-copied')||t;setTimeout(function(){b.textContent=t},1500)});});"""


def asset(name: str) -> Response | None:
    if name == "portal.js":
        return Response(PORTAL_JS, media_type="text/javascript; charset=utf-8", headers={"Cache-Control": "public, max-age=3600"})
    return None
