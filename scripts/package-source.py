#!/usr/bin/env python3
"""Package tracked source files without local credentials or build products."""
from __future__ import annotations

import os
from datetime import datetime, timezone
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


# Compatibility floor: installed updaters cap compressed AND expanded bytes.
LEGACY_ARCHIVE_LIMIT = 80 * 1024 * 1024


def main() -> None:
    target = Path(sys.argv[1]).resolve()
    root = Path(__file__).resolve().parents[1]
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\0")
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH") or subprocess.check_output(
        ["git", "show", "-s", "--format=%ct", "HEAD"], cwd=root
    ).strip())
    timestamp = datetime.fromtimestamp(max(epoch, 315532800), timezone.utc).timetuple()[:6]
    def write_entry(archive, path, name):
        info = zipfile.ZipInfo(name, date_time=timestamp)
        info.create_system = 3
        mode = 0o100755 if path.stat().st_mode & 0o111 else 0o100644
        info.external_attr = mode << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, path.read_bytes(), compresslevel=9)
    entries = []
    for raw in sorted(filter(None, paths)):
        rel = Path(os.fsdecode(raw))
        path = root / rel
        # Review screenshots stay in GitHub. Runtime assets remain in the ZIP.
        if rel.parts[0] == "screenshots":
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if rel.name.startswith(".env") and rel.name not in {".env.example", ".env.test.example"}:
            continue
        if rel.suffix.lower() in {".apk", ".ipa", ".zip"}:
            continue
        entries.append((path, rel.as_posix()))
    template = root / "release-manifest.template.json"
    if template.is_file() and b"release-manifest.template.json" not in paths:
        entries.append((template, template.name))
    expanded = sum(path.stat().st_size for path, _ in entries)
    if expanded > LEGACY_ARCHIVE_LIMIT:
        raise SystemExit(f"Expanded release archive exceeds installed updater limit: {expanded} > {LEGACY_ARCHIVE_LIMIT}")
    with tempfile.TemporaryDirectory(dir=target.parent, prefix="release-package-") as staging:
        staged = Path(staging) / "release.zip"
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, name in entries:
                write_entry(archive, path, name)
        if staged.stat().st_size > LEGACY_ARCHIVE_LIMIT:
            raise SystemExit("Compressed release archive exceeds installed updater limit")
        os.replace(staged, target)
    print(f"Release source: {len(entries)} files, {expanded} expanded bytes; screenshots/ remain in GitHub")


if __name__ == "__main__":
    main()
