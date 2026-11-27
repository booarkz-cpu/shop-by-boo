#!/usr/bin/env python3
"""Compare the release APK's declared package and version with its Gradle project."""

import argparse
import os
import re
import subprocess
from pathlib import Path


def check_version(gradle: str, badging: str) -> int:
    package = next((line for line in badging.splitlines() if line.startswith("package: ")), "")
    fields = dict(re.findall(r"\b(name|versionCode|versionName)='([^']*)'", package))
    for setting, field, pattern in (
        ("applicationId", "name", r'"([\w.]+)"'),
        ("versionName", "versionName", r'"(\d+\.\d+\.\d+)"'),
        ("versionCode", "versionCode", r"([1-9]\d*)"),
    ):
        values = re.findall(rf"^\s*{setting}\s*=\s*{pattern}[ \t]*$", gradle, re.MULTILINE)
        if len(values) != 1 or values[0] != fields.get(field):
            raise ValueError(f"{setting}: expected {values} from Gradle, found {fields.get(field)!r} in APK")
    return int(fields["versionCode"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gradle", type=Path)
    parser.add_argument("apk", type=Path)
    args = parser.parse_args()
    aapt = Path(os.environ["ANDROID_HOME"]) / "build-tools/35.0.0/aapt"
    result = subprocess.run([aapt, "dump", "badging", args.apk], capture_output=True, text=True, check=True)
    print(check_version(args.gradle.read_text(), result.stdout))


if __name__ == "__main__":
    main()
