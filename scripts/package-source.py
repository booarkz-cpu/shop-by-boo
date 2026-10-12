#!/usr/bin/env python3
"""Package tracked source files without local credentials or build products."""
from __future__ import annotations

import os
from datetime import datetime, timezone
import subprocess
import sys
import zipfile
from pathlib import Path


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
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for raw in sorted(filter(None, paths)):
            rel = Path(os.fsdecode(raw))
            path = root / rel
            if path.is_symlink() or not path.is_file():
                continue
            if rel.name.startswith(".env") and rel.name != ".env.example" and rel.name != ".env.test.example":
                continue
            if rel.suffix.lower() in {".apk", ".ipa", ".zip"}:
                continue
            write_entry(archive, path, rel.as_posix())
        template = root / "release-manifest.template.json"
        if template.is_file() and b"release-manifest.template.json" not in paths:
            write_entry(archive, template, template.name)


if __name__ == "__main__":
    main()
