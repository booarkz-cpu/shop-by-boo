"""Authentication of incoming mail: SPF (RFC 7208), DKIM (RFC 6376, RFC 8463) and DMARC (RFC 7489).

DNS goes through the DNS-over-HTTPS resolver of ``mail_domain``. Results follow the
RFC vocabulary (pass, fail, softfail, neutral, none, temperror, permerror) so the
receiver can write an ``Authentication-Results`` header (RFC 8601).
"""
from __future__ import annotations

import base64
import hashlib
import re
import time
from dataclasses import dataclass, field

from .mail_domain import DnsError, Resolver, SpfContext, _address_domain, _spf, _tags, organizational

WSP = re.compile(rb"[ \t]+")


# ---------------------------------------------------------------- SPF

async def spf(dns: Resolver, ip: str, mail_from: str, helo: str) -> tuple[str, str]:
    """(result, checked domain). The null sender is checked with the HELO name."""
    domain = _address_domain(mail_from) or helo.lower().strip(".")
    if not domain or "." not in domain:
        return "none", domain
    try:
        result, _all = await _spf(SpfContext(dns, ip), domain)
    except DnsError:
        return "temperror", domain
    except ValueError:
        return "permerror", domain
    return (result or "none"), domain


# ---------------------------------------------------------------- DKIM

def split_message(raw: bytes) -> tuple[list[bytes], bytes]:
    """Header fields (each with its folding, without the final CRLF) and the body."""
    raw = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    head, sep, body = raw.partition(b"\r\n\r\n")
    if not sep:
        head, body = raw, b""
    fields: list[bytes] = []
    for line in head.split(b"\r\n"):
        if line[:1] in (b" ", b"\t") and fields:
            fields[-1] += b"\r\n" + line
        elif line:
            fields.append(line)
    return fields, body


def _name(field_: bytes) -> str:
    return field_.split(b":", 1)[0].strip().lower().decode("latin-1")


def canon_body(body: bytes, mode: str, length: int | None = None) -> bytes:
    lines = body.split(b"\r\n")
    if body.endswith(b"\r\n"):
        lines = lines[:-1]
    if mode == "relaxed":
        lines = [WSP.sub(b" ", line).rstrip(b" ") for line in lines]
    while lines and lines[-1] == b"":
        lines.pop()
    if mode == "relaxed":
        out = b"".join(line + b"\r\n" for line in lines)
    else:
        out = b"".join(line + b"\r\n" for line in lines) or b"\r\n"
    return out[:length] if length is not None else out


def canon_header(field_: bytes, mode: str) -> bytes:
    if mode == "simple":
        return field_
    name, _, value = field_.partition(b":")
    value = WSP.sub(b" ", value.replace(b"\r\n", b"")).strip(b" ")
    return name.strip().lower() + b":" + value


@dataclass
class DkimResult:
    domain: str
    selector: str
    result: str
    reason: str = ""


@dataclass
class AuthResults:
    spf: str = "none"
    spf_domain: str = ""
    dkim: list[DkimResult] = field(default_factory=list)
    dmarc: str = "none"
    dmarc_policy: str = "none"
    from_domain: str = ""

    def header(self, hostname: str) -> str:
        dkim = next((d for d in self.dkim if d.result == "pass"), self.dkim[0] if self.dkim else None)
        parts = [f"spf={self.spf} smtp.mailfrom={self.spf_domain or 'unknown'}",
                 f"dkim={dkim.result} header.d={dkim.domain}" if dkim else "dkim=none",
                 f"dmarc={self.dmarc} (p={self.dmarc_policy}) header.from={self.from_domain or 'unknown'}"]
        return f"Authentication-Results: {hostname}; " + "; ".join(parts)


def _strip_b(value: str) -> str:
    """The signature header with the b= value emptied (RFC 6376, 3.7)."""
    return re.sub(r"((?:^|;)[ \t\r\n]*b[ \t\r\n]*=)[^;]*", r"\1", value, count=1)


async def _key(dns: Resolver, selector: str, domain: str) -> tuple[str, bytes] | None:
    records = [r for r in await dns.query(f"{selector}._domainkey.{domain}", "TXT") if "p=" in r]
    if not records:
        return None
    tags = _tags(records[0])
    if not tags.get("p"):
        return "revoked", b""
    return tags.get("k", "rsa").lower(), base64.b64decode(tags["p"] + "=" * (-len(tags["p"]) % 4))


