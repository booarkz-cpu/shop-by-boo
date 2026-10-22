#!/usr/bin/env python3
"""Download the latest GitHub release zip and check its SHA-256.

Refuses redirects off the official repository, zip entries that escape the
destination, and a release that is not newer than the installed version.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "booarkz-cpu/shop-by-boo"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024


def version_tuple(value: str) -> tuple:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z0-9.-]+))?", value)
    if not match:
        raise ValueError("Invalid version")
    base = tuple(int(piece) for piece in match.groups()[:3])
    suffix = match.group(4)
    preview = re.fullmatch(r"(alpha|beta|rc)(?:[.-]?(\d+))?", suffix or "")
    if preview:
        return base + ({"alpha": 0, "beta": 1, "rc": 2}[preview.group(1)], int(preview.group(2) or 0))
    # Historical -realise/-audited labels denote stable legacy versions.
    return base + (3, 0)


def current_version(app_dir: Path) -> str:
    text = (app_dir / "backend/app/main.py").read_text(encoding="utf-8")
    if "MAIN_PY_ASSEMBLED_FROM_PARTS" in text:
        text = (app_dir / "backend/app/main_src/part-00").read_text(encoding="utf-8")
    marker = 'APP_VERSION = "'
    start = text.index(marker) + len(marker)
    return text[start:text.index('"', start)]


def current_distribution(app_dir: Path) -> str:
    runtime = current_version(app_dir)
    manifest_path = app_dir / "release-manifest.template.json"
    if not manifest_path.is_file():
        return runtime
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Invalid distribution manifest")
    tag = manifest.get("distribution_tag")
    if not tag:
        return runtime
    if not isinstance(tag, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Invalid installed distribution tag")
    if manifest.get("version") != runtime:
        raise ValueError("Distribution manifest does not match the API version")
    return tag[1:]


def tag_commit(tag: str) -> str:
    payload = fetch_json(f"https://api.github.com/repos/{REPO}/git/ref/tags/{tag}")
    for _ in range(5):
        obj = payload.get("object") if isinstance(payload, dict) else None
        if not isinstance(obj, dict) or not re.fullmatch(r"[0-9a-f]{40}", str(obj.get("sha") or "")):
            fail("Invalid GitHub tag object")
        if obj.get("type") == "commit":
            return obj["sha"]
        if obj.get("type") != "tag":
            fail("Release tag does not identify a commit")
        payload = fetch_json(f"https://api.github.com/repos/{REPO}/git/tags/{obj['sha']}")
    fail("Release tag has too many annotated tag layers")


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "RemnawaveShop-Updater"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.geturl().split("/", 3)[2] != "api.github.com":
            raise SystemExit("GitHub redirect is not allowed")
        return json.load(response)


def fail(message: str) -> None:
    print(message)
    raise SystemExit(1)


def download(url: str) -> bytes:
    if not url.startswith(DOWNLOAD_PREFIX):
        fail("Release asset URL is not from this repository")
    request = urllib.request.Request(url, headers={"User-Agent": "RemnawaveShop-Updater"})
    with urllib.request.urlopen(request, timeout=120) as response:
        host = response.geturl().split("/", 3)[2]
        if host not in {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}:
            fail("Release download host is not allowed")
        blob = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(blob) > MAX_ARCHIVE_BYTES:
        fail("Release archive is too large")
    return blob


def safe_extract(blob: bytes, destination: Path) -> None:
    if len(blob) > MAX_ARCHIVE_BYTES:
        fail("Release archive is too large")
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        total = 0
        seen = set()
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            mode = (info.external_attr >> 16) & 0xFFFF
            parts = Path(name).parts
            if (stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))):
                fail("Release archive contains a link or special file")
            if not name or name.startswith("/") or ".." in parts or "." in parts or ":" in parts[0]:
                fail("Release archive contains an unsafe path")
            canonical = name.rstrip("/")
            if canonical in seen:
                fail("Release archive contains duplicate paths")
            seen.add(canonical)
            total += info.file_size
            if total > MAX_ARCHIVE_BYTES:
                fail("Release archive is too large")
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/") or not name.strip("/"):
                continue
            target = (destination / name).resolve()
            root = destination.resolve()
            if target != root and root not in target.parents:
                fail("Release archive contains an unsafe path")
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(info) as source, target.open("wb") as handle:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_ARCHIVE_BYTES:
                        fail("Release archive is too large")
                    handle.write(chunk)
    if (destination / "backend/app/main.py").is_file():
        return
    children = [path for path in destination.iterdir() if path.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir() and (children[0] / "backend/app/main.py").is_file():
        nested = children[0]
        for item in list(nested.iterdir()):
            target = destination / item.name
            if target.exists():
                fail("Release archive layout is unsafe")
            item.rename(target)
        nested.rmdir()


def main() -> None:
    app_dir = Path(sys.argv[1]).resolve()
    stage = Path(sys.argv[2]).resolve()
    installed = current_distribution(app_dir)
    requested = os.environ.get('RELEASE_TAG', '').strip()
    if requested and not re.fullmatch(r'v\d+\.\d+\.\d+', requested):
        fail('RELEASE_TAG must be an exact stable tag such as v28.10.0')
    payload = fetch_json(f'https://api.github.com/repos/{REPO}/releases/tags/{requested}' if requested else API)
    if payload.get('draft') or payload.get('prerelease'):
        fail('Production updater refuses draft and prerelease releases')
    tag = str(payload.get("tag_name") or "")
    if requested and tag != requested:
        fail('Requested release tag does not match GitHub response')
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        fail("Invalid release tag")
    latest = tag.lstrip("v")
    if version_tuple(latest) <= version_tuple(installed):
        print(f"Установлена актуальная версия {installed}")
        raise SystemExit(0)
    assets = {item.get("name"): item.get("browser_download_url") for item in payload.get("assets") or []}
    zip_name = f"remnawave_vpn_shop_v{latest.replace('.', '_')}_full_release.zip"
    sha_name = zip_name + ".sha256"
    if (assets.get(zip_name) != f"{DOWNLOAD_PREFIX}{tag}/{zip_name}"
            or assets.get(sha_name) != f"{DOWNLOAD_PREFIX}{tag}/{sha_name}"):
        fail("В релизе нет архива и SHA-256 для указанной версии")
    blob = download(str(assets[zip_name]))
    checksum = download(str(assets[sha_name])).decode("utf-8").strip()
    match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?" + re.escape(zip_name), checksum)
    if not match:
        fail("Некорректный SHA-256 или имя архива")
    digest_line = match.group(1).lower()
    actual = hashlib.sha256(blob).hexdigest()
    if actual != digest_line:
        fail("SHA-256 релиза не совпал")
    stage.mkdir(parents=True, exist_ok=True)
    safe_extract(blob, stage)
    try:
        extracted = current_version(stage)
    except (OSError, ValueError):
        fail("В архиве нет версии приложения")
    try:
        distribution = current_distribution(stage)
    except (OSError, ValueError):
        fail("Некорректная версия дистрибутива в архиве")
    if distribution != latest:
        fail("Версия дистрибутива в архиве не совпадает с тегом релиза")
    if distribution != extracted:
        manifest_name = zip_name.removesuffix(".zip") + "_manifest.json"
        if assets.get(manifest_name) != f"{DOWNLOAD_PREFIX}{tag}/{manifest_name}":
            fail("В релизе нет манифеста дистрибутива")
        try:
            manifest = json.loads(download(str(assets[manifest_name])))
        except (ValueError, UnicodeDecodeError):
            fail("Некорректный манифест дистрибутива")
        if not isinstance(manifest, dict) or any((
            manifest.get("distribution_tag") != tag,
            manifest.get("version") != extracted,
            manifest.get("artifact") != zip_name,
            manifest.get("sha256") != actual,
            manifest.get("commit") != tag_commit(tag),
        )):
            fail("Манифест дистрибутива не совпадает с архивом или коммитом тега")
    print(latest)


if __name__ == "__main__":
    main()
