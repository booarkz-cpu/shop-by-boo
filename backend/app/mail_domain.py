"""Mail domain health: MX, SPF, DKIM and DMARC DNS checks and DMARC aggregate reports.

* **DNS checks.** Records are read through DNS-over-HTTPS (``MAIL_DNS_DOH_URL``, JSON
  API) so the check works without a resolver library. SPF is evaluated the way a
  receiver does it: one ``v=spf1`` record, at most 10 DNS-querying terms across
  ``include``/``redirect``, an explicit ``all``; when the SMTP host resolves, its
  address is checked against the policy. DKIM compares the published key with the
  key generated in the panel. DMARC checks the policy, ``pct``, the report address
  and the external-destination authorization of RFC 7489 section 7.1.
* **Reports.** Aggregate reports (XML, gzip or zip) come from a read-only IMAP
  mailbox (``DMARC_IMAP_*``) or an upload in the panel. Archives are unpacked with
  size and ratio limits, XML with DOCTYPE/ENTITY is refused, only reports about the
  shop's domain are kept, and ``(org_name, report_id)`` is unique, so a resent
  report is a duplicate, not a second copy. The mailbox is opened read-only and
  nothing is ever sent, so intake cannot cause a mail loop.
* **Trust.** Anyone can mail a report to the ``rua`` address. Reports are shown as
  observations only, never trigger actions, and a report whose sender address does
  not match the reporting organisation is marked as unverified.
* **Retention.** Reports older than ``DMARC_REPORT_RETENTION_DAYS`` are deleted; an
  administrator can erase all of them.
"""
from __future__ import annotations

import asyncio
import contextlib
import email
import email.policy
import imaplib
import io
import ipaddress
import json
import logging
import re
import ssl
import time
import zipfile
import zlib
from datetime import datetime, timedelta, timezone
from typing import Callable
from xml.etree import ElementTree

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import AppSetting, DmarcIntakeState, DmarcRecord, DmarcReport
from .security import decrypt_secret, require_permission

logger = logging.getLogger("vpnshop.mail_domain")

MAX_UPLOAD = 5 * 1024 * 1024          # compressed report or upload
MAX_XML = 50 * 1024 * 1024            # unpacked XML
MAX_RATIO = 200                       # unpacked / packed
MAX_MESSAGE = 10 * 1024 * 1024        # one mailbox message
MAX_RECORDS = 20000
MESSAGES_PER_CYCLE = 50
JOURNAL_SIZE = 30
SPF_LOOKUP_LIMIT = 10
CHECK_KEY = "mail_domain_check"
MAILBOX = "imap"
MANUAL_GAP = 30.0
REPORT_TYPES = {"application/gzip", "application/x-gzip", "application/zip", "application/x-zip-compressed",
                "application/xml", "text/xml", "application/octet-stream"}


def private(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(dependencies=[Depends(private)])


def utcnow() -> datetime:
    return datetime.utcnow()


def _address_domain(value: str) -> str:
    value = (value or "").strip().strip("<>").lower()
    return value.rsplit("@", 1)[1].strip(">").strip() if "@" in value else ""


def mail_domain() -> str:
    """The checked domain: MAIL_DOMAIN, otherwise the domain of the SMTP sender."""
    explicit = settings.mail_domain.strip().lower().rstrip(".")
    return explicit or _address_domain(settings.smtp_from) or _address_domain(settings.smtp_user)


def intake_configured() -> bool:
    return bool(settings.dmarc_imap_host.strip() and settings.dmarc_imap_user.strip() and settings.dmarc_imap_password)


def _belongs(domain: str, base: str) -> bool:
    domain, base = domain.lower().rstrip("."), base.lower().rstrip(".")
    return bool(base) and (domain == base or domain.endswith("." + base))


def organizational(domain: str) -> str:
    """Last two labels. Without a public suffix list this is an approximation, so it
    is only used to explain policy inheritance, never to accept foreign reports."""
    parts = domain.lower().rstrip(".").split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else domain.lower()


# ---------------------------------------------------------------- DNS over HTTPS

TYPES = {"A": 1, "MX": 15, "TXT": 16, "AAAA": 28}


class DnsError(Exception):
    """The resolver failed (not NXDOMAIN): the check result is unknown."""


def _default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=False,
                             headers={"Accept": "application/dns-json", "User-Agent": "CorgiShop-MailDomain/1"})


client_factory: Callable[[], httpx.AsyncClient] = _default_client


def _txt(data: str) -> str:
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', data)
    if not parts:
        return data
    return "".join(re.sub(r"\\(.)", r"\1", part) for part in parts)


