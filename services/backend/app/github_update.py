"""Read the latest GitHub release for this repository.

The API reports whether a newer tag exists. The host script
`scripts/update-from-github.sh` downloads that release, checks SHA-256
and applies it. The API process does not extract archives.
"""
from __future__ import annotations

import re

from fastapi import HTTPException

GITHUB_REPO = "booarkz-cpu/shop-by-boo"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{GITHUB_REPO}/releases/download/"


def version_tuple(value: str) -> tuple:
    numbers = []
    for piece in value.lstrip("v").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        numbers.append(int(digits or 0))
    return tuple(numbers)


def release_status(current: str, payload: dict, current_distribution: str | None = None) -> dict:
    tag = str(payload.get("tag_name") or "")
    valid_tag = bool(re.fullmatch(r"v\d+\.\d+\.\d+", tag)) and not payload.get("draft") and not payload.get("prerelease")
    latest = tag[1:] if valid_tag else ""
    zip_name = f"remnawave_vpn_shop_v{latest.replace('.', '_')}_full_release.zip"
    required = {zip_name, zip_name + ".sha256"} if valid_tag else set()
    if valid_tag and current_distribution and latest != current:
        required.add(zip_name.removesuffix(".zip") + "_manifest.json")
    available = {}
    for item in payload.get("assets") or []:
        url = str(item.get("browser_download_url") or "")
        name = str(item.get("name") or "")
        if name not in required or url != f"{DOWNLOAD_PREFIX}{tag}/{name}":
            continue
        available[name] = {"name": name, "url": url}
    assets = [available[name] for name in (zip_name, zip_name + ".sha256") if name in available] if valid_tag else []
    return {
        "repository": GITHUB_REPO,
        "current": current,
        "current_tag": current_distribution or f"v{current}",
        "latest": latest,
        "tag": tag,
        "update_available": len(available) == len(required) and len(assets) == 2 and version_tuple(latest) > version_tuple(current_distribution or current),
        "assets": assets,
        "apply_command": "sudo bash /opt/vpn-shop/scripts/update-from-github.sh",
    }


async def fetch_latest_release() -> dict:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = await client.get(
                GITHUB_API,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "RemnawaveShop-Updater"},
            )
    except Exception:
        raise HTTPException(502, "GitHub не ответил")
    if response.status_code != 200:
        raise HTTPException(502, "GitHub не ответил")
    data = response.json()
    if not isinstance(data, dict) or not data.get("tag_name"):
        raise HTTPException(502, "GitHub не ответил")
    return data