def _verify(kind: str, key: bytes, signature: bytes, data: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

    try:
        if kind == "ed25519":
            ed25519.Ed25519PublicKey.from_public_bytes(key).verify(signature, hashlib.sha256(data).digest())
            return True
        public = serialization.load_der_public_key(key)
        if not isinstance(public, rsa.RSAPublicKey) or public.key_size < 1024:
            return False
        public.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


async def dkim(dns: Resolver, raw: bytes, now: float | None = None, limit: int = 3) -> list[DkimResult]:
    fields, body = split_message(raw)
    signatures = [f for f in fields if _name(f) == "dkim-signature"][:limit]
    out: list[DkimResult] = []
    for sig_field in signatures:
        value = sig_field.split(b":", 1)[1].decode("latin-1")
        tags = {k: v for k, v in _tags(value).items()}
        domain, selector = tags.get("d", "").lower(), tags.get("s", "")
        try:
            if tags.get("v") != "1" or not domain or not selector or "h" not in tags or "bh" not in tags or "b" not in tags:
                out.append(DkimResult(domain, selector, "permerror", "missing tags"))
                continue
            algorithm = tags.get("a", "").lower()
            if algorithm not in ("rsa-sha256", "ed25519-sha256"):
                out.append(DkimResult(domain, selector, "permerror", f"algorithm {algorithm}"))
                continue
            if "from" not in [h.strip().lower() for h in tags["h"].split(":")]:
                out.append(DkimResult(domain, selector, "permerror", "From not signed"))
                continue
            if tags.get("x", "").isdigit() and int(tags["x"]) < (now or time.time()):
                out.append(DkimResult(domain, selector, "fail", "expired"))
                continue
            header_mode, _, body_mode = tags.get("c", "simple/simple").lower().partition("/")
            body_mode = body_mode or "simple"
            length = int(tags["l"]) if tags.get("l", "").isdigit() else None
            if base64.b64encode(hashlib.sha256(canon_body(body, body_mode, length)).digest()).decode() != tags["bh"]:
                out.append(DkimResult(domain, selector, "fail", "body hash"))
                continue
            remaining = list(fields)
            data = b""
            for name in tags["h"].split(":"):
                name = name.strip().lower()
                for index in range(len(remaining) - 1, -1, -1):  # bottom-most unused instance first
                    if _name(remaining[index]) == name:
                        data += canon_header(remaining.pop(index), header_mode) + b"\r\n"
                        break
            data += canon_header(_strip_b(sig_field.decode("latin-1")).encode("latin-1"), header_mode)
            key = await _key(dns, selector, domain)
            if key is None:
                out.append(DkimResult(domain, selector, "permerror", "no key"))
                continue
            kind, material = key
            if kind == "revoked":
                out.append(DkimResult(domain, selector, "fail", "key revoked"))
                continue
            if (kind == "ed25519") != (algorithm == "ed25519-sha256"):
                out.append(DkimResult(domain, selector, "permerror", "key type"))
                continue
            ok = _verify(kind, material, base64.b64decode(tags["b"] + "=" * (-len(tags["b"]) % 4)), data)
            out.append(DkimResult(domain, selector, "pass" if ok else "fail", "" if ok else "signature"))
        except DnsError:
            out.append(DkimResult(domain, selector, "temperror", "dns"))
        except (ValueError, TypeError) as exc:
            out.append(DkimResult(domain, selector, "permerror", type(exc).__name__))
    return out


# ---------------------------------------------------------------- DMARC

def header_from(raw: bytes) -> str:
    fields, _ = split_message(raw)
    found = [f for f in fields if _name(f) == "from"]
    if len(found) != 1:
        return ""  # none or several From fields: DMARC cannot be evaluated (RFC 7489, 6.6.1)
    return _address_domain(found[0].split(b":", 1)[1].decode("utf-8", "replace"))


async def dmarc(dns: Resolver, from_domain: str, spf_result: str, spf_domain: str, dkim_results: list[DkimResult]) -> tuple[str, str]:
    """(result, policy) for the From domain with relaxed alignment by default."""
    if not from_domain:
        return "permerror", "none"
    record = None
    for name in dict.fromkeys([from_domain, organizational(from_domain)]):
        values = [v for v in await dns.query(f"_dmarc.{name}", "TXT") if v.lower().replace(" ", "").startswith("v=dmarc1")]
        if values:
            record = (name, _tags(values[0]))
            break
    if record is None:
        return "none", "none"
    name, tags = record
    policy = tags.get("sp", tags.get("p", "none")) if name != from_domain else tags.get("p", "none")
    policy = policy.lower() if policy.lower() in ("none", "quarantine", "reject") else "none"
    strict_spf, strict_dkim = tags.get("aspf", "r").lower() == "s", tags.get("adkim", "r").lower() == "s"

    def aligned(domain: str, strict: bool) -> bool:
        domain = domain.lower()
        return domain == from_domain if strict else organizational(domain) == organizational(from_domain)

    passed = (spf_result == "pass" and aligned(spf_domain, strict_spf)) or any(
        d.result == "pass" and aligned(d.domain, strict_dkim) for d in dkim_results)
    return ("pass" if passed else "fail"), policy


async def authenticate(dns: Resolver, raw: bytes, ip: str, mail_from: str, helo: str) -> AuthResults:
    results = AuthResults()
    results.spf, results.spf_domain = await spf(dns, ip, mail_from, helo)
    try:
        results.dkim = await dkim(dns, raw)
    except DnsError:
        results.dkim = [DkimResult("", "", "temperror", "dns")]
    results.from_domain = header_from(raw)
    try:
        results.dmarc, results.dmarc_policy = await dmarc(dns, results.from_domain, results.spf, results.spf_domain, results.dkim)
    except DnsError:
        results.dmarc, results.dmarc_policy = "temperror", "none"
    return results
