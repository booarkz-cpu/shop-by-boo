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


def _gb(value) -> str:
    try:
        return f"{int(value) / 1024 ** 3:.1f} ГБ"
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


CSS = """:root{--bg:#090D16;--card:#0F172A;--line:#1E293B;--text:#E2E8F0;--muted:#94A3B8;--accent:#3B82F6;--ok:#22C55E;--warn:#F59E0B;--bad:#EF4444}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 Inter,system-ui,sans-serif}
main{max-width:720px;margin:0 auto;padding:24px 16px 48px}header{display:flex;align-items:center;gap:12px;margin-bottom:20px}
header img{width:44px;height:44px;border-radius:12px}h1{font-size:22px;margin:0}h2{font-size:17px;margin:0 0 12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;margin-bottom:14px}
.status{display:inline-block;padding:2px 10px;border-radius:99px;font-weight:600}.on{background:#14532d;color:#bbf7d0}.off{background:#7f1d1d;color:#fecaca}
.muted{color:var(--muted)}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
input{flex:1;min-width:0;background:#020617;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:10px;font:13px ui-monospace,monospace}
button,a.btn{background:var(--accent);color:#fff;border:0;border-radius:10px;padding:10px 14px;font:inherit;font-weight:600;text-decoration:none;cursor:pointer}
a.ghost{background:transparent;border:1px solid var(--line);color:var(--text)}.qr{background:#fff;border-radius:12px;padding:8px;width:200px;margin:12px auto 0}
.qr svg{width:100%;height:auto;display:block}.apps{display:grid;gap:10px}.app{border:1px solid var(--line);border-radius:12px;padding:12px}
.notice{border-color:var(--warn)}ul{margin:0;padding-left:18px}footer{text-align:center;margin-top:24px}"""


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
    e = html.escape
    now = datetime.utcnow()
    active = bool(info.get("active"))
    days = (sub.expires_at - now).days if sub.expires_at else None
    cabinet = f"https://{settings.cabinet_domain}"
    support = portal.get("support_url") or cabinet
    parts = []
    if portal.get("notice"):
        parts.append(f"<section class='card notice'>{e(portal['notice'])}</section>")
    status = f"<span class='status {'on' if active else 'off'}'>{'Активна' if active else 'Не активна'}</span>"
    until = f"до {sub.expires_at:%d.%m.%Y %H:%M} UTC" if sub.expires_at else "срок не указан"
    warn = ""
    if active and days is not None and days < int(portal.get("expiry_warning_days") or 0):
        warn = f"<p class='muted'>Осталось {max(days, 0)} дн. — продлите в <a href='{e(cabinet)}'>личном кабинете</a>.</p>"
    if not active:
        warn = f"<p>Подписка закончилась или приостановлена. <a class='btn' href='{e(cabinet)}'>Продлить</a></p>"
    traffic = ""
    if portal.get("show_traffic") and "used" in facts:
        limit = "без лимита" if not facts.get("limit") else _gb(facts["limit"])
        traffic = f"<p>Трафик: {_gb(facts.get('used'))} из {limit}</p>"
    parts.append(f"<section class='card' data-portal-status><h2>{e(plan.name if plan else 'Подписка')}</h2>"
                 f"<div class='row'>{status}<span class='muted'>{e(until)}</span></div>{traffic}{warn}</section>")
    parts.append("<section class='card' data-portal-link><h2>Ссылка подписки</h2>"
                 f"<div class='row'><input id='sub-link' readonly value='{e(link)}' aria-label='Ссылка подписки'>"
                 "<button type='button' data-copy='sub-link'>Копировать</button></div>"
                 f"<div class='qr' role='img' aria-label='QR-код ссылки подписки'>{qr_svg(link)}</div>"
                 "<p class='muted'>Отсканируйте QR-код в приложении или добавьте подписку кнопкой ниже. Ссылка — ключ доступа: не пересылайте её.</p></section>")
    apps = []
    for app in portal.get("apps") or []:
        if not isinstance(app, dict) or not app.get("name"):
            continue
        deeplink = str(app.get("deeplink") or "")
        add = f"<a class='btn' href='{e(deeplink.replace('{url}', quote(link, safe='')))}'>Добавить в {e(app['name'])}</a>" if "{url}" in deeplink else ""
        get = f"<a class='btn ghost' href='{e(app['download'])}' rel='noopener'>Скачать</a>" if str(app.get("download") or "").startswith("https://") else ""
        apps.append(f"<div class='app'><b>{e(app['name'])}</b> <span class='muted'>{e(app.get('platforms') or '')}</span>"
                    f"<div class='row' style='margin-top:8px'>{add}{get}</div></div>")
    if apps:
        parts.append("<section class='card' data-portal-apps><h2>Как подключиться</h2>"
                     "<ol><li>Установите приложение.</li><li>Нажмите «Добавить» или отсканируйте QR-код.</li><li>Выберите сервер и подключитесь.</li></ol>"
                     f"<div class='apps'>{''.join(apps)}</div></section>")
    if portal.get("show_devices") and "devices" in facts:
        limit = facts.get("device_limit") or sub.device_limit_snapshot
        rows = "".join(f"<li>{e(d['platform'] or 'Устройство')} {e(d['model'])}</li>" for d in facts["devices"]) or "<li class='muted'>Устройств пока нет</li>"
        parts.append(f"<section class='card' data-portal-devices><h2>Устройства: {len(facts['devices'])}"
                     f"{' из ' + str(limit) if limit else ''}</h2><ul>{rows}</ul>"
                     f"<p class='muted'>Удалить устройство можно в <a href='{e(cabinet)}'>личном кабинете</a>.</p></section>")
    parts.append(f"<section class='card'><h2>Помощь</h2><div class='row'><a class='btn ghost' href='{e(support)}'>Поддержка</a>"
                 f"<a class='btn ghost' href='{e(cabinet)}'>Личный кабинет</a></div></section>")
    logo = f"<img src='{e(brand['logo_url'])}' alt=''>" if str(brand.get("logo_url") or "").startswith(("https://", "/")) else ""
    minimal = portal.get("template") == "minimal"
    body = (f"<main data-portal-template='{e(portal.get('template'))}'><header>{logo}<div><h1>{e(portal.get('title') or 'Подписка')}</h1>"
            f"<div class='muted'>{e(brand.get('name') or '')}</div></div></header>{''.join(p for p in parts if not minimal or any(k in p for k in MINIMAL))}"
            f"<footer class='muted'>{e(brand.get('name') or '')}</footer></main>")
    doc = (f"<!doctype html><html lang=ru><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<meta name=robots content='noindex,nofollow'><title>{e(portal.get('title') or 'Подписка')}</title>"
           f"<style>{CSS}</style><script src='/sub/-/portal.js' defer></script></head><body>{body}</body></html>")
    return HTMLResponse(doc, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                                      "X-Robots-Tag": "noindex, nofollow"})


PORTAL_JS = """document.addEventListener('click',function(e){var b=e.target.closest('[data-copy]');if(!b)return;
var i=document.getElementById(b.getAttribute('data-copy'));if(!i)return;i.select();
(navigator.clipboard?navigator.clipboard.writeText(i.value):Promise.reject()).catch(function(){document.execCommand('copy')})
.finally(function(){var t=b.textContent;b.textContent='Скопировано';setTimeout(function(){b.textContent=t},1500)});});"""


def asset(name: str) -> Response | None:
    if name == "portal.js":
        return Response(PORTAL_JS, media_type="text/javascript; charset=utf-8", headers={"Cache-Control": "public, max-age=3600"})
    return None
