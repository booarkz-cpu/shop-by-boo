#!/usr/bin/env python3
"""Record the source commit in the AAR and verify the actual JNI payload of assembled APKs."""
import argparse
import hashlib
import re
from pathlib import Path
from zipfile import BadZipFile, ZipFile, ZipInfo, is_zipfile

MARKER = "assets/corgi-xray.commit"
# ELF class and machine number from the Android ABI.
ABIS = {"armeabi-v7a": (1, 40), "arm64-v8a": (2, 183), "x86": (1, 3), "x86_64": (2, 62)}


def revision(text: str) -> bytes:
    if not re.fullmatch("[0-9a-f]{40}", text):
        raise ValueError("expected a full lowercase source commit")
    return (text + "\n").encode("ascii")


def stamp(aar: Path, commit: str) -> None:
    marker = revision(commit)
    if not is_zipfile(aar):
        raise ValueError(f"{aar}: expected an AAR from gomobile")
    with ZipFile(aar, "a") as archive:
        if MARKER in archive.namelist():
            raise ValueError(f"{aar} already has an Xray source marker")
        # ZipInfo uses a fixed timestamp. Independent builds of the same AAR stay comparable.
        archive.writestr(ZipInfo(MARKER), marker)
    payload(aar, "jni", marker)


def payload(path: Path, prefix: str, expected: bytes) -> dict[str, str]:
    with ZipFile(path) as archive:
        names = archive.namelist()
        if names.count(MARKER) != 1 or archive.read(MARKER) != expected:
            raise ValueError(f"{path}: missing, ambiguous or wrong source commit")
        entries = [name for name in names if name.startswith(prefix + "/") and name.endswith("/libgojni.so")]
        required = [f"{prefix}/{abi}/libgojni.so" for abi in ABIS]
        if sorted(entries) != sorted(required):
            raise ValueError(f"{path}: unexpected JNI entries {entries}")
        digests = {}
        for abi, (elf_class, machine) in ABIS.items():
            with archive.open(f"{prefix}/{abi}/libgojni.so") as lib:
                header = lib.read(20)
                if (len(header) != 20 or header[:4] != b"\x7fELF" or header[4] != elf_class
                        or header[5] != 1 or int.from_bytes(header[18:20], "little") != machine):
                    raise ValueError(f"{path}: wrong ELF architecture for {abi}")
                digest = hashlib.sha256(header)
                for chunk in iter(lambda: lib.read(1024 * 1024), b""):
                    digest.update(chunk)
                digests[abi] = digest.hexdigest()
        return digests


def verify(aar: Path, apks: list[Path], commit: str) -> None:
    expected = revision(commit)
    original = payload(aar, "jni", expected)
    for apk in apks:
        native = payload(apk, "lib", expected)
        for abi, sha in original.items():
            if native[abi] != sha:
                raise ValueError(f"{apk}: {abi}/libgojni.so differs from {aar}")
            print(f"{apk.name} {abi} {commit} {sha}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stamp", "verify"))
    parser.add_argument("commit")
    parser.add_argument("aar", type=Path)
    parser.add_argument("apks", nargs="*", type=Path)
    args = parser.parse_args()
    if (args.action == "verify") != bool(args.apks):
        parser.error("verify requires at least one APK; stamp accepts only the AAR")
    try:
        if args.action == "stamp":
            stamp(args.aar, args.commit)
        else:
            verify(args.aar, args.apks, args.commit)
    except (OSError, ValueError, BadZipFile) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
