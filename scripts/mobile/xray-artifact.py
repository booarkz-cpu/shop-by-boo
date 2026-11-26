#!/usr/bin/env python3
"""Record the source commit in the AAR and verify the actual JNI payload of assembled APKs."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from zipfile import BadZipFile, ZipFile, ZipInfo, is_zipfile

MARKER = "assets/corgi-xray.commit"
# ELF class and machine number from the Android ABI.
ABIS = {"armeabi-v7a": (1, 40), "arm64-v8a": (2, 183), "x86": (1, 3), "x86_64": (2, 62)}


def revision(text: str) -> bytes:
    if not re.fullmatch("[0-9a-f]{40}", text):
        raise ValueError("expected a full lowercase source commit")
    return (text + "\n").encode("ascii")


def module_version(info: dict, commit: str) -> str:
    revision(commit)
    name = "github.com/2dust/AndroidLibXrayLite"
    origin = info.get("Origin") or {}
    version = info.get("Version", "")
    if (info.get("Path") != name or origin.get("VCS") != "git" or origin.get("URL") != f"https://{name}"
            or origin.get("Hash") != commit or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.+-]+)?", version)
            or not re.fullmatch(r"h1:[A-Za-z0-9+/]{43}=", info.get("Sum", ""))):
        raise ValueError("Go module does not identify the pinned Android wrapper and checksum")
    return version


def check_replacements(mod: dict) -> None:
    for entry in mod.get("Replace") or []:
        if entry["Old"]["Path"] == "github.com/2dust/AndroidLibXrayLite" or not entry["New"].get("Version"):
            raise ValueError("Go module replacement would substitute the wrapper or embed a local path")


def check_linked_module(build: dict, info: dict) -> None:
    wrappers = [dep for dep in build.get("Deps", []) if dep.get("Path") == info["Path"]]
    if (len(wrappers) != 1 or wrappers[0].get("Replace") or wrappers[0].get("Version") != info["Version"]
            or wrappers[0].get("Sum") != info["Sum"]):
        raise ValueError("ELF linked wrapper differs from the resolved version and checksum")


def check_native_metadata(aar: Path, commit: str, info: dict) -> None:
    module_version(info, commit)
    with ZipFile(aar) as archive, tempfile.TemporaryDirectory() as directory:
        elf = Path(directory) / "libgojni.so"
        for abi in ABIS:
            with archive.open(f"jni/{abi}/libgojni.so") as src, elf.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            build = json.loads(subprocess.check_output(["go", "version", "-m", "-json", str(elf)], text=True))
            check_linked_module(build, info)


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
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("stamp", "verify", "module-version"):
        cmd = commands.add_parser(action)
        cmd.add_argument("commit")
        if action == "module-version":
            cmd.add_argument("metadata", type=Path)
            cmd.add_argument("modfile", type=Path)
        else:
            cmd.add_argument("aar", type=Path)
            if action == "stamp":
                cmd.add_argument("--module-info", type=Path)
            if action == "verify":
                cmd.add_argument("apks", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "stamp":
            if args.module_info:
                check_native_metadata(args.aar, args.commit, json.loads(args.module_info.read_text()))
            stamp(args.aar, args.commit)
        elif args.action == "verify":
            verify(args.aar, args.apks, args.commit)
        else:
            check_replacements(json.loads(args.modfile.read_text()))
            print(module_version(json.loads(args.metadata.read_text()), args.commit))
    except (OSError, KeyError, ValueError, BadZipFile, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
