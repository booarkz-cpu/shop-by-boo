"""Receive-only SMTP server for the shop's service addresses (MX of the mail domain).

* **Only listed recipients.** ``MAIL_RECEIVER_ROUTES`` maps addresses to targets, for
  example ``dmarc@shop.example=dmarc,support@shop.example=support``. Any other
  recipient is refused with 550 during the dialog, so the server can never relay.
* **Targets.** ``dmarc`` imports DMARC aggregate reports into the mail domain section
  (same limits as the mailbox intake); ``support`` posts the message to Support Pro's
  signed ``/email/inbound`` endpoint, where the email channel turns it into a ticket.
* **Checks.** SPF of the envelope sender, DKIM signatures and DMARC of the From
  domain: SPF ``fail`` and DMARC ``fail`` under ``p=reject`` are refused, everything
  else is accepted with an ``Authentication-Results`` header on top (incoming headers
  claiming to be ours are removed). Greylisting for unknown senders, message size and
  per-address rate limits, at most 10 recipients, command timeouts, and an optional
  ClamAV scan (``MAIL_RECEIVER_CLAMAV``).
* **No bounces.** Problems are reported inside the SMTP dialog; the receiver never
  sends mail, so it cannot start a bounce loop.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import ssl
import time
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Callable

import httpx

from .config import settings
from .mail_auth import AuthResults, authenticate
from . import mail_domain
from .mail_domain import Resolver

logger = logging.getLogger("vpnshop.mail_receiver")

COMMAND_TIMEOUT = 60.0
DATA_TIMEOUT = 300.0
MAX_RECIPIENTS = 10
MAX_COMMANDS = 100
MAX_LINE = 4096
PER_IP_CONNECTIONS = 5
MAX_CONNECTIONS = 100
RATE_MESSAGES, RATE_WINDOW = 30, 600.0
GREYLIST_DELAY, GREYLIST_TTL, WHITELIST_TTL = 60.0, 86400.0, 30 * 86400.0
TARGETS = ("dmarc", "support")


def routes() -> dict[str, str]:
    out = {}
    for part in (settings.mail_receiver_routes or "").split(","):
        address, _, target = part.strip().partition("=")
        if "@" in address and target.strip() in TARGETS:
            out[address.strip().lower()] = target.strip()
    return out


def hostname() -> str:
    domain = mail_domain.mail_domain()
    return (settings.mail_receiver_hostname or "").strip() or (f"mx.{domain}" if domain else "localhost")


def max_bytes() -> int:
    return max(1, int(settings.mail_receiver_max_mb or 10)) * 1024 * 1024


def _address(value: str) -> str:
    match = re.match(r"^\s*<([^>]*)>", value)
    return (match.group(1) if match else value.split()[0] if value.split() else "").strip().lower()


# ---------------------------------------------------------------- state (greylist, rate)

JOURNAL_KEY = "mx:journal"


class MemoryState:
    def __init__(self):
        self.values: dict[str, tuple[float, float]] = {}
        self.counters: dict[str, list[float]] = defaultdict(list)
        self.entries: list[dict] = []

    async def journal(self, entry: dict) -> None:
        self.entries.insert(0, entry)
        del self.entries[50:]

    async def recent(self) -> list[dict]:
        return list(self.entries)

    async def get(self, key: str) -> float | None:
        item = self.values.get(key)
        if not item or item[1] < time.time():
            return None
        return item[0]

    async def set(self, key: str, value: float, ttl: float) -> None:
        self.values[key] = (value, time.time() + ttl)

    async def hit(self, key: str, window: float) -> int:
        now = time.time()
        hits = [t for t in self.counters[key] if now - t < window]
        hits.append(now)
        self.counters[key] = hits
        return len(hits)


class RedisState:
    def __init__(self, client):
        self.client = client

    async def journal(self, entry: dict) -> None:
        await self.client.lpush(JOURNAL_KEY, json.dumps(entry, ensure_ascii=False))
        await self.client.ltrim(JOURNAL_KEY, 0, 49)

    async def recent(self) -> list[dict]:
        return [json.loads(item) for item in await self.client.lrange(JOURNAL_KEY, 0, 49)]

    async def get(self, key: str) -> float | None:
        value = await self.client.get(key)
        return float(value) if value is not None else None

    async def set(self, key: str, value: float, ttl: float) -> None:
        await self.client.set(key, str(value), ex=int(ttl))

    async def hit(self, key: str, window: float) -> int:
        count = await self.client.incr(key)
        if count == 1:
            await self.client.expire(key, int(window))
        return int(count)


def _network(ip: str) -> str:
    address = ipaddress.ip_address(ip)
    return str(ipaddress.ip_network(f"{ip}/{24 if address.version == 4 else 64}", strict=False))


async def greylisted(state, ip: str, mail_from: str, rcpt: str, now: float | None = None) -> bool:
    """True while the (network, sender, recipient) triplet is younger than a minute.
    A sender that passed once is remembered for 30 days per network and domain."""
    if not settings.mail_receiver_greylist:
        return False
    now = now or time.time()
    net = _network(ip)
    domain = mail_from.rpartition("@")[2] or "<>"
    if await state.get(f"mx:white:{net}:{domain}") is not None:
        return False
    key = "mx:grey:" + hashlib.sha256(f"{net}|{mail_from}|{rcpt}".encode()).hexdigest()
    first = await state.get(key)
    if first is None:
        await state.set(key, now, GREYLIST_TTL)
        return True
    if now - first < GREYLIST_DELAY:
        return True
    await state.set(f"mx:white:{net}:{domain}", now, WHITELIST_TTL)
    return False


# ---------------------------------------------------------------- ClamAV

class ScanUnavailable(Exception):
    """ClamAV did not answer: the message is deferred, never accepted unscanned."""


async def clamav_scan(data: bytes) -> str | None:
    """Virus name, or None when clean. Raises ScanUnavailable when ClamAV does not answer."""
    target = (settings.mail_receiver_clamav or "").strip()
    if not target:
        return None
    host, _, port = target.rpartition(":")
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host or target, int(port or 3310)), 10)
        writer.write(b"zINSTREAM\0")
        for start in range(0, len(data), 65536):
            chunk = data[start:start + 65536]
            writer.write(len(chunk).to_bytes(4, "big") + chunk)
        writer.write(b"\0\0\0\0")
        await writer.drain()
        reply = (await asyncio.wait_for(reader.read(4096), 60)).decode("utf-8", "replace").strip("\0 \n")
        writer.close()
    except (OSError, asyncio.TimeoutError, ValueError) as exc:
        raise ScanUnavailable(str(exc)) from exc
    if reply.endswith("FOUND"):
        return reply.split(":", 1)[-1].replace("FOUND", "").strip() or "malware"
    if not reply.endswith("OK"):
        raise ScanUnavailable(reply[:100])
    return None


# ---------------------------------------------------------------- delivery

http_factory: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=30, follow_redirects=False)


def support_signature(raw: bytes, timestamp: str, secret: str) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + hashlib.sha256(raw).hexdigest().encode(), hashlib.sha256).hexdigest()


class TemporaryFailure(Exception):
    """The target is unavailable: the sender gets 451 and retries."""


async def deliver(target: str, raw: bytes, sender: str, auth: AuthResults) -> str:
    if target == "dmarc":
        from .db import SessionLocal
        from .mail_domain import ReportError, import_bytes, report_parts

        _from, parts = report_parts(raw)
        if not parts:
            return "no report attached"
        trusted = auth.dmarc == "pass"
        outcomes = []
        async with SessionLocal() as db:
            for filename, payload in parts:
                try:
                    outcomes.append(await import_bytes(db, payload, "smtp", _from if trusted else ""))
                except ReportError as exc:
                    outcomes.append(f"rejected: {exc}")
            await db.commit()
        return ", ".join(outcomes)
    url, secret = (settings.mail_support_inbound_url or "").strip(), settings.mail_inbound_secret or ""
    if not url or not secret:
        raise TemporaryFailure("Support Pro inbound is not configured")
    timestamp = str(int(time.time()))
    try:
        async with http_factory() as client:
            response = await client.post(url, content=raw, headers={"Content-Type": "message/rfc822", "X-Mail-Timestamp": timestamp,
                                                                     "X-Mail-Signature": support_signature(raw, timestamp, secret)})
    except httpx.HTTPError as exc:
        raise TemporaryFailure("Support Pro is unreachable") from exc
    if response.status_code >= 500 or response.status_code == 429:
        raise TemporaryFailure(f"Support Pro answered {response.status_code}")
    if response.status_code >= 400:
        return f"refused by Support Pro ({response.status_code})"
    return (response.json() or {}).get("result", "accepted")


# ---------------------------------------------------------------- SMTP session

class Session:
    def __init__(self, server: "Receiver", reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.server, self.reader, self.writer = server, reader, writer
        peer = writer.get_extra_info("peername") or ("0.0.0.0", 0)
        self.ip = str(ipaddress.ip_address(peer[0].split("%")[0]))
        self.helo = ""
        self.tls = False
        self.reset()

    def reset(self) -> None:
        self.mail_from: str | None = None
        self.rcpts: list[tuple[str, str]] = []

    async def send(self, line: str) -> None:
        self.writer.write(line.encode() + b"\r\n")
        await self.writer.drain()

    async def readline(self, timeout: float = COMMAND_TIMEOUT) -> bytes | None:
        try:
            line = await asyncio.wait_for(self.reader.readuntil(b"\n"), timeout)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError):
            return None
        except asyncio.LimitOverrunError as exc:
            # Drop the oversized line, otherwise the next read sees the same bytes again.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.reader.readexactly(exc.consumed), timeout)
                await asyncio.wait_for(self.reader.readuntil(b"\n"), timeout)
            return b"\x00TOO-LONG"
        return line

    async def run(self) -> None:
        await self.send(f"220 {hostname()} ESMTP ready")
        for _ in range(MAX_COMMANDS):
            line = await self.readline()
            if line is None:
                await self.send("421 4.4.2 Timeout")
                return
            if line == b"\x00TOO-LONG":
                await self.send("500 5.5.2 Line too long")
                return
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            verb, _, arg = text.partition(" ")
            verb = verb.upper()
            handler = getattr(self, "cmd_" + verb.lower(), None) if verb.isalpha() else None
            if handler is None:
                await self.send("502 5.5.1 Command not implemented")
                continue
            if await handler(arg.strip()) is False:
                return
        await self.send("421 4.7.0 Too many commands")

    async def cmd_helo(self, arg: str) -> None:
        self.helo = arg[:255] or self.ip
        self.reset()
        await self.send(f"250 {hostname()}")

    async def cmd_ehlo(self, arg: str) -> None:
        self.helo = arg[:255] or self.ip
        self.reset()
        lines = [hostname(), f"SIZE {max_bytes()}", "8BITMIME", "ENHANCEDSTATUSCODES", "PIPELINING"]
        if self.server.tls_context and not self.tls:
            lines.append("STARTTLS")
        for index, item in enumerate(lines):
            await self.send(("250 " if index == len(lines) - 1 else "250-") + item)

    async def cmd_starttls(self, arg: str) -> bool | None:
        if not self.server.tls_context or self.tls:
            await self.send("502 5.5.1 TLS not available")
            return None
        await self.send("220 2.0.0 Ready to start TLS")
        try:
            await self.writer.start_tls(self.server.tls_context)
        except (ssl.SSLError, ConnectionError, OSError):
            return False
        self.tls, self.helo = True, ""
        self.reset()
        return None

    async def cmd_mail(self, arg: str) -> None:
        if not self.helo:
            await self.send("503 5.5.1 Send EHLO first")
            return
        if self.mail_from is not None:
            await self.send("503 5.5.1 Sender already given")
            return
        match = re.match(r"(?i)^FROM:\s*(<[^>]*>)(.*)$", arg)
        if not match:
            await self.send("501 5.5.4 Syntax: MAIL FROM:<address>")
            return
        size = re.search(r"(?i)\bSIZE=(\d+)", match.group(2))
        if size and int(size.group(1)) > max_bytes():
            await self.send("552 5.3.4 Message too big")
            return
        if await self.server.state.hit(f"mx:rate:{_network(self.ip)}", RATE_WINDOW) > RATE_MESSAGES:
            await self.send("450 4.7.1 Too many messages, try later")
            return
        self.mail_from = _address(match.group(1))
        await self.send("250 2.1.0 Sender OK")

    async def cmd_rcpt(self, arg: str) -> None:
        if self.mail_from is None:
            await self.send("503 5.5.1 Need MAIL first")
            return
        match = re.match(r"(?i)^TO:\s*(<[^>]*>)", arg)
        if not match:
            await self.send("501 5.5.4 Syntax: RCPT TO:<address>")
            return
        rcpt = _address(match.group(1))
        target = routes().get(rcpt)
        if target is None:
            await self.send("550 5.1.1 No such recipient here (relay denied)")
            return
        if len(self.rcpts) >= MAX_RECIPIENTS:
            await self.send("452 4.5.3 Too many recipients")
            return
        if await greylisted(self.server.state, self.ip, self.mail_from, rcpt):
            await self.send("451 4.7.1 Greylisted, please try again later")
            return
        self.rcpts.append((rcpt, target))
        await self.send("250 2.1.5 Recipient OK")

    async def cmd_data(self, arg: str) -> None:
        if not self.rcpts:
            await self.send("503 5.5.1 Need RCPT first")
            return
        await self.send("354 End data with <CR><LF>.<CR><LF>")
        chunks, size, too_big = [], 0, False
        while True:
            line = await self.readline(DATA_TIMEOUT)
            if line is None:
                await self.send("421 4.4.2 Timeout in DATA")
                return
            if line == b"\x00TOO-LONG":
                too_big = True  # keep reading to the end of DATA, then refuse
                continue
            if line.rstrip(b"\r\n") == b".":
                break
            if line.startswith(b"."):
                line = line[1:]
            size += len(line)
            if size > max_bytes():
                too_big = True
            elif not too_big:
                chunks.append(line)
        if too_big:
            self.reset()
            await self.send("552 5.3.4 Message too big")
            return
        raw = b"".join(chunks)
        code = await self.server.accept(self, raw)
        self.reset()
        await self.send(code)

    async def cmd_rset(self, arg: str) -> None:
        self.reset()
        await self.send("250 2.0.0 OK")

    async def cmd_noop(self, arg: str) -> None:
        await self.send("250 2.0.0 OK")

    async def cmd_vrfy(self, arg: str) -> None:
        await self.send("252 2.5.2 Cannot verify, send mail")

    async def cmd_quit(self, arg: str) -> bool:
        await self.send("221 2.0.0 Bye")
        return False



class Receiver:
    def __init__(self, state=None, tls_context: ssl.SSLContext | None = None):
        self.state = state or MemoryState()
        self.tls_context = tls_context
        self.connections: dict[str, int] = defaultdict(int)

    async def _log(self, session: Session, outcome: str, detail: str) -> None:
        entry = {"at": datetime.utcnow().isoformat(timespec="seconds"), "ip": session.ip, "from": session.mail_from or "",
                 "to": [r for r, _ in session.rcpts], "outcome": outcome, "detail": detail[:200]}
        with contextlib.suppress(Exception):
            await self.state.journal(entry)
        logger.info("mail %s from %s: %s", outcome, session.ip, detail[:200])

    async def accept(self, session: Session, raw: bytes) -> str:
        own = hostname().lower()
        lines = raw.replace(b"\r\n", b"\n").split(b"\n")
        cleaned, skip = [], False
        for line in lines:  # drop Authentication-Results that pretend to be ours (RFC 8601, 5)
            if line[:1] in (b" ", b"\t") and skip:
                continue
            skip = line.lower().startswith(b"authentication-results:") and line.split(b":", 1)[1].strip().lower().startswith(own.encode())
            if not skip:
                cleaned.append(line)
        raw = b"\r\n".join(cleaned)
        async with mail_domain.client_factory() as client:
            auth = await authenticate(Resolver(client), raw, session.ip, session.mail_from or "", session.helo)
        if auth.spf == "fail":
            await self._log(session, "rejected", f"SPF fail for {auth.spf_domain}")
            return "550 5.7.23 SPF validation failed"
        if auth.dmarc == "fail" and auth.dmarc_policy == "reject":
            await self._log(session, "rejected", f"DMARC reject for {auth.from_domain}")
            return "550 5.7.1 Rejected by DMARC policy of the sender domain"
        if auth.spf == "temperror" or auth.dmarc == "temperror":
            await self._log(session, "deferred", "DNS temporary error")
            return "451 4.4.3 Temporary DNS failure, try later"
        try:
            virus = await clamav_scan(raw)
        except ScanUnavailable:
            await self._log(session, "deferred", "antivirus unavailable")
            return "451 4.3.0 Antivirus unavailable, try later"
        if virus:
            await self._log(session, "rejected", f"malware {virus}")
            return "554 5.7.1 Message contains malware"
        received = (f"Received: from {session.helo or session.ip} ([{session.ip}])\r\n\tby {hostname()} with {'ESMTPS' if session.tls else 'ESMTP'}; "
                    f"{format_datetime(datetime.now(timezone.utc))}\r\n")
        message = (auth.header(hostname()) + "\r\n" + received).encode() + raw
        results = []
        for rcpt, target in session.rcpts:
            try:
                results.append(f"{target}: {await deliver(target, message, session.mail_from or '', auth)}")
            except TemporaryFailure as exc:
                await self._log(session, "deferred", str(exc))
                return "451 4.3.0 Temporary delivery failure, try later"
        await self._log(session, "accepted", "; ".join(results) + f" (spf={auth.spf}, dmarc={auth.dmarc})")
        return "250 2.0.0 Message accepted"

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        session = Session(self, reader, writer)
        if sum(self.connections.values()) >= MAX_CONNECTIONS or self.connections[session.ip] >= PER_IP_CONNECTIONS:
            with contextlib.suppress(ConnectionError):
                await session.send("421 4.7.0 Too many connections, try later")
            writer.close()
            return
        self.connections[session.ip] += 1
        try:
            await session.run()
        except (ConnectionError, ssl.SSLError):
            logger.info("mail connection from %s dropped", session.ip)
        finally:
            self.connections[session.ip] -= 1
            with contextlib.suppress(Exception):
                writer.close()


def tls_context() -> ssl.SSLContext | None:
    cert, key = (settings.mail_receiver_tls_cert or "").strip(), (settings.mail_receiver_tls_key or "").strip()
    if not cert or not key:
        return None
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    return context


async def serve(host: str = "0.0.0.0", port: int = 2525):
    state = MemoryState()
    if settings.redis_url:
        with contextlib.suppress(Exception):
            from redis.asyncio import Redis

            client = Redis.from_url(settings.redis_url, decode_responses=True, **settings.redis_connection_kwargs())
            await client.ping()
            state = RedisState(client)
    receiver = Receiver(state, tls_context())
    server = await asyncio.start_server(receiver.handle, host, port, limit=MAX_LINE)
    logger.warning("mail receiver on %s:%s for %s", host, port, ", ".join(routes()) or "no addresses (set MAIL_RECEIVER_ROUTES)")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if not settings.mail_receiver_enabled:
        raise SystemExit("MAIL_RECEIVER_ENABLED=false")
    asyncio.run(serve(port=int(settings.mail_receiver_port or 2525)))
