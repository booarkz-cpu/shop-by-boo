#!/usr/bin/env python3
"""Check the external links of README and live documentation over the network.

``check-doc-links.py`` verifies relative links, images and Markdown anchors without touching the
network: it must stay fast and deterministic in CI. This script answers the other question — do the
URLs the README points at still exist? It is run deliberately (and nightly), not on every push,
because a third-party outage must not fail a code review.

What counts as a problem:

* HTTP 404/410 — the page or repository is gone;
* a redirect to a different host that is not in ``ALLOWED_REDIRECTS`` (a moved resource);
* an unexpected HTTP status that persists after ``--retries``.

Individual transport failures are reported as unverified. An unusable client or a run in which no
server returned an HTTP response exits with status 2.

Badge images (``img.shields.io``) and ``example.com``/``*.example.*``/``*.ДОМЕН`` placeholders are
skipped: they are documentation fixtures, not links to check.

    python scripts/check-external-links.py            # report, exit 1 on hard failures
    python scripts/check-external-links.py --timeout 20 --retries 3
    python scripts/check-external-links.py --only github.com
"""
from __future__ import annotations

import argparse
import concurrent.futures
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"node_modules", ".git", "dist", ".next", "archive"}
# The owner's prompts are kept word for word, and the register quotes them: their links are the owner's own
# (a private repository answers 404 to an anonymous request) and are not ours to fix.
VERBATIM = ("docs/prompts/", "docs/REQUIREMENTS_MASTER_REGISTER.md")
HOSTS_SKIPPED = {"img.shields.io", "badgen.net", "shields.io", "localhost", "127.0.0.1"}
# Hosts a link may legitimately be redirected to when the site moved to a canonical address.
ALLOWED_REDIRECTS = {
    "github.com": {"docs.github.com", "github.blog"},
    # The console is behind Google sign-in: an anonymous GET is redirected to the login page on purpose.
    "console.firebase.google.com": {"accounts.google.com"},
    "console.cloud.google.com": {"accounts.google.com"},
}

LINK = re.compile(r"!?\[[^\]]*\]\(\s*(https?://[^)\s]+?)(?:\s+\"[^\"]*\")?\s*\)")
# A quote ends a bare URL: links inside JSON or code samples ("probeUrl": "https://…") are read without it.
BARE_URL = re.compile(r"(?<![(\[<])(\bhttps?://[^\s)>\]\"']+)")


def documents() -> list[Path]:
    return [ROOT / "README.md"] + sorted(
        path for path in ROOT.rglob("*.md")
        if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts)
        and not path.name.startswith("release-v")
        and not path.relative_to(ROOT).as_posix().startswith(VERBATIM)
    )


def placeholder(url: str) -> bool:
    """A URL that documents a shape rather than pointing at a real page."""
    if any(ch in url for ch in ("<", ">", "`", "{", "}", "$", " ", "|")):
        return True
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return True
    if not host or "." not in host:
        return True
    if any(token in host for token in ("example.", "домен", "your-", "placeholder")):
        return True
    return host in HOSTS_SKIPPED


def collect(only: str) -> dict[str, list[str]]:
    """url -> the files that reference it."""
    found: dict[str, list[str]] = {}
    for path in documents():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if path == ROOT / "docs/AUTONOMOUS_ACCEPTANCE_CHECKLIST.md":
            # Each generated requirement row begins with its ID and verbatim source wording.
            # Keep checking links in its evidence and notes, as well as the document header.
            text = "\n".join(
                re.split(r"(?<!\\)\|", line, maxsplit=3)[-1] if line.startswith("| REQ-") else line
                for line in text.splitlines()
            )
        for match in list(LINK.finditer(text)) + list(BARE_URL.finditer(text)):
            url = match.group(1).rstrip(".,;:")
            if placeholder(url):
                continue
            if only and only not in url:
                continue
            found.setdefault(url, []).append(str(path.relative_to(ROOT)))
    return found


def probe(url: str, timeout: float, retries: int) -> tuple[str, str]:
    """Check one URL, keeping cookies and retries isolated from other URLs."""
    headers = {"User-Agent": "corgi-doc-link-check/1.0 (+https://github.com/booarkz-cpu/shop-by-boo)"}
    try:
        import httpx
        client = httpx.Client(follow_redirects=False, timeout=timeout, headers=headers)
    except (ImportError, ValueError) as exc:
        return "setup_error", type(exc).__name__

    last = ""
    with client:
        for attempt in range(retries):
            try:
                response = client.get(url)
            except httpx.RequestError as exc:
                if attempt + 1 == retries:
                    return "unverified", f"unverified: {type(exc).__name__}"
                continue
            code = response.status_code
            if code in (404, 410):
                return "fail", f"HTTP {code}"
            if code in (301, 302, 303, 307, 308):
                location = response.headers.get("location", "")
                source_host = urlsplit(url).hostname or ""
                target_host = urlsplit(location).hostname or source_host
                allowed = ALLOWED_REDIRECTS.get(source_host, set())
                if target_host != source_host and target_host not in allowed:
                    return "fail", f"redirects to {target_host}"
                return "ok", f"HTTP {code} → {location[:80]}"
            if 200 <= code < 400:
                return "ok", f"HTTP {code}"
            if code in (400, 401, 403, 429, 405):
                return "skip", f"HTTP {code} (host answers, request needs a parameter or access)"
            last = f"HTTP {code}"
    return "fail", last or "unreachable"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--only", default="", help="check only URLs containing this substring")
    parser.add_argument("--jobs", type=int, default=12)
    args = parser.parse_args()

    urls = collect(args.only)
    if not urls:
        print("no external links to check")
        return
    failures: list[tuple[str, str, list[str]]] = []
    skipped = 0
    unanswered = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(probe, url, args.timeout, args.retries): url for url in urls}
        for future in concurrent.futures.as_completed(futures):
            url = futures[future]
            status, detail = future.result()
            if status == "setup_error":
                parser.exit(2, f"HTTP client setup failed ({detail}). Check proxy settings and installed HTTPX transports.\n")
            if status == "fail":
                failures.append((url, detail, urls[url]))
            elif status in ("skip", "unverified"):
                skipped += 1
                unanswered += status == "unverified"
                print(f"  skip {url} — {detail}")
    print(f"\nchecked {len(urls)} external links: "
          f"{len(urls) - len(failures) - skipped} ok, {skipped} skipped, {len(failures)} broken")
    for url, detail, files in sorted(failures):
        print(f"  BROKEN {url} — {detail}")
        for name in sorted(set(files))[:3]:
            print(f"        referenced in {name}")
    if unanswered == len(urls):
        parser.exit(2, "No HTTP response from any selected URL. Check the runner network and proxy settings.\n")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
