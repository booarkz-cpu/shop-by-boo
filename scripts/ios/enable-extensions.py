#!/usr/bin/env python3
"""Embed the iOS app extensions into the customer app (mobile/ios-user).

    python3 scripts/ios/enable-extensions.py --push            # rich push (pictures) only
    python3 scripts/ios/enable-extensions.py --tunnel --push   # plus the embedded VPN

The project ships both targets (CorgiTunnel, CorgiNotificationService) but does not embed them, so
the default build and its signing stay as they are. Each extension is its own App ID with its own
provisioning profile, and the packet tunnel needs the Network Extension entitlement that Apple grants
to the owner's team on request (docs/ru/APP_PROTECTION.md, docs/INSTALLATION.md). Run this script
in a signed release once the team has them; it is idempotent.

--tunnel also:
  * sets CORGI_TUNNEL = YES (the app then connects by itself instead of handing the subscription
    to Happ / v2RayTun);
  * adds the Network Extension and App Group entitlements to the app;
  * links mobile/ios-user/Frameworks/LibXray.xcframework and HevSocks5Tunnel.xcframework into the
    extension when they exist (scripts/ios/build-tunnel-frameworks.sh builds them).
"""
import argparse
import plistlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IOS = ROOT / "mobile/ios-user"
PBX = IOS / "VpnShopUser.xcodeproj/project.pbxproj"
APP_ENTITLEMENTS = IOS / "VpnShopUser/VpnShopUser.entitlements"
APP_TARGET = "B0000000000000000000000E"
PROJECT = "B0000000000000000000000F"
APP_GROUP = "group.shop.remnawave.user"
EXT = {
    "tunnel": {"target": "B000000000000000000000DA", "product": "B000000000000000000000D1", "name": "CorgiTunnel",
               "frameworks_phase": "B000000000000000000000D9", "ids": ("B000000000000000000000F1", "B000000000000000000000F2", "B000000000000000000000F3")},
    "push": {"target": "B000000000000000000000EA", "product": "B000000000000000000000E1", "name": "CorgiNotificationService",
             "frameworks_phase": "B000000000000000000000E9", "ids": ("B000000000000000000000F4", "B000000000000000000000F5", "B000000000000000000000F6")},
}
EMBED_PHASE = "B000000000000000000000F0"
FRAMEWORKS = {"LibXray": ("B000000000000000000000F7", "B000000000000000000000F8"),
              "HevSocks5Tunnel": ("B000000000000000000000F9", "B000000000000000000000FA")}


def add_objects(text: str, block: str) -> str:
    return text.replace("\t};\n\trootObject", block + "\t};\n\trootObject", 1)


def app_target_line(text: str) -> str:
    match = re.search(rf"\t\t{APP_TARGET} = \{{isa = PBXNativeTarget;.*\n", text)
    if not match:
        sys.exit("app target not found in project.pbxproj")
    return match.group(0)


def embed(text: str, key: str) -> str:
    ext = EXT[key]
    build_file, proxy, dependency = ext["ids"]
    if build_file in text:
        return text
    text = add_objects(text, (
        f'\t\t{build_file} /* {ext["name"]}.appex in Embed App Extensions */ = {{isa = PBXBuildFile; fileRef = {ext["product"]}; '
        f'settings = {{ATTRIBUTES = (RemoveHeadersOnCopy, ); }}; }};\n'
        f'\t\t{proxy} = {{isa = PBXContainerItemProxy; containerPortal = {PROJECT}; proxyType = 1; remoteGlobalIDString = {ext["target"]}; remoteInfo = {ext["name"]}; }};\n'
        f'\t\t{dependency} = {{isa = PBXTargetDependency; target = {ext["target"]}; targetProxy = {proxy}; }};\n'))
    if EMBED_PHASE not in text:
        text = add_objects(text, f'\t\t{EMBED_PHASE} /* Embed App Extensions */ = {{isa = PBXCopyFilesBuildPhase; buildActionMask = 2147483647; '
                                 f'dstPath = ""; dstSubfolderSpec = 13; files = (); name = "Embed App Extensions"; runOnlyForDeploymentPostprocessing = 0; }};\n')
        line = app_target_line(text)
        text = text.replace(line, re.sub(r"buildPhases = \(([^)]*)\)", lambda m: f"buildPhases = ({m.group(1)}, {EMBED_PHASE})", line), 1)
    text = re.sub(rf"({EMBED_PHASE} /\* Embed App Extensions \*/ = \{{[^\n]*files = \()([^)]*)\)",
                  lambda m: f"{m.group(1)}{(m.group(2) + ', ') if m.group(2).strip() else ''}{build_file})", text, count=1)
    line = app_target_line(text)
    text = text.replace(line, re.sub(r"dependencies = \(([^)]*)\)",
                                     lambda m: f"dependencies = ({(m.group(1) + ', ') if m.group(1).strip() else ''}{dependency})", line), 1)
    return text


