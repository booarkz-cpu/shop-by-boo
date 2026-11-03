"""Release files for node modules (v28.70.0, stage 12): Xray core (XTLS/Xray-core) and wgcf (ViRb3/wgcf).

The shop asks GitHub's releases API for the version and takes the SHA-256 GitHub computed for each file
(``assets[].digest``). The plan fixes URL and SHA-256 when it is made, the administrator approves exactly that, and
the server refuses a file with another checksum. A release without a published digest is refused."""
from __future__ import annotations

import asyncio
import os
import re

import httpx

from . import rw_plan

API = "https://api.github.com/repos"
TAG = re.compile(r"^v\d{1,3}\.\d{1,3}\.\d{1,3}$")
SHA = re.compile(r"^sha256:([0-9a-f]{64})$")


class ReleaseError(RuntimeError):
    """Shown to the administrator."""


async def _release(repo: str, tag: str | None, attempts: int = 3) -> dict:
    url = f"{API}/{repo}/releases/" + (f"tags/{tag}" if tag else "latest")
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GH_API_TOKEN"):  # optional: a higher rate limit (CI passes its job token)
        headers["Authorization"] = f"Bearer {os.environ['GH_API_TOKEN']}"
    answer = None
    for attempt in range(attempts):  # a dropped TLS handshake or a 5xx is retried, a 404 is not
        try:
            async with httpx.AsyncClient(timeout=20, headers=headers) as client:
                answer = await client.get(url)
        except httpx.HTTPError as exc:
            if attempt == attempts - 1:
                raise ReleaseError(f"GitHub недоступен: {type(exc).__name__}") from exc
            await asyncio.sleep(2 * (attempt + 1))
            continue
        if answer.status_code < 500 or attempt == attempts - 1:
            break
        await asyncio.sleep(2 * (attempt + 1))
    if answer.status_code == 404:
        raise ReleaseError(f"В {repo} нет релиза {tag or 'latest'}")
    if answer.status_code != 200:
        raise ReleaseError(f"GitHub ответил {answer.status_code}")
    return answer.json()


def _asset(release: dict, repo: str, name: str) -> dict[str, str]:
    for asset in release.get("assets") or []:
        if asset.get("name") != name:
            continue
        url = asset.get("browser_download_url") or ""
        if not url.startswith(f"https://github.com/{repo}/releases/download/"):
            raise ReleaseError(f"Неожиданный адрес файла {name}")
        digest = SHA.match(asset.get("digest") or "")
        if not digest:
            raise ReleaseError(f"GitHub не опубликовал SHA-256 для {name}: такой файл не ставится")
        return {"url": url, "sha256": digest.group(1)}
    raise ReleaseError(f"В релизе нет файла {name}")


async def fetch(repo: str, tag: str | None) -> dict:
    """Seam for tests."""
    return await _release(repo, tag)


async def xray_core(tag: str | None) -> tuple[str, dict[str, dict[str, str]]]:
    if tag and not TAG.match(tag):
        raise ReleaseError("Версия ядра вида v25.10.15")
    release = await fetch("XTLS/Xray-core", tag)
    version = release.get("tag_name") or ""
    if not TAG.match(version):
        raise ReleaseError(f"Неожиданная версия {version!r}")
    return version, {arch: _asset(release, "XTLS/Xray-core", name) for arch, name in rw_plan.XRAY_ASSETS.items()}


async def wgcf() -> tuple[str, dict[str, dict[str, str]]]:
    release = await fetch("ViRb3/wgcf", None)
    version = release.get("tag_name") or ""
    if not TAG.match(version):
        raise ReleaseError(f"Неожиданная версия wgcf {version!r}")
    plain = version.lstrip("v")
    return version, {arch: _asset(release, "ViRb3/wgcf", f"wgcf_{plain}_linux_{goarch}") for arch, goarch in rw_plan.WGCF_ARCH.items()}
