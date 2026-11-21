"""Check both iOS destinations and their exported Swift-facing ABI using Xcode's tools."""

import argparse
import hashlib
import plistlib
import re
import subprocess
from pathlib import Path

ARCHITECTURES = {"device": {"arm64"}, "simulator": {"arm64", "x86_64"}}
EXPORTS = {
    "LibXray": {"_LibXrayInvoke"},
    "HevSocks5Tunnel": {"_hev_socks5_tunnel_main_from_str", "_hev_socks5_tunnel_quit"},
}


def ios_binaries(root, name):
    bundle = root / f"{name}.xcframework"
    with (bundle / "Info.plist").open("rb") as info:
        entries = plistlib.load(info)["AvailableLibraries"]
    result = {}
    for entry in entries:
        variant = entry.get("SupportedPlatformVariant", "device")
        if entry["SupportedPlatform"] != "ios" or variant not in ARCHITECTURES:
            continue
        if variant in result or set(entry["SupportedArchitectures"]) != ARCHITECTURES[variant]:
            raise ValueError(f"{name}: unexpected or duplicate architectures for {variant}")
        folder = bundle / entry["LibraryIdentifier"]
        binary = folder / entry["LibraryPath"]
        if binary.suffix == ".framework":
            binary /= binary.stem
        result[variant] = binary, folder / entry.get("HeadersPath", "Headers")
    if set(result) != set(ARCHITECTURES):
        raise ValueError(f"{name}: missing iOS destination: {sorted(result)}")
    return result


def minimum_versions(commands, variant):
    platforms = {"device": {"IOS", "2"}, "simulator": {"IOSSIMULATOR", "7"}}[variant]
    versions = []
    for block in re.split(r"(?m)^Load command \d+\s*$", commands):
        if "cmd LC_BUILD_VERSION" in block:
            platform = re.search(r"(?m)^[ \t]*platform[ \t]+([^\n]+)", block)
            label = platform[1].strip().upper() if platform else ""
            name = label.split()[0] if label[:1].isdigit() else re.sub(r"[^A-Z]", "", label)
            minimum = re.search(r"(?m)^\s*minos\s+(\d+(?:\.\d+)*)", block)
            if name not in platforms or not minimum:
                raise ValueError(f"incompatible Mach-O platform for {variant}")
            versions.append(minimum[1])
        elif "cmd LC_VERSION_MIN_IPHONEOS" in block:
            minimum = re.search(r"(?m)^\s*version\s+(\d+(?:\.\d+)*)", block)
            if not minimum:
                raise ValueError("missing Mach-O deployment target")
            versions.append(minimum[1])
        elif re.search(r"cmd LC_VERSION_MIN_(MACOSX|TVOS|WATCHOS)", block):
            raise ValueError(f"non-iOS object in {variant} archive")
    if not versions:
        raise ValueError("missing iOS deployment target")
    for version in versions:
        parts = tuple(map(int, version.split(".")))
        if (parts + (0, 0, 0))[:3] > (15, 0, 0):
            raise ValueError(f"deployment target {version} exceeds iOS 15.0")
    return sorted(set(versions))


def verify(root, record):
    manifest = []
    for name, required in EXPORTS.items():
        for variant, (binary, _) in sorted(ios_binaries(root, name).items()):
            archs = subprocess.check_output(["xcrun", "lipo", "-archs", binary], text=True).split()
            if set(archs) != ARCHITECTURES[variant]:
                raise ValueError(f"{binary}: actual architectures {archs}")
            for arch in sorted(archs):
                output = subprocess.check_output(["xcrun", "nm", "-arch", arch, "-gU", binary], text=True)
                symbols = {row.rsplit(maxsplit=1)[-1] for row in output.splitlines() if row.strip()}
                if missing := required - symbols:
                    raise ValueError(f"{binary} {arch}: missing definitions {sorted(missing)}")
                commands = subprocess.check_output(["xcrun", "otool", "-arch", arch, "-l", binary], text=True)
                minimum = minimum_versions(commands, variant)
                print(f"{name} {variant} {arch}: min OS {minimum}, {', '.join(sorted(required))}")
            digest = hashlib.sha256()
            with binary.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    digest.update(block)
            manifest.append(f"{digest.hexdigest()}  {binary.relative_to(root)}\n")
    path = root / "ios-sha256.txt"
    content = "".join(manifest)
    if record:
        path.write_text(content, encoding="utf-8")
    elif path.read_text(encoding="utf-8") != content:
        raise ValueError("iOS binary hashes differ from the build record")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    verify(args.root, args.record)