def link_frameworks(text: str) -> str:
    phase = EXT["tunnel"]["frameworks_phase"]
    for name, (ref, build) in FRAMEWORKS.items():
        if not (IOS / "Frameworks" / f"{name}.xcframework").exists():
            print(f"  {name}.xcframework missing: the tunnel builds but refuses to start (run scripts/ios/build-tunnel-frameworks.sh)")
            continue
        if ref in text:
            continue
        text = add_objects(text, (
            f'\t\t{ref} /* {name}.xcframework */ = {{isa = PBXFileReference; lastKnownFileType = wrapper.xcframework; path = Frameworks/{name}.xcframework; sourceTree = "<group>"; }};\n'
            f'\t\t{build} /* {name}.xcframework in Frameworks */ = {{isa = PBXBuildFile; fileRef = {ref}; }};\n'))
        text = re.sub(rf"(\t\t{phase} = \{{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = \()([^)]*)\)",
                      lambda m, build=build: f"{m.group(1)}{(m.group(2) + ', ') if m.group(2).strip() else ''}{build})", text, count=1)
    return text


def entitlements():
    data = plistlib.loads(APP_ENTITLEMENTS.read_bytes())
    data["com.apple.developer.networking.networkextension"] = ["packet-tunnel-provider"]
    groups = data.setdefault("com.apple.security.application-groups", [])
    if APP_GROUP not in groups:
        groups.append(APP_GROUP)
    APP_ENTITLEMENTS.write_bytes(plistlib.dumps(data))


CONFIGS = {"app": ("B00000000000000000000012", "B00000000000000000000013"),
           "tunnel": ("B000000000000000000000DC", "B000000000000000000000DD"),
           "push": ("B000000000000000000000EC", "B000000000000000000000ED")}


def set_profiles(text: str, profiles: dict[str, str]) -> str:
    """Manual signing: each target (app, tunnel, push) gets its own provisioning profile UUID."""
    for key, uuid in profiles.items():
        if not re.fullmatch(r"[0-9A-Fa-f-]{36}", uuid):
            sys.exit(f"not a profile UUID: {key}={uuid}")
        for config in CONFIGS[key]:
            pattern = rf"(\t\t{config} = \{{isa = XCBuildConfiguration; buildSettings = \{{)(PROVISIONING_PROFILE_SPECIFIER = [^;]*; )?"
            text, n = re.subn(pattern, lambda m, uuid=uuid: f"{m.group(1)}PROVISIONING_PROFILE_SPECIFIER = {uuid}; ", text, count=1)
            if n != 1:
                sys.exit(f"build configuration {config} not found")
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tunnel", action="store_true", help="embed the packet tunnel (needs the Network Extension entitlement)")
    parser.add_argument("--push", action="store_true", help="embed the notification service extension (pictures in push)")
    parser.add_argument("--profile", action="append", default=[], metavar="TARGET=UUID",
                        help="provisioning profile per target for manual signing: app=…, tunnel=…, push=…")
    args = parser.parse_args(argv)
    if not (args.tunnel or args.push):
        parser.error("choose --tunnel and/or --push")
    profiles = dict(item.split("=", 1) for item in args.profile)
    if set(profiles) - set(CONFIGS):
        parser.error("--profile targets are app, tunnel, push")
    text = PBX.read_text()
    if args.push:
        text = embed(text, "push")
        print("rich push: CorgiNotificationService embedded")
    if args.tunnel:
        text = embed(text, "tunnel")
        text = link_frameworks(text)
        text = text.replace("CORGI_TUNNEL = NO;", "CORGI_TUNNEL = YES;")
        entitlements()
        print("tunnel: CorgiTunnel embedded, CORGI_TUNNEL = YES, entitlements added")
    if profiles:
        text = set_profiles(text, profiles)
        print("profiles:", ", ".join(sorted(profiles)))
    PBX.write_text(text)


if __name__ == "__main__":
    main()
