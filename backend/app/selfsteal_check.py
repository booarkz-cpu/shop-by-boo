"""«Проверка снаружи» of a SelfSteal site (v28.91.0, stage 20, N8): what a stranger — or a censor's scanner — sees.

The shop's server asks the node directly: every request goes to the node's own address from the server registry with
the node's domain as SNI and Host — no other address is ever contacted (no SSRF through the domain or the links of the
page: inner pages and the sitemap are read only when they are on the same domain, from the same address).

Eleven points, each «ok» or a remark with what was seen:
 1. dns       the domain points to the node's address;
 2. https     the site opens over HTTPS (code, time);
 3. title     the page has its own <title> (not a default page of a web server);
 4. cert      the certificate is a real one for the domain (issuer, name, days left);
 5. redirect  http:// answers 301 to https://;
 6. notfound  a missing address answers 404 with a page of the site;
 7. headers   no Server / X-Powered-By that name the software;
 8. hsts      Strict-Transport-Security;
 9. robots    /robots.txt;
10. sitemap   the sitemap named in robots.txt;
11. pages     the site has inner pages (not a single page).
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import secrets
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

TITLE = re.compile(r"<title[^>]*>\s*([^<]*?)\s*</title>", re.I)
HREF = re.compile(r"""href\s*=\s*["']([^"'#?]+)""", re.I)
DEFAULT_TITLES = ("welcome to nginx", "apache2", "it works", "caddy", "index of", "test page", "default page", "403 forbidden",
                  "404 not found", "502 bad gateway")
POINTS = ("dns", "https", "title", "cert", "redirect", "notfound", "headers", "hsts", "robots", "sitemap", "pages")


@dataclass
class Answer:
    status: int
    headers: dict[str, str]
    body: bytes
    ms: int


@dataclass
class Report:
    domain: str
    address: str
    checked_at: str
    points: list[dict] = field(default_factory=list)

    @property
    def remarks(self) -> int:
        return sum(1 for p in self.points if not p["ok"])

    def add(self, key: str, ok: bool, text: str) -> None:
        self.points.append({"key": key, "ok": ok, "text": text})

    def as_dict(self) -> dict:
        return {"domain": self.domain, "address": self.address, "checked_at": self.checked_at, "points": self.points,
                "remarks": self.remarks, "summary": "в порядке" if not self.remarks else f"есть замечания ({self.remarks})"}


# ---------------------------------------------------------------- the network (seams: tests replace these)

async def resolve(domain: str) -> set[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(domain, 443, type=socket.SOCK_STREAM)
    return {info[4][0] for info in infos}


async def fetch(address: str, domain: str, scheme: str, path: str) -> Answer:
    """One GET to ``address`` for ``domain`` (SNI and Host); no redirects are followed."""
    import httpx
    port = 443 if scheme == "https" else 80
    host = f"[{address}]" if ":" in address else address
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, verify=False, trust_env=False) as client:
        response = await client.get(f"{scheme}://{host}:{port}{path}", headers={"Host": domain, "User-Agent": "Mozilla/5.0"},
                                    extensions={"sni_hostname": domain} if scheme == "https" else {})
        body = response.content[:500_000]
    return Answer(response.status_code, {k.lower(): v for k, v in response.headers.items()}, body, int((time.monotonic() - started) * 1000))


def _certificate(address: str, domain: str) -> dict:
    context = ssl.create_default_context()
    with socket.create_connection((address, 443), timeout=10) as raw, context.wrap_socket(raw, server_hostname=domain) as tls:
        return tls.getpeercert() or {}


async def certificate(address: str, domain: str) -> dict:
    """The node's certificate checked against the system's trusted roots and the domain; raises ssl errors."""
    return await asyncio.to_thread(_certificate, address, domain)


# ---------------------------------------------------------------- the check

def node_address(host: str) -> str:
    """The node's address from the registry: a public IP (a name is resolved once here)."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    if not ip.is_global:
        raise ValueError("Адрес ноды не публичный: проверка снаружи невозможна")
    return str(ip)


def _name(cert: dict, key: str) -> str:
    for rdn in cert.get(key, ()):
        for k, v in rdn:
            if k in ("organizationName", "commonName"):
                return v
    return ""


async def check(domain: str, address: str) -> dict:
    report = Report(domain, address, datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    # 1. DNS
    try:
        found = await resolve(domain)
        report.add("dns", address in found, f"{domain} → {', '.join(sorted(found)) or 'нет записей'}"
                   + ("" if address in found else f" (адрес ноды {address})"))
    except OSError as exc:
        report.add("dns", False, f"{domain} не разрешается: {exc.__class__.__name__}")
    # 2–3. HTTPS and the page
    home = None
    try:
        home = await fetch(address, domain, "https", "/")
        report.add("https", home.status == 200, f"HTTPS: код {home.status}, {home.ms} мс")
    except Exception as exc:  # noqa: BLE001 — any failure is the remark
        report.add("https", False, f"HTTPS не открывается: {exc.__class__.__name__}")
    text = home.body.decode("utf-8", "replace") if home else ""
    title = (TITLE.search(text) or [None, ""])[1].strip() if home else ""
    own = bool(title) and not any(x in title.lower() for x in DEFAULT_TITLES)
    report.add("title", own, f"Заголовок: «{title[:80]}»" if title else "У страницы нет <title>")
    # 4. Certificate
    try:
        cert = await certificate(address, domain)
        left = (datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
        report.add("cert", left >= 7, f"Сертификат: {_name(cert, 'issuer') or 'издатель неизвестен'}, для {_name(cert, 'subject') or domain}, "
                   f"осталось {left} дн.")
    except (ssl.SSLError, ssl.CertificateError) as exc:
        report.add("cert", False, f"Сертификат не настоящий или не для {domain}: {getattr(exc, 'reason', None) or exc.__class__.__name__}")
    except (OSError, KeyError, ValueError) as exc:
        report.add("cert", False, f"Сертификат не прочитан: {exc.__class__.__name__}")
    # 5. http → https
    try:
        plain = await fetch(address, domain, "http", "/")
        location = plain.headers.get("location", "")
        report.add("redirect", plain.status == 301 and location.startswith(f"https://{domain}"),
                   f"http://: код {plain.status}" + (f" → {location[:80]}" if location else ""))
    except Exception as exc:  # noqa: BLE001
        report.add("redirect", False, f"http:// не отвечает: {exc.__class__.__name__}")
    # 6. 404
    try:
        missing = await fetch(address, domain, "https", f"/{secrets.token_hex(6)}-check")
        page = b"<html" in missing.body[:2000].lower() or b"<!doctype" in missing.body[:200].lower()
        report.add("notfound", missing.status == 404 and page, f"Несуществующий адрес: код {missing.status}" + ("" if page else ", без страницы"))
    except Exception as exc:  # noqa: BLE001
        report.add("notfound", False, f"Несуществующий адрес: {exc.__class__.__name__}")
    # 7–8. Headers
    if home:
        loud = [f"{k}: {home.headers[k]}" for k in ("server", "x-powered-by") if home.headers.get(k)]
        report.add("headers", not loud, "Лишних заголовков нет" if not loud else "Выдают программу: " + "; ".join(loud))
        hsts = home.headers.get("strict-transport-security", "")
        report.add("hsts", "max-age=" in hsts, f"HSTS: {hsts}" if hsts else "Нет Strict-Transport-Security")
    else:
        report.add("headers", False, "Нет ответа по HTTPS")
        report.add("hsts", False, "Нет ответа по HTTPS")
    # 9–10. robots.txt and the sitemap it names
    sitemap = ""
    try:
        robots = await fetch(address, domain, "https", "/robots.txt")
        body = robots.body.decode("utf-8", "replace")
        ok = robots.status == 200 and "user-agent" in body.lower()
        report.add("robots", ok, f"robots.txt: код {robots.status}")
        m = re.search(r"(?im)^\s*sitemap:\s*(\S+)", body) if ok else None
        sitemap = m.group(1) if m else ""
    except Exception as exc:  # noqa: BLE001
        report.add("robots", False, f"robots.txt: {exc.__class__.__name__}")
    target = urlsplit(sitemap)
    if not sitemap:
        report.add("sitemap", False, "В robots.txt нет строки Sitemap")
    elif target.hostname != domain:
        report.add("sitemap", False, f"Sitemap на другом домене ({target.hostname}) — не проверяется")
    else:
        try:
            got = await fetch(address, domain, "https", target.path or "/")
            ok = got.status == 200 and b"<urlset" in got.body[:5000]
            report.add("sitemap", ok, f"{target.path}: код {got.status}" + ("" if ok else ", не карта сайта"))
        except Exception as exc:  # noqa: BLE001
            report.add("sitemap", False, f"Sitemap: {exc.__class__.__name__}")
    # 11. Inner pages: links of the home page on the same domain that answer 200
    inner = []
    for href in dict.fromkeys(HREF.findall(text)):
        url = urlsplit(urljoin(f"https://{domain}/", href))
        if url.hostname == domain and url.scheme == "https" and url.path not in ("", "/") and not re.search(r"\.(css|js|svg|png|jpe?g|ico|webp)$", url.path):
            inner.append(url.path)
    alive = 0
    for path in inner[:5]:
        try:
            alive += (await fetch(address, domain, "https", path)).status == 200
        except Exception:  # noqa: BLE001
            pass
    report.add("pages", alive >= 2, f"Внутренних страниц открывается: {alive} из {len(inner[:5])}")
    return report.as_dict()
