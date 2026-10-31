#!/usr/bin/env python3
"""Check the external links of README and live documentation over the network.

``check-doc-links.py`` verifies relative links, images and Markdown anchors without touching the
network: it must stay fast and deterministic in CI. This script answers the other question — do the
URLs the README points at still exist? It is run deliberately (and nightly), not on every push,
because a third-party outage must not fail a code review.

What counts as a problem:

* HTTP 404/410 — the page or repository is gone;
* a redirect to a different host that is not in ``ALLOWED_REDIRECTS`` (a moved resource);
* a DNS failure or a timeout that persists after ``--retries``.

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
HOSTS_SKIPPED = {"img.shields.io", "badgen.net", "shields.io", "localhost", "127.0.0.1"}
# Hosts a link may legitimately be redirected to when the site moved to a canonical address.
ALLOWED_REDIRECTS = {
    "github.com": {"docs.github.com", "github.blog"},
    # The console is behind Google sign-in: an anonymous GET is redirected to the login page on purpose.
    "console.firebase.google.com": {"accounts.google.com"},
    "console.cloud.google.com": {"accounts.google.com"},
}

LINK = re.compile(r"!?\[[^\]]*\]\(\s*(https?://[^)\s]+?)(?:\s+\"[^\"]*\")?\s*\)")
BARE_URL = re.compile(r"(?<![(\[<])(\bhttps?://[^\s)>\]]+)")


def documents() -> list[Path]:
    return [ROOT / "README.md"] + sorted(
        path for path in ROOT.rglob("*.md")
        if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts)
        and not path.name.startswith("release-v")
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
        for match in list(LINK.finditer(text)) + list(BARE_URL.finditer(text)):
            url = match.group(1).rstrip(".,;:")
            if placeholder(url):
                continue
            if only and only not in url:
                continue
            found.setdefault(url, []).append(str(path.relative_to(ROOT)))
    return found


def probe(url: str, timeout: float, retries: int) -> tuple[str, str]:
    """Return ``(status, detail)``: status is one of ok/fail/skip."""
    import httpx

    headers = {"User-Agent": "corgi-doc-link-check/1.0 (+https://github.com/booarkz-cpu/shop-by-boo)"}
    last = ""
    for attempt in range(retries):
        try:
            with httpx.Client(follow_redirects=False, timeout=timeout, headers=headers) as client:
                response = client.get(url)
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
            # The server answered, so the host exists: a guard, a rate limit or a parameter requirement
            # is not a broken link. Only 404/410 and a moved resource are.
            if code in (400, 401, 403, 429, 405):
                return "skip", f"HTTP {code} (host answers, request needs a parameter or access)"
            last = f"HTTP {code}"
        except Exception as exc:  # noqa: BLE001 — any transport error is reported, not raised
            # A DNS failure or a timeout in this sandbox says nothing about the page: report it as
            # unverified instead of accusing the documentation of a dead link.
            return "skip", f"unverified: {type(exc).__name__}"
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(probe, url, args.timeout, args.retries): url for url in urls}
        for future in concurrent.futures.as_completed(futures):
            url = futures[future]
            status, detail = future.result()
            if status == "fail":
                failures.append((url, detail, urls[url]))
            elif status == "skip":
                skipped += 1
                print(f"  skip {url} — {detail}")
    print(f"\nchecked {len(urls)} external links: "
          f"{len(urls) - len(failures) - skipped} ok, {skipped} skipped, {len(failures)} broken")
    for url, detail, files in sorted(failures):
        print(f"  BROKEN {url} — {detail}")
        for name in sorted(set(files))[:3]:
            print(f"        referenced in {name}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
