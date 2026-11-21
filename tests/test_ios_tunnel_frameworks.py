"""Negative cases for XCFramework destination validation before native linking."""

import importlib.util
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

FILE = Path(__file__).resolve().parents[1] / "scripts/ios/verify_tunnel_frameworks.py"
SPEC = importlib.util.spec_from_file_location("verify_tunnel_frameworks", FILE)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)

RUNTIME_FILE = Path(__file__).parent / "ios/tunnel_runtime.py"
RUNTIME_SPEC = importlib.util.spec_from_file_location("tunnel_runtime", RUNTIME_FILE)
tunnel_runtime = importlib.util.module_from_spec(RUNTIME_SPEC)
RUNTIME_SPEC.loader.exec_module(tunnel_runtime)


def library(identifier, archs, variant=None):
    entry = {"LibraryIdentifier": identifier, "SupportedPlatform": "ios",
             "SupportedArchitectures": archs, "LibraryPath": "LibXray.framework"}
    if variant:
        entry["SupportedPlatformVariant"] = variant
    return entry


DEVICE = library("ios-arm64", ["arm64"])
SIM = library("ios-arm64_x86_64-simulator", ["arm64", "x86_64"], "simulator")


def inspect(tmp_path, entries):
    bundle = tmp_path / "LibXray.xcframework"
    bundle.mkdir(exist_ok=True)
    (bundle / "Info.plist").write_bytes(plistlib.dumps({"AvailableLibraries": entries}))
    return verifier.ios_binaries(tmp_path, "LibXray")


class FrameworkTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)

    def test_device_and_simulator_are_distinct(self):
        result = inspect(self.root, [DEVICE, SIM, library("catalyst", ["arm64"], "maccatalyst")])
        self.assertEqual(set(result), {"device", "simulator"})
        for variant, entry in (("device", DEVICE), ("simulator", SIM)):
            binary, _ = result[variant]
            self.assertEqual(binary, self.root / "LibXray.xcframework" / entry["LibraryIdentifier"] / "LibXray.framework/LibXray")

    def test_rejects_missing_duplicate_or_incompatible_destinations(self):
        for entries in ([DEVICE], [SIM, SIM], [DEVICE, SIM, SIM],
                        [DEVICE, library("sim", ["arm64"], "simulator")],
                        [library("wrong-device", ["x86_64"]), SIM]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                inspect(self.root, entries)

    def test_checks_platform_and_minimum_in_macho_load_commands(self):
        commands = "Load command 0\n cmd LC_BUILD_VERSION\n cmdsize 24\n platform 7\n minos 15.0\n"
        self.assertEqual(verifier.minimum_versions(commands, "simulator"), ["15.0"])
        with self.assertRaisesRegex(ValueError, "platform"):
            verifier.minimum_versions(commands, "device")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            verifier.minimum_versions(commands.replace("15.0", "16.0"), "simulator")

    def test_stalled_simulator_is_erased_and_booted_once_more(self):
        completed = subprocess.CompletedProcess([], 0)
        with (
            mock.patch.object(tunnel_runtime, "simulator_ready", side_effect=[False, True]) as ready,
            mock.patch.object(tunnel_runtime.subprocess, "run", return_value=completed) as run,
        ):
            tunnel_runtime.boot_simulator("device-id")
        self.assertEqual(ready.call_args_list, [mock.call("device-id", 120), mock.call("device-id", 180)])
        self.assertEqual(run.call_count, 4)
        self.assertEqual(run.call_args_list[1].args[0][-2:], ["shutdown", "device-id"])
        self.assertEqual(run.call_args_list[2].args[0][-2:], ["erase", "device-id"])

    def test_ready_simulator_is_not_erased(self):
        completed = subprocess.CompletedProcess([], 0)
        with (
            mock.patch.object(tunnel_runtime, "simulator_ready", return_value=True),
            mock.patch.object(tunnel_runtime.subprocess, "run", return_value=completed) as run,
        ):
            tunnel_runtime.boot_simulator("device-id")
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