class Resolver:
    """One check run: cached answers and a query budget against slow or looping DNS."""

    def __init__(self, client: httpx.AsyncClient, budget: int = 80):
        self.client, self.cache, self.budget = client, {}, budget

    async def query(self, name: str, rtype: str) -> list[str]:
        name = name.lower().rstrip(".")
        key = (name, rtype)
        if key in self.cache:
            return self.cache[key]
        if self.budget <= 0:
            raise DnsError("Слишком много DNS-запросов за одну проверку")
        self.budget -= 1
        try:
            response = await self.client.get(settings.mail_dns_doh_url, params={"name": name, "type": rtype}, headers={"Accept": "application/dns-json"})
        except httpx.HTTPError as exc:
            raise DnsError("DNS-резолвер недоступен") from exc
        if response.status_code != 200:
            raise DnsError(f"DNS-резолвер вернул HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise DnsError("DNS-резолвер вернул не JSON") from exc
        status = body.get("Status")
        if status == 3:  # NXDOMAIN
            self.cache[key] = []
            return []
        if status != 0:
            raise DnsError(f"DNS вернул код {status} для {name}")
        out = []
        for answer in body.get("Answer") or []:
            if answer.get("type") != TYPES[rtype]:
                continue
            data = str(answer.get("data") or "")
            out.append(_txt(data) if rtype == "TXT" else data if rtype == "MX" else data.rstrip("."))
        self.cache[key] = out
        return out

    async def addresses(self, name: str) -> list[str]:
        return [*(await self.query(name, "A")), *(await self.query(name, "AAAA"))]


# ---------------------------------------------------------------- findings

def sentence(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def finding(check: str, status: str, title: str, detail: str = "", record: str | None = None) -> dict:
    return {"check": check, "status": status, "title": title, "detail": detail, "record": record}


RANK = {"ok": 0, "info": 0, "warn": 1, "fail": 2}


def overall(findings: list[dict]) -> str:
    worst = max((RANK.get(f["status"], 0) for f in findings), default=0)
    return {0: "ok", 1: "warn", 2: "fail"}[worst]


# ---------------------------------------------------------------- MX

async def check_mx(dns: Resolver, domain: str) -> list[dict]:
    rows = []
    for value in await dns.query(domain, "MX"):
        parts = value.split()
        if len(parts) == 2 and parts[0].isdigit():
            rows.append((int(parts[0]), parts[1].rstrip(".").lower()))
    if not rows:
        return [finding("mx", "warn", "Нет MX-записи", "Почта на этот домен (ответы клиентов, отказы доставки, DMARC-отчёты на адрес домена) не доставляется. Если почта на домен не нужна, опубликуйте null MX: «0 .».")]
    if any(host in ("", ".") for _, host in rows):
        return [finding("mx", "info", "Домен не принимает почту (null MX)", "Отчёты DMARC должны идти на адрес другого домена.", "0 .")]
    out = []
    for pref, host in sorted(rows):
        if not await dns.addresses(host):
            out.append(finding("mx", "fail", f"MX-хост {host} не резолвится", "Отправители не смогут доставить почту на этот сервер.", f"{pref} {host}"))
    if settings.mail_receiver_enabled and settings.mail_receiver_hostname.strip():
        own = settings.mail_receiver_hostname.strip().lower().rstrip(".")
        if own not in [host for _, host in rows]:
            out.append(finding("mx", "warn", f"MX не указывает на приёмник магазина ({own})",
                               "Приёмник почты включён, но почта домена идёт на другие серверы. Добавьте MX-запись на этот хост или выключите приёмник.",
                               "; ".join(f"{p} {h}" for p, h in sorted(rows))))
    if not out:
        out.append(finding("mx", "ok", "MX-записи на месте", ", ".join(f"{p} {h}" for p, h in sorted(rows)), "; ".join(f"{p} {h}" for p, h in sorted(rows))))
    return out


# ---------------------------------------------------------------- SPF

class SpfContext:
    def __init__(self, dns: Resolver, ip: str | None):
        self.dns, self.ip, self.lookups, self.warnings, self.errors = dns, ip, 0, [], []

    def count(self, term: str) -> None:
        self.lookups += 1
        if self.lookups > SPF_LOOKUP_LIMIT:
            raise ValueError(f"больше {SPF_LOOKUP_LIMIT} DNS-запросов (последний — {term}); получатели вернут permerror")


def _spf_records(values: list[str]) -> list[str]:
    return [v for v in values if v.lower() == "v=spf1" or v.lower().startswith("v=spf1 ")]


def _in_network(ip: str, value: str, default_v4: int = 32, default_v6: int = 128) -> bool:
    try:
        address = ipaddress.ip_address(ip)
        if "/" not in value:
            value = f"{value}/{default_v4 if ':' not in value else default_v6}"
        return address in ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False


def _split_cidr(spec: str, domain: str) -> tuple[str, int | None, int | None]:
    """'a:example.com/24//64' -> (example.com, 24, 64)."""
    target, v4, v6 = spec or domain, None, None
    if "//" in target:
        target, rest = target.split("//", 1)
        v6 = int(rest) if rest.isdigit() else None
    if "/" in target:
        target, rest = target.split("/", 1)
        v4 = int(rest) if rest.isdigit() else None
    return (target or domain), v4, v6


async def _matches_host(ctx: SpfContext, host: str, v4: int | None, v6: int | None) -> bool:
    for address in await ctx.dns.addresses(host):
        prefix = (v6 if v6 is not None else 128) if ":" in address else (v4 if v4 is not None else 32)
        if _in_network(ctx.ip, f"{address}/{prefix}"):
            return True
    return False


QUALIFIERS = {"+": "pass", "-": "fail", "~": "softfail", "?": "neutral"}


async def _spf(ctx: SpfContext, domain: str, depth: int = 0) -> tuple[str | None, str | None]:
    """Returns (result for ctx.ip or None, all-qualifier of this policy). Every term is
    walked, even after a match, so the DNS lookup count is the receiver's worst case."""
    if depth > 10:
        raise ValueError("слишком глубокая вложенность include/redirect")
    records = _spf_records(await ctx.dns.query(domain, "TXT"))
    if not records:
        if depth:
            raise ValueError(f"include/redirect на {domain} без SPF-записи")
        return None, None
    if len(records) > 1:
        raise ValueError(f"у {domain} несколько SPF-записей")
    redirect, result, all_q = None, None, None
    for term in records[0].split()[1:]:
        lowered = term.lower()
        if lowered.startswith("redirect="):
            redirect = term.split("=", 1)[1]
            continue
        if re.match(r"^[a-z][a-z0-9_.-]*=", lowered):
            continue  # exp= and unknown modifiers
        qualifier = term[0] if term[0] in "+-~?" else "+"
        mech = term[1:] if term[0] in "+-~?" else term
        match = re.match(r"[a-z0-9]+", mech.lower())
        name = match.group(0) if match else ""
        arg = mech[len(name):]
        if "%" in arg:
            ctx.warnings.append(f"макрос в «{term}» не вычисляется проверкой")
            if name in ("include", "exists", "a", "mx", "ptr"):
                ctx.count(term)
            continue
        matched = False
        if name == "all":
            all_q = qualifier
            matched = True
        elif name in ("ip4", "ip6"):
            matched = bool(ctx.ip) and _in_network(ctx.ip, arg.lstrip(":"))
        elif name == "include":
            ctx.count(term)
            inner, _ = await _spf(ctx, arg.lstrip(":"), depth + 1)
            matched = inner == "pass"
        elif name == "a":
            ctx.count(term)
            host, v4, v6 = _split_cidr(arg.lstrip(":"), domain)
            matched = bool(ctx.ip) and await _matches_host(ctx, host, v4, v6)
        elif name == "mx":
            ctx.count(term)
            host, v4, v6 = _split_cidr(arg.lstrip(":"), domain)
            for value in (await ctx.dns.query(host, "MX"))[:10]:
                parts = value.split()
                if ctx.ip and len(parts) == 2 and await _matches_host(ctx, parts[1].rstrip("."), v4, v6):
                    matched = True
                    break
        elif name == "ptr":
            ctx.count(term)
            ctx.warnings.append("механизм ptr устарел (RFC 7208, 5.5) и многими получателями не поддерживается")
        elif name == "exists":
            ctx.count(term)
            matched = bool(ctx.ip) and bool(await ctx.dns.query(arg.lstrip(":"), "A"))
        else:
            raise ValueError(f"неизвестный механизм «{term}»")
        if matched and ctx.ip and result is None:
            result = QUALIFIERS[qualifier]
        if name == "all":
            break  # terms after all are never evaluated (RFC 7208, 5.1)
    if all_q is None and redirect:
        ctx.count("redirect=" + redirect)
        inner, all_q = await _spf(ctx, redirect, depth + 1)
        if result is None:
            result = inner
    if ctx.ip and result is None:
        result = "neutral"
    return result, all_q


async def check_spf(dns: Resolver, domain: str, smtp_host: str) -> list[dict]:
    values = _spf_records(await dns.query(domain, "TXT"))
    if not values:
        return [finding("spf", "fail", "Нет SPF-записи", "Получатели не знают, каким серверам разрешено отправлять почту домена. Добавьте TXT «v=spf1 include:<провайдер SMTP> -all».")]
    if len(values) > 1:
        return [finding("spf", "fail", "Несколько SPF-записей", "Получатели вернут permerror. Объедините их в одну запись.", " | ".join(values))]
    record = values[0]
    ip = None
    if smtp_host:
        try:
            ip = str(ipaddress.ip_address(smtp_host))
        except ValueError:
            found = await dns.addresses(smtp_host)
            ip = found[0] if found else None
    ctx = SpfContext(dns, ip)
    try:
        result, all_q = await _spf(ctx, domain)
    except ValueError as exc:
        return [finding("spf", "fail", "SPF-запись с ошибкой", sentence(str(exc)) + ".", record)]
    out = []
    if all_q in ("+", "?"):
        out.append(finding("spf", "fail", f"SPF разрешает отправку всем ({all_q}all)", "Любой сервер сможет отправлять почту от имени домена. Используйте -all или ~all.", record))
    elif all_q is None:
        out.append(finding("spf", "warn", "SPF без завершающего all", "Письма с чужих серверов получат neutral. Добавьте -all или ~all в конец записи.", record))
    for warning in ctx.warnings:
        out.append(finding("spf", "warn", "Замечание к SPF", sentence(warning) + ".", record))
    if ctx.lookups >= 8:
        out.append(finding("spf", "warn", f"SPF использует {ctx.lookups} из {SPF_LOOKUP_LIMIT} DNS-запросов", "Ещё один include может сделать запись недействительной.", record))
    if smtp_host and ip is None:
        out.append(finding("spf", "info", "Адрес SMTP-сервера не определён", f"{smtp_host} не резолвится; проверка покрытия адреса пропущена.", record))
    elif ip and result != "pass":
        out.append(finding("spf", "warn", f"Адрес SMTP-сервера {ip} не входит в SPF (результат {result})",
                           "Если провайдер отправляет с других серверов, чем адрес для подключения, убедитесь, что он указан через include.", record))
    if not out:
        out.append(finding("spf", "ok", "SPF настроен", f"Запросов DNS: {ctx.lookups} из {SPF_LOOKUP_LIMIT}" + (f"; {ip} разрешён" if ip else ""), record))
    return out


# ---------------------------------------------------------------- DKIM

def _tags(record: str) -> dict[str, str]:
    out = {}
    for part in record.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            out[key.strip().lower()] = re.sub(r"\s+", "", value.strip())
    return out


async def local_dkim(db: AsyncSession) -> dict | None:
    row = await db.get(AppSetting, "dkim_private")
    if not row:
        return None
    try:
        data = json.loads(row.value)
        from cryptography.hazmat.primitives import serialization

        key = serialization.load_pem_private_key(decrypt_secret(data["private"]).encode(), password=None)
        public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        body = "".join(line for line in public.splitlines() if not line.startswith("-----"))
        return {"selector": data.get("selector") or "shop", "domain": (data.get("domain") or "").lower(), "public": body}
    except Exception:
        return {"selector": None, "domain": None, "public": None, "error": "Ключ DKIM в панели не читается"}


async def check_dkim(dns: Resolver, domain: str, selectors: list[str], local: dict | None) -> list[dict]:
    if local and local.get("error"):
        return [finding("dkim", "fail", local["error"], "Создайте ключ заново в разделе «Антиабуз и агенты».")]
    names = list(dict.fromkeys([*([local["selector"]] if local and local.get("selector") and _belongs(domain, local.get("domain") or domain) else []), *selectors]))
    if not names:
        return [finding("dkim", "info", "Селектор DKIM не задан", "Ключ в панели не создан. Если письма подписывает провайдер SMTP, укажите его селектор при проверке.")]
    out = []
    for selector in names:
        name = f"{selector}._domainkey.{domain}"
        records = [v for v in await dns.query(name, "TXT") if "p=" in v.lower()]
        if not records:
            out.append(finding("dkim", "fail", f"Нет DKIM-ключа {selector}", f"TXT-запись {name} не найдена.", None))
            continue
        tags = _tags(records[0])
        if tags.get("v", "DKIM1").upper() != "DKIM1":
            out.append(finding("dkim", "fail", f"DKIM {selector}: неверная версия", "Ожидается v=DKIM1.", records[0]))
        elif not tags.get("p"):
            out.append(finding("dkim", "fail", f"DKIM {selector} отозван", "Пустой p= означает отозванный ключ.", records[0]))
        elif local and selector == local.get("selector") and local.get("public") and tags["p"] != local["public"]:
            out.append(finding("dkim", "fail", f"DKIM {selector}: ключ в DNS не совпадает с ключом панели", "Письма, подписанные ключом панели, не пройдут проверку. Опубликуйте TXT, выданный при создании ключа.", records[0][:120] + "…"))
        elif tags.get("t", "").find("y") >= 0:
            out.append(finding("dkim", "warn", f"DKIM {selector} в тестовом режиме (t=y)", "Получатели не учитывают результат подписи.", records[0][:120] + "…"))
        else:
            out.append(finding("dkim", "ok", f"DKIM {selector} опубликован", "Ключ совпадает с ключом панели." if local and selector == local.get("selector") else "Ключ опубликован.", records[0][:120] + "…"))
    return out


# ---------------------------------------------------------------- DMARC

async def check_dmarc(dns: Resolver, domain: str, from_domain: str) -> list[dict]:
    values = [v for v in await dns.query(f"_dmarc.{domain}", "TXT") if v.lower().replace(" ", "").startswith("v=dmarc1")]
    inherited = None
    if not values and organizational(domain) != domain:
        inherited = organizational(domain)
        values = [v for v in await dns.query(f"_dmarc.{inherited}", "TXT") if v.lower().replace(" ", "").startswith("v=dmarc1")]
    if not values:
        return [finding("dmarc", "fail", "Нет DMARC-записи", f"Добавьте TXT _dmarc.{domain}: «v=DMARC1; p=none; rua=mailto:dmarc@{domain}» и после проверки отчётов ужесточите политику.")]
    if len(values) > 1:
        return [finding("dmarc", "fail", "Несколько DMARC-записей", "Получатели проигнорируют политику.", " | ".join(values))]
    record = values[0]
    tags = _tags(record)
    out = []
    policy = tags.get("p", "").lower()
    if inherited:
        policy = tags.get("sp", policy).lower()
        out.append(finding("dmarc", "info", f"Политика наследуется от {inherited}", "Для поддомена действует sp= (или p=) организационного домена.", record))
    if policy not in ("none", "quarantine", "reject"):
        out.append(finding("dmarc", "fail", "DMARC без корректной политики p=", "Допустимо none, quarantine или reject.", record))
    elif policy == "none":
        out.append(finding("dmarc", "warn", "DMARC в режиме наблюдения (p=none)", "Подделанные письма доставляются. Когда отчёты покажут, что все ваши источники проходят проверку, перейдите на quarantine, затем reject.", record))
    try:
        pct = int(tags.get("pct", "100"))
    except ValueError:
        pct = 100
    if policy in ("quarantine", "reject") and pct < 100:
        out.append(finding("dmarc", "warn", f"Политика применяется к {pct}% писем", "Остальные письма обрабатываются как при p=none.", record))
    rua = [part.strip() for part in tags.get("rua", "").split(",") if part.strip()]
    if not rua:
        out.append(finding("dmarc", "warn", "Отчёты DMARC не запрошены (нет rua=)", f"Добавьте rua=mailto:dmarc@{domain}, чтобы видеть, кто отправляет почту от имени домена.", record))
    for target in rua:
        address = target[7:].split("!", 1)[0] if target.lower().startswith("mailto:") else ""
        target_domain = _address_domain(address)
        if not target_domain:
            out.append(finding("dmarc", "fail", f"Неверный адрес отчётов «{target}»", "Ожидается mailto:адрес.", record))
            continue
        if not (_belongs(target_domain, domain) or _belongs(target_domain, organizational(domain)) or _belongs(domain, organizational(target_domain))):
            auth = [v for v in await dns.query(f"{domain}._report._dmarc.{target_domain}", "TXT") if v.lower().replace(" ", "").startswith("v=dmarc1")]
            if not auth:
                out.append(finding("dmarc", "warn", f"{target_domain} не подтвердил приём отчётов", f"Получатели не отправят отчёты на чужой домен без TXT {domain}._report._dmarc.{target_domain} «v=DMARC1» (RFC 7489, 7.1).", record))
    mailbox = settings.dmarc_imap_user.strip().lower()
    if "@" in mailbox and rua and not any(mailbox in t.lower() for t in rua):
        out.append(finding("dmarc", "warn", "Ящик отчётов не указан в rua", f"Магазин читает {mailbox}, а отчёты уходят на {', '.join(rua)}.", record))
    if from_domain and not _belongs(from_domain, organizational(domain)):
        out.append(finding("dmarc", "warn", f"Адрес отправителя на другом домене ({from_domain})", "SMTP_FROM не выровнен с проверяемым доменом — DMARC проверит другой домен.", record))
    if not [f for f in out if f["status"] in ("warn", "fail")]:
        out.append(finding("dmarc", "ok", f"DMARC: p={policy}", "Политика опубликована, отчёты запрошены.", record))
    return out


async def run_checks(db: AsyncSession, selectors: list[str] | None = None) -> dict:
    domain = mail_domain()
    checked = utcnow()
    if not domain:
        return {"domain": "", "checked_at": checked.isoformat(), "status": "fail",
                "findings": [finding("domain", "fail", "Почтовый домен не задан", "Укажите MAIL_DOMAIN или адрес SMTP_FROM в .env.")]}
    findings: list[dict] = []
    async with client_factory() as client:
        dns = Resolver(client)
        local = await local_dkim(db)
        from_domain = _address_domain(settings.smtp_from)
        for name, step in (("mx", lambda: check_mx(dns, domain)), ("spf", lambda: check_spf(dns, domain, settings.smtp_host.strip())),
                           ("dkim", lambda: check_dkim(dns, domain, selectors or [], local)), ("dmarc", lambda: check_dmarc(dns, domain, from_domain))):
            try:
                findings.extend(await step())
            except DnsError as exc:
                findings.append(finding(name, "warn", "Проверка не выполнена", f"{exc}. Повторите позже.", None))
    result = {"domain": domain, "checked_at": checked.isoformat(), "status": overall(findings), "findings": findings,
              "selectors": selectors or []}
    row = await db.get(AppSetting, CHECK_KEY)
    if row:
        row.value = json.dumps(result, ensure_ascii=False)
    else:
        db.add(AppSetting(key=CHECK_KEY, value=json.dumps(result, ensure_ascii=False)))
    return result


# ---------------------------------------------------------------- DMARC aggregate reports

class ReportError(ValueError):
    """The file is not an acceptable aggregate report for this domain."""


def extract_xml(data: bytes) -> bytes:
    if len(data) > MAX_UPLOAD:
        raise ReportError("Файл больше 5 МБ")
    if data[:2] == b"\x1f\x8b":
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            out = decoder.decompress(data, MAX_XML + 1)
        except zlib.error as exc:
            raise ReportError("Повреждённый gzip") from exc
        if len(out) > MAX_XML or decoder.unconsumed_tail:
            raise ReportError("Распакованный отчёт больше 50 МБ")
    elif data[:4] == b"PK\x03\x04":
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
            members = [m for m in archive.infolist() if not m.is_dir()]
        except zipfile.BadZipFile as exc:
            raise ReportError("Повреждённый zip") from exc
        if len(members) != 1:
            raise ReportError("В архиве должен быть один XML-файл")
        member = members[0]
        if member.flag_bits & 0x1:
            raise ReportError("Зашифрованный архив")
        if member.file_size > MAX_XML:
            raise ReportError("Распакованный отчёт больше 50 МБ")
        try:
            with archive.open(member) as handle:
                out = handle.read(MAX_XML + 1)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error) as exc:
            raise ReportError("Архив не распаковывается") from exc
        if len(out) > MAX_XML:
            raise ReportError("Распакованный отчёт больше 50 МБ")
    else:
        out = data
    if len(data) and len(out) / len(data) > MAX_RATIO and len(out) > 1024 * 1024:
        raise ReportError("Подозрительная степень сжатия архива")
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(node, name: str):
    if node is None:
        return None
    for item in node:
        if _local(item.tag) == name:
            return item
    return None


def _children(node, name: str) -> list:
    return [item for item in (node if node is not None else []) if _local(item.tag) == name]


def _text(node, *path: str, limit: int = 255) -> str:
    for name in path:
        node = _child(node, name)
    return ((node.text or "").strip() if node is not None else "")[:limit]


def _int(value: str, field: str, low: int = 0, high: int = 10**12) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise ReportError(f"Поле {field} не число") from exc
    if not low <= number <= high:
        raise ReportError(f"Поле {field} вне допустимого диапазона")
    return number


def parse_report(xml: bytes, domain: str) -> dict:
    if re.search(rb"<!\s*(doctype|entity)", xml, re.I):
        raise ReportError("XML с DOCTYPE/ENTITY не принимается")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ReportError("Файл не является XML") from exc
    if _local(root.tag) != "feedback":
        raise ReportError("Это не DMARC aggregate report (нет <feedback>)")
    meta, policy = _child(root, "report_metadata"), _child(root, "policy_published")
    org, report_id = _text(meta, "org_name"), _text(meta, "report_id")
    if not org or not report_id:
        raise ReportError("В отчёте нет org_name или report_id")
    begin = _int(_text(meta, "date_range", "begin"), "date_range/begin", 0, 2**33)
    end = _int(_text(meta, "date_range", "end"), "date_range/end", 0, 2**33)
    if end < begin or end - begin > 32 * 86400:
        raise ReportError("Неверный интервал отчёта")
    if end > time.time() + 2 * 86400:
        raise ReportError("Интервал отчёта в будущем")
    reported = _text(policy, "domain").lower().rstrip(".")
    if not _belongs(reported, domain):
        raise ReportError(f"Отчёт о чужом домене ({reported or 'не указан'})")
    rows = _children(root, "record")
    if len(rows) > MAX_RECORDS:
        raise ReportError(f"Больше {MAX_RECORDS} записей в отчёте")
    records = []
    for row in rows:
        data = _child(row, "row")
        try:
            ip = str(ipaddress.ip_address(_text(data, "source_ip")))
        except ValueError as exc:
            raise ReportError("Неверный source_ip в записи") from exc
        evaluated = _child(data, "policy_evaluated")
        auth = _child(row, "auth_results")
        dkim = _child(auth, "dkim")
        spf = _child(auth, "spf")
        records.append({
            "source_ip": ip, "count": _int(_text(data, "count") or "0", "count", 0, 10**10),
            "disposition": _text(evaluated, "disposition", limit=16).lower() or None,
            "dkim": _text(evaluated, "dkim", limit=8).lower() or None, "spf": _text(evaluated, "spf", limit=8).lower() or None,
            "header_from": _text(row, "identifiers", "header_from").lower() or None,
            "dkim_domain": _text(dkim, "domain").lower() or None, "dkim_result": _text(dkim, "result", limit=16).lower() or None,
            "spf_domain": _text(spf, "domain").lower() or None, "spf_result": _text(spf, "result", limit=16).lower() or None,
        })
    pct = _text(policy, "pct")
    return {
        "org_name": org, "report_id": report_id, "reporter_email": _text(meta, "email").lower() or None, "domain": reported,
        "policy": _text(policy, "p", limit=16).lower() or None, "pct": int(pct) if pct.isdigit() else None,
        "date_begin": datetime.fromtimestamp(begin, timezone.utc).replace(tzinfo=None),
        "date_end": datetime.fromtimestamp(end, timezone.utc).replace(tzinfo=None), "records": records,
    }


def _passed(record: dict) -> bool:
    return record.get("dkim") == "pass" or record.get("spf") == "pass"


async def store_report(db: AsyncSession, parsed: dict, source: str, sender: str = "") -> str:
    """Inserts the report with its records. Returns 'imported' or 'duplicate'. The caller commits."""
    existing = await db.scalar(select(DmarcReport.id).where(DmarcReport.org_name == parsed["org_name"], DmarcReport.report_id == parsed["report_id"]))
    if existing:
        return "duplicate"
    messages = sum(r["count"] for r in parsed["records"])
    passed = sum(r["count"] for r in parsed["records"] if _passed(r))
    reporter = parsed.get("reporter_email") or ""
    sender_domain = _address_domain(sender)
    report = DmarcReport(
        org_name=parsed["org_name"], report_id=parsed["report_id"], reporter_email=reporter or None,
        sender_matches=bool(sender_domain) and bool(_address_domain(reporter)) and organizational(sender_domain) == organizational(_address_domain(reporter)),
        domain=parsed["domain"], policy=parsed["policy"], pct=parsed["pct"], date_begin=parsed["date_begin"], date_end=parsed["date_end"],
        received_at=utcnow(), source=source, messages=messages, passed=passed, failed=messages - passed)
    try:
        async with db.begin_nested():
            db.add(report)
            await db.flush()
            for record in parsed["records"]:
                db.add(DmarcRecord(report_row_id=report.id, **record))
            await db.flush()
    except IntegrityError:
        return "duplicate"  # the same report stored concurrently
    return "imported"


async def import_bytes(db: AsyncSession, data: bytes, source: str, sender: str = "") -> str:
    xml = extract_xml(data)
    domain = mail_domain()
    if not domain:
        raise ReportError("Почтовый домен не задан (MAIL_DOMAIN или SMTP_FROM)")
    return await store_report(db, parse_report(xml, domain), source, sender)


def report_parts(raw: bytes) -> tuple[str, list[tuple[str, bytes]]]:
    """Report attachments of one mailbox message: (sender, [(filename, bytes)])."""
    message = email.message_from_bytes(raw, policy=email.policy.default)
    sender = str(message.get("From") or "")
    parts = []
    for part in message.walk():
        if part.is_multipart():
            continue
        filename = (part.get_filename() or "").lower()
        ctype = part.get_content_type()
        if ctype in REPORT_TYPES or filename.endswith((".xml", ".gz", ".zip")):
            if ctype == "application/octet-stream" and not filename.endswith((".xml", ".gz", ".zip")):
                continue
            payload = part.get_payload(decode=True) or b""
            parts.append((filename or ctype, payload))
        if len(parts) >= 3:
            break
    return sender, parts


# ---------------------------------------------------------------- IMAP intake (read-only)

def _imap_connect():
    context = ssl.create_default_context()
    if settings.dmarc_imap_port == 143:
        client = imaplib.IMAP4(settings.dmarc_imap_host.strip(), 143, timeout=30)
        client.starttls(ssl_context=context)
        return client
    return imaplib.IMAP4_SSL(settings.dmarc_imap_host.strip(), settings.dmarc_imap_port, ssl_context=context, timeout=30)


imap_factory: Callable[[], imaplib.IMAP4] = _imap_connect


class IntakeError(Exception):
    """The mailbox could not be read; the cursor stays where it was."""


def fetch_new(uidvalidity: int | None, last_uid: int, limit: int = MESSAGES_PER_CYCLE) -> tuple[int, list[tuple[int, bytes | None]]]:
    """Reads up to ``limit`` messages after ``last_uid`` without changing the mailbox.
    A message above MAX_MESSAGE is returned with ``None`` instead of its body."""
    try:
        client = imap_factory()
    except (OSError, imaplib.IMAP4.error, ssl.SSLError) as exc:
        raise IntakeError(f"IMAP недоступен: {type(exc).__name__}") from exc
    try:
        try:
            client.login(settings.dmarc_imap_user.strip(), settings.dmarc_imap_password)
        except imaplib.IMAP4.error as exc:
            raise IntakeError("IMAP отклонил вход: проверьте DMARC_IMAP_USER и DMARC_IMAP_PASSWORD") from exc
        typ, _ = client.select(settings.dmarc_imap_folder.strip() or "INBOX", readonly=True)
        if typ != "OK":
            raise IntakeError("Папка IMAP не открывается")
        validity = client.response("UIDVALIDITY")[1]
        current = int(validity[0]) if validity and validity[0] else 0
        start = last_uid if uidvalidity == current else 0
        typ, data = client.uid("SEARCH", None, f"UID {start + 1}:*")
        if typ != "OK":
            raise IntakeError("Поиск писем IMAP не выполнен")
        uids = sorted(u for u in (int(x) for x in (data[0] or b"").split()) if u > start)[:limit]
        out: list[tuple[int, bytes | None]] = []
        for uid in uids:
            typ, meta = client.uid("FETCH", str(uid), "(RFC822.SIZE)")
            size = re.search(rb"RFC822\.SIZE (\d+)", b" ".join(m if isinstance(m, bytes) else b" ".join(m) for m in meta if m)) if typ == "OK" else None
            if not size or int(size.group(1)) > MAX_MESSAGE:
                out.append((uid, None))
                continue
            typ, body = client.uid("FETCH", str(uid), "(BODY.PEEK[])")
            raw = next((item[1] for item in body if isinstance(item, tuple) and len(item) > 1), None) if typ == "OK" else None
            out.append((uid, raw))
        return current, out
    except (OSError, imaplib.IMAP4.error, ssl.SSLError) as exc:
        raise IntakeError(f"Ошибка IMAP: {type(exc).__name__}") from exc
    finally:
        with contextlib.suppress(Exception):
            client.logout()


async def _state(db: AsyncSession) -> DmarcIntakeState:
    state = await db.get(DmarcIntakeState, MAILBOX, with_for_update=True)
    if state is None:
        state = DmarcIntakeState(mailbox=MAILBOX, last_uid=0, imported=0, duplicates=0, rejected=0, journal=[])
        db.add(state)
        await db.flush()
    return state


def _journal(state: DmarcIntakeState, outcome: str, detail: str, source: str) -> None:
    entries = list(state.journal or [])
    entries.insert(0, {"at": utcnow().isoformat(timespec="seconds"), "outcome": outcome, "detail": detail[:200], "source": source})
    state.journal = entries[:JOURNAL_SIZE]


def _count(state: DmarcIntakeState, outcome: str) -> None:
    if outcome == "imported":
        state.imported += 1
    elif outcome == "duplicate":
        state.duplicates += 1
    else:
        state.rejected += 1


async def intake(db: AsyncSession) -> dict:
    """One read-only mailbox cycle. Each message commits together with the cursor."""
    if not intake_configured():
        return {"configured": False}
    state = await _state(db)
    validity, last_uid = state.uidvalidity, state.last_uid
    await db.commit()
    try:
        current, messages = await asyncio.to_thread(fetch_new, validity, last_uid)
    except IntakeError as exc:
        state = await _state(db)
        state.last_error, state.last_error_at = str(exc)[:255], utcnow()
        await db.commit()
        return {"configured": True, "error": str(exc)}
    stats = {"configured": True, "messages": len(messages), "imported": 0, "duplicate": 0, "rejected": 0}
    if validity != current:
        state = await _state(db)
        state.uidvalidity, state.last_uid = current, 0
        await db.commit()
    for uid, raw in messages:
        state = await _state(db)
        if raw is None:
            _journal(state, "rejected", f"Письмо UID {uid} больше 10 МБ или недоступно", "imap")
            _count(state, "rejected")
            stats["rejected"] += 1
        else:
            sender, parts = report_parts(raw)
            if not parts:
                _journal(state, "rejected", f"Письмо UID {uid} без вложения-отчёта", "imap")
                _count(state, "rejected")
                stats["rejected"] += 1
            for filename, payload in parts:
                try:
                    outcome = await import_bytes(db, payload, "imap", sender)
                    detail = filename
                except ReportError as exc:
                    outcome, detail = "rejected", f"{filename}: {exc}"
                _journal(state, outcome, detail, "imap")
                _count(state, outcome)
                stats[outcome] += 1
        state.last_uid = max(state.last_uid, uid)
        await db.commit()
    state = await _state(db)
    state.last_success, state.last_error = utcnow(), None
    await db.commit()
    return stats


async def enforce_retention(db: AsyncSession, now: datetime | None = None) -> int:
    days = max(1, int(settings.dmarc_report_retention_days or 180))
    cutoff = (now or utcnow()) - timedelta(days=days)
    ids = (await db.scalars(select(DmarcReport.id).where(DmarcReport.date_end < cutoff))).all()
    if ids:
        await db.execute(delete(DmarcRecord).where(DmarcRecord.report_row_id.in_(ids)))
        await db.execute(delete(DmarcReport).where(DmarcReport.id.in_(ids)))
    return len(ids)


async def erase_all(db: AsyncSession) -> int:
    count = await db.scalar(select(func.count(DmarcReport.id))) or 0
    await db.execute(delete(DmarcRecord))
    await db.execute(delete(DmarcReport))
    state = await db.get(DmarcIntakeState, MAILBOX, with_for_update=True)
    if state:
        state.journal, state.imported, state.duplicates, state.rejected = [], 0, 0, 0
    return count


# ---------------------------------------------------------------- summary

async def summary(db: AsyncSession, days: int = 30, now: datetime | None = None) -> dict:
    since = (now or utcnow()) - timedelta(days=days)
    reports = (await db.scalars(select(DmarcReport).where(DmarcReport.date_end >= since).order_by(DmarcReport.date_end.desc()))).all()
    ids = [r.id for r in reports]
    rows = (await db.scalars(select(DmarcRecord).where(DmarcRecord.report_row_id.in_(ids)))).all() if ids else []
    sources: dict[str, dict] = {}
    for row in rows:
        item = sources.setdefault(row.source_ip, {"ip": row.source_ip, "messages": 0, "passed": 0, "failed": 0, "dispositions": {}, "header_from": set(), "dkim_domains": set()})
        item["messages"] += row.count
        passed = row.dkim == "pass" or row.spf == "pass"
        item["passed" if passed else "failed"] += row.count
        if row.disposition:
            item["dispositions"][row.disposition] = item["dispositions"].get(row.disposition, 0) + row.count
        if row.header_from:
            item["header_from"].add(row.header_from)
        if row.dkim_domain:
            item["dkim_domains"].add(row.dkim_domain)
    listed = sorted(sources.values(), key=lambda s: (-s["failed"], -s["messages"]))[:50]
    for item in listed:
        item["header_from"], item["dkim_domains"] = sorted(item["header_from"]), sorted(item["dkim_domains"])
    total = sum(r.messages for r in reports)
    passed = sum(r.passed for r in reports)
    reporters: dict[str, int] = {}
    for r in reports:
        reporters[r.org_name] = reporters.get(r.org_name, 0) + 1
    return {"days": days, "reports": len(reports), "messages": total, "passed": passed, "failed": total - passed,
            "pass_rate": round(passed * 100 / total, 1) if total else None, "sources": listed,
            "reporters": [{"org": k, "reports": v} for k, v in sorted(reporters.items(), key=lambda kv: -kv[1])]}


def _report_row(r: DmarcReport) -> dict:
    return {"id": r.id, "org_name": r.org_name, "report_id": r.report_id, "reporter_email": r.reporter_email,
            "sender_matches": r.sender_matches, "domain": r.domain, "policy": r.policy, "pct": r.pct,
            "date_begin": r.date_begin.isoformat(), "date_end": r.date_end.isoformat(), "received_at": r.received_at.isoformat(),
            "source": r.source, "messages": r.messages, "passed": r.passed, "failed": r.failed}


# ---------------------------------------------------------------- scheduler

async def mail_domain_scheduler():
    from .db import engine

    last_check = 0.0
    while True:
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                if intake_configured():
                    await intake(db)
                await enforce_retention(db)
                await db.commit()
                if mail_domain() and time.monotonic() - last_check > 86400:
                    last_check = time.monotonic()
                    stored = await db.get(AppSetting, CHECK_KEY)
                    selectors = json.loads(stored.value).get("selectors", []) if stored else []
                    await run_checks(db, selectors)
                    await db.commit()
        except Exception as exc:
            logger.warning("Mail domain cycle failed: %s", type(exc).__name__)
        await asyncio.sleep(900)


# ---------------------------------------------------------------- admin API

_manual: dict[str, float] = {}


def _throttle(key: str) -> None:
    if time.monotonic() - _manual.get(key, -MANUAL_GAP) < MANUAL_GAP:
        raise HTTPException(429, "Повторите через 30 секунд")
    _manual[key] = time.monotonic()


async def _view(db: AsyncSession) -> dict:
    stored = await db.get(AppSetting, CHECK_KEY)
    check = json.loads(stored.value) if stored else None
    state = await db.get(DmarcIntakeState, MAILBOX)
    recent = (await db.scalars(select(DmarcReport).order_by(DmarcReport.date_end.desc(), DmarcReport.id.desc()).limit(20))).all()
    return {
        "domain": mail_domain(),
        "smtp_from": settings.smtp_from or settings.smtp_user,
        "check": check if check and check.get("domain") == mail_domain() else None,
        "intake": {
            "configured": intake_configured(), "mailbox": settings.dmarc_imap_user.strip() if intake_configured() else "",
            "folder": settings.dmarc_imap_folder.strip() or "INBOX", "retention_days": settings.dmarc_report_retention_days,
            "last_success": state.last_success.isoformat() if state and state.last_success else None,
            "last_error": state.last_error if state else None,
            "imported": state.imported if state else 0, "duplicates": state.duplicates if state else 0, "rejected": state.rejected if state else 0,
            "journal": (state.journal or [])[:10] if state else [],
        },
        "summary": await summary(db),
        "reports": [_report_row(r) for r in recent],
        "receiver": await receiver_status(),
    }


async def receiver_status() -> dict:
    """The MX receiver runs as its own process; its journal is shared through Redis."""
    from .mail_receiver import JOURNAL_KEY, hostname, routes
    from . import main

    journal: list = []
    client = getattr(main, "redis_client", None)
    if client is not None:
        try:
            journal = [json.loads(item) for item in await client.lrange(JOURNAL_KEY, 0, 19)]
        except Exception:
            journal = []
    return {"enabled": settings.mail_receiver_enabled, "hostname": hostname(), "greylist": settings.mail_receiver_greylist,
            "tls": bool(settings.mail_receiver_tls_cert and settings.mail_receiver_tls_key), "antivirus": bool(settings.mail_receiver_clamav),
            "support_ready": bool(settings.mail_support_inbound_url and settings.mail_inbound_secret),
            "routes": [{"address": a, "target": t} for a, t in routes().items()], "journal": journal}


@router.get("/api/admin/mail/domain")
async def admin_mail_domain(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    return await _view(db)


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dkim_selectors: list[str] = Field(default_factory=list, max_length=5)


@router.post("/api/admin/mail/domain/check")
async def admin_mail_check(body: CheckIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    selectors = []
    for value in body.dkim_selectors:
        value = value.strip().lower()
        if value and not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,62}", value):
            raise HTTPException(422, "Селектор DKIM: латиница, цифры, точка, дефис")
        if value:
            selectors.append(value)
    _throttle("check")
    result = await run_checks(db, selectors)
    from .main import audit

    await audit(db, "mail.domain.check", getattr(admin, "email", "admin"), result["domain"], {"status": result["status"]})
    await db.commit()
    return await _view(db)


@router.post("/api/admin/mail/dmarc/upload")
async def admin_dmarc_upload(file: UploadFile = File(...), db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    data = await file.read(MAX_UPLOAD + 1)
    state = await _state(db)
    name = (file.filename or "report")[:120]
    try:
        outcome = await import_bytes(db, data, "upload")
    except ReportError as exc:
        _journal(state, "rejected", f"{name}: {exc}", "upload")
        _count(state, "rejected")
        await db.commit()
        raise HTTPException(422, str(exc))
    _journal(state, outcome, name, "upload")
    _count(state, outcome)
    from .main import audit

    await audit(db, "mail.dmarc.upload", getattr(admin, "email", "admin"), name, {"outcome": outcome})
    await db.commit()
    return {"outcome": outcome, **(await _view(db))}


@router.post("/api/admin/mail/dmarc/sync")
async def admin_dmarc_sync(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    if not intake_configured():
        raise HTTPException(409, "Ящик отчётов не настроен: задайте DMARC_IMAP_HOST, DMARC_IMAP_USER и DMARC_IMAP_PASSWORD")
    _throttle("sync")
    stats = await intake(db)
    return {"result": stats, **(await _view(db))}


@router.get("/api/admin/mail/dmarc/reports/{report_id}")
async def admin_dmarc_report(report_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    report = await db.get(DmarcReport, report_id)
    if not report:
        raise HTTPException(404, "Отчёт не найден")
    rows = (await db.scalars(select(DmarcRecord).where(DmarcRecord.report_row_id == report_id).order_by(DmarcRecord.count.desc()).limit(500))).all()
    return {**_report_row(report), "records": [{
        "source_ip": r.source_ip, "count": r.count, "disposition": r.disposition, "dkim": r.dkim, "spf": r.spf,
        "header_from": r.header_from, "dkim_domain": r.dkim_domain, "dkim_result": r.dkim_result,
        "spf_domain": r.spf_domain, "spf_result": r.spf_result} for r in rows]}


class EraseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str


@router.post("/api/admin/mail/dmarc/erase")
async def admin_dmarc_erase(body: EraseIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    if body.confirm.strip() != "УДАЛИТЬ":
        raise HTTPException(422, "Для подтверждения введите УДАЛИТЬ")
    count = await erase_all(db)
    from .main import audit

    await audit(db, "mail.dmarc.erase", getattr(admin, "email", "admin"), mail_domain(), {"reports": count})
    await db.commit()
    return {"erased": count, **(await _view(db))}
