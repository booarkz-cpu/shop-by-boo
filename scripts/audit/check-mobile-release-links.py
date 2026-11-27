#!/usr/bin/env python3
"""Check the mobile downloads and checksums offered on the shop landing pages."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "booarkz-cpu/shop-by-boo"
LINK = re.compile(r"https://github\.com/booarkz-cpu/shop-by-boo/releases/latest/download/([A-Za-z0-9._-]+)")
TAGGED_IOS = re.compile(
    r"https://github\.com/booarkz-cpu/shop-by-boo/releases/download/(v\d+\.\d+\.\d+)/"
    r"(corgi_lusi_ios_(user|admin)_(\d+_\d+_\d+)_(unsigned\.ipa|simulator\.zip))"
)
READMES = [
    ROOT / "README.md",
    ROOT / "README.en.md",
    ROOT / "README.uk.md",
]


class RedirectRecorder(urllib.request.HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.locations: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.locations.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def produced_apks() -> set[str]:
    build = (ROOT / "scripts/build-android-apk.sh").read_text()
    names = set(re.findall(r'stable="([a-z0-9.-]+\.apk)"', build))
    names |= set(re.findall(r"cp \"\$client\" dist/mobile/([a-z0-9.-]+\.apk)", (ROOT / ".github/workflows/mobile-release.yml").read_text()))
    return names


def table_packages(section: str, page: str) -> list[str]:
    packages = []
    for row in section.splitlines():
        if not row.startswith("|"):
            continue
        links = re.findall(r"\]\(([^)\s]+)\)", row)
        for index in range(0, len(links), 2):
            package = links[index]
            if index + 1 >= len(links) or links[index + 1] != package + ".sha256":
                raise ValueError(f"{page}: expected the matching SHA-256 link next to {package}")
            packages.append(package)
    return packages


def readme_downloads(text: str, page: str, apks: set[str]) -> set[tuple[str, str]]:
    sections = re.split(r"^## .+$", text, maxsplit=2, flags=re.M)
    parts = re.split(r"^### (.+)$", sections[1], flags=re.M) if len(sections) > 1 else []
    platforms = dict(zip(parts[1::2], parts[2::2], strict=True))
    if set(platforms) != {"Android", "iOS"} or len(parts) != 5:
        raise ValueError(f"{page}: expected Android and iOS in the first download section")

    android = table_packages(platforms["Android"], page)
    expected = {f"https://github.com/{REPOSITORY}/releases/latest/download/{apk}" for apk in apks}
    if len(android) != len(expected) or set(android) != expected:
        raise ValueError(f"{page}: expected one link for each APK from the release workflow")

    ios = set()
    variants = []
    versions = set()
    for url in table_packages(platforms["iOS"], page):
        match = TAGGED_IOS.fullmatch(url)
        if not match:
            raise ValueError(f"{page}: invalid iOS release link {url}")
        tag, name, role, version, kind = match.groups()
        ios.add((tag, name))
        variants.append((role, kind))
        versions.add((tag, version))
    expected_variants = {(role, kind) for role in ("user", "admin") for kind in ("unsigned.ipa", "simulator.zip")}
    if len(variants) != len(expected_variants) or set(variants) != expected_variants or len(versions) != 1:
        raise ValueError(f"{page}: expected a device and simulator build per app from the same release")
    return ios


def verify_checksum(asset: dict, checksum: dict, url: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "shop-by-boo-release-link-audit"})
    with urllib.request.urlopen(request, timeout=30) as response:
        record = response.read(1025)
    if len(record) > 1024 or "sha256:" + hashlib.sha256(record).hexdigest() != checksum["digest"]:
        raise ValueError(f"invalid checksum file for {asset['name']}")
    fields = record.decode("ascii").split()
    if len(fields) != 2 or fields[1].removeprefix("*") != asset["name"] or "sha256:" + fields[0] != asset["digest"]:
        raise ValueError(f"checksum does not match {asset['name']}")


def get_release(ref: str) -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "shop-by-boo-release-link-audit"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com/repos/{REPOSITORY}/releases/{ref}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def resolve_permanent_download(url: str) -> tuple[int, str, list[str]]:
    recorder = RedirectRecorder()
    opener = urllib.request.build_opener(recorder)
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "shop-by-boo-release-link-audit"})
    with opener.open(request, timeout=60) as response:
        return response.status, response.geturl(), recorder.locations


def verify() -> dict:
    apks = produced_apks()
    pages = [readme_downloads(doc.read_text(), doc.name, apks) for doc in READMES]
    if any(ios != pages[0] for ios in pages[1:]):
        raise ValueError("localized README pages offer different iOS downloads")
    for doc in sorted((ROOT / "docs/wiki").glob("*/Mobile.md")):
        if set(LINK.findall(doc.read_text())) != apks:
            raise ValueError(f"{doc.relative_to(ROOT)}: APK links differ from the release workflow")

    release = get_release("latest")
    if release["draft"] or release["prerelease"]:
        raise ValueError("the latest release is not a published stable release")
    tag = release["tag_name"]
    if not re.fullmatch(r"v[0-9]+(?:\.[0-9]+){2}", tag):
        raise ValueError(f"unexpected release tag: {tag!r}")
    assets = {asset["name"]: asset for asset in release["assets"]}

    verified = []
    for name in sorted(apks):
        if name not in assets:
            raise ValueError(f"{name} is absent from release {tag}")
        asset = assets[name]
        if asset["size"] <= 0:
            raise ValueError(f"{name} is empty")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", asset.get("digest") or ""):
            raise ValueError(f"{name} has no GitHub SHA-256 digest")
        permanent = f"https://github.com/{REPOSITORY}/releases/latest/download/{name}"
        status, final_url, redirects = resolve_permanent_download(permanent)
        if status != 200:
            raise ValueError(f"{permanent} returned HTTP {status}")
        if not redirects or redirects[0] != asset["browser_download_url"]:
            raise ValueError(f"{permanent} did not redirect to the {tag} asset")
        if final_url == permanent:
            raise ValueError(f"{permanent} was not resolved")
        verify_checksum(asset, assets[name + ".sha256"], permanent + ".sha256")
        verified.append({"name": name, "size": asset["size"], "digest": asset["digest"]})

    # iOS filenames contain the app version and point to a specific distribution tag.
    releases = {tag: assets}
    ios = []
    for pinned_tag, name in sorted(pages[0]):
        if pinned_tag not in releases:
            pinned = get_release("tags/" + pinned_tag)
            if pinned["draft"] or pinned["prerelease"] or pinned["tag_name"] != pinned_tag:
                raise ValueError(f"expected published release {pinned_tag}")
            releases[pinned_tag] = {item["name"]: item for item in pinned["assets"]}
        files = releases[pinned_tag]
        asset = files[name]
        status, _, _ = resolve_permanent_download(asset["browser_download_url"])
        if status != 200 or asset["size"] <= 0:
            raise ValueError(f"{pinned_tag}/{name} is unavailable")
        checksum = files[name + ".sha256"]
        verify_checksum(asset, checksum, checksum["browser_download_url"])
        ios.append({"name": name, "size": asset["size"], "digest": asset["digest"]})

    return {"tag": tag, "assets": verified, "ios_assets": ios}


def main() -> int:
    result = verify()
    packages = result["assets"] + result["ios_assets"]
    total = sum(asset["size"] for asset in packages)
    print(f"Mobile release links: PASS; tag={result['tag']}; packages={len(packages)}; bytes={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
