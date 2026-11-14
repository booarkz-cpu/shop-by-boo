#!/usr/bin/env python3
"""v28.101.0 (stage 20, N11): the Xray core of «Корги Люси: клиент» follows AndroidLibXrayLite by itself.

The workflow «Xray core watch» runs this once a day with the latest release of 2dust/AndroidLibXrayLite (its tag and
the commit the tag points at). When the commit differs from the one pinned in scripts/mobile/build-xray-aar.sh, the
files are rewritten for a pull request: the new commit, the client's versionCode + 1 and the next patch version, and a
CHANGELOG line of the client. The pull request then goes through the whole CI (the AAR is built from the new commit and
the real VPN runs on an emulator) and is merged only when every check is green — the owner's rule; the app updates
itself from the next shop release.

    python3 scripts/mobile/xray-core-watch.py --tag v26.1.18 --commit <40 hex> [--write]
prints «up-to-date» or «update <old> <new> <client version>» (and with --write changes the files)."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AAR = ROOT / "scripts/mobile/build-xray-aar.sh"
GRADLE = ROOT / "apps/vpn-client/android/app/build.gradle.kts"
NOTES = ROOT / "docs/ru/new/ANDROID_CLIENT_APP.md"
COMMIT_LINE = re.compile(r'^COMMIT="\$\{XRAY_AAR_COMMIT:-([0-9a-f]{40})\}"$', re.M)
TAG = re.compile(r"^v?\d{1,4}\.\d{1,4}\.\d{1,4}$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def current_commit(script: str) -> str:
    found = COMMIT_LINE.search(script)
    if not found:
        raise ValueError("no pinned COMMIT in build-xray-aar.sh")
    return found.group(1)


def set_commit(script: str, commit: str) -> str:
    if not SHA.match(commit):
        raise ValueError("commit: 40 hex")
    return COMMIT_LINE.sub(f'COMMIT="${{XRAY_AAR_COMMIT:-{commit}}}"', script, count=1)


def bump_client(gradle: str) -> tuple[str, str]:
    """versionCode + 1 and the next patch version (1.6.0 → 1.6.1); returns the new text and the new version."""
    code = re.search(r"versionCode = (\d+)", gradle)
    name = re.search(r'versionName = "(\d+)\.(\d+)\.(\d+)"', gradle)
    if not code or not name:
        raise ValueError("no versionCode / versionName")
    major, minor, patch = (int(x) for x in name.groups())
    version = f"{major}.{minor}.{patch + 1}"
    gradle = gradle.replace(code.group(0), f"versionCode = {int(code.group(1)) + 1}", 1)
    return gradle.replace(name.group(0), f'versionName = "{version}"', 1), version


def note(notes: str, version: str, tag: str, commit: str) -> str:
    """A section of the client's notes above the latest one."""
    entry = (f"## Версия {version} — ядро Xray из AndroidLibXrayLite {tag}\n\n"
             f"- Ядро обновлено автоматически (N11): AndroidLibXrayLite {tag}, коммит `{commit}`; проверено сборкой AAR, "
             "unit-тестами и настоящим VPN на эмуляторе.\n\n")
    first = notes.find("\n## ")
    return notes[: first + 1] + entry + notes[first + 1:] if first >= 0 else notes + "\n" + entry


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tag", required=True)
    p.add_argument("--commit", required=True)
    p.add_argument("--write", action="store_true")
    a = p.parse_args(argv)
    if not TAG.match(a.tag) or not SHA.match(a.commit):
        print("bad tag or commit", file=sys.stderr)
        return 2
    script = AAR.read_text()
    old = current_commit(script)
    if old == a.commit:
        print("up-to-date")
        return 0
    gradle, version = bump_client(GRADLE.read_text())
    if a.write:
        AAR.write_text(set_commit(script, a.commit))
        GRADLE.write_text(gradle)
        NOTES.write_text(note(NOTES.read_text(), version, a.tag, a.commit))
    print(f"update {old} {a.commit} {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
