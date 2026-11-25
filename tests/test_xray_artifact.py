"""Archive-level checks for provenance, ABI coverage and byte-for-byte JNI packaging."""
import importlib.util
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("xray_artifact", ROOT / "scripts/mobile/xray-artifact.py")
artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact)
COMMIT = "a" * 40
ABIS = {"armeabi-v7a": (1, 40), "arm64-v8a": (2, 183), "x86": (1, 3), "x86_64": (2, 62)}


def archive(path, prefix, *, commit=COMMIT, omit=None, change=None, wrong_arch=None):
    with ZipFile(path, "w") as output:
        for abi, (elf_class, machine) in ABIS.items():
            if abi == omit:
                continue
            header = bytearray(20)
            header[:6] = b"\x7fELF" + bytes([elf_class, 1])
            header[18:20] = (0 if abi == wrong_arch else machine).to_bytes(2, "little")
            data = header + (b"changed" if abi == change else b"library")
            output.writestr(ZipInfo(f"{prefix}/{abi}/libgojni.so"), data)
        if prefix == "lib" and commit:
            output.writestr(ZipInfo("assets/corgi-xray.commit"), commit + "\n")
    return path


def test_two_builds_have_the_same_marker_and_verify_both_apks(tmp_path):
    first = archive(tmp_path / "first.aar", "jni")
    second = archive(tmp_path / "second.aar", "jni")
    for aar in (first, second):
        artifact.stamp(aar, COMMIT)
    assert first.read_bytes() == second.read_bytes()
    shop = archive(tmp_path / "shop.apk", "lib")
    client = archive(tmp_path / "client.apk", "lib")
    artifact.verify(first, [shop, client], COMMIT)


@pytest.mark.parametrize(("options", "message"), [
    ({"commit": None}, "source commit"),
    ({"commit": "b" * 40}, "source commit"),
    ({"omit": "armeabi-v7a"}, "JNI entries"),
    ({"change": "arm64-v8a"}, "differs"),
    ({"wrong_arch": "x86_64"}, "ELF architecture"),
])
def test_rejects_an_inconsistent_package(tmp_path, options, message):
    aar = archive(tmp_path / "xray.aar", "jni")
    artifact.stamp(aar, COMMIT)
    apk = archive(tmp_path / "client.apk", "lib", **options)
    with pytest.raises(ValueError, match=message):
        artifact.verify(aar, [apk], COMMIT)


def upstream_module():
    return {"Path": "github.com/2dust/AndroidLibXrayLite", "Version": "v0.0.0-20261110063532-aaaaaaaaaaaa",
            "Sum": "h1:" + "A" * 43 + "=", "Origin": {"Hash": COMMIT, "VCS": "git",
            "URL": "https://github.com/2dust/AndroidLibXrayLite"}}


def test_module_version_authenticates_the_pinned_wrapper_and_its_source():
    info = upstream_module()
    assert artifact.module_version(info, COMMIT) == info["Version"]


@pytest.mark.parametrize(("field", "value"), [
    ("Path", "example.invalid/fork"), ("Version", "latest"), ("Sum", "h1:short"),
    ("Origin", {}), ("Hash", "b" * 40), ("VCS", "hg"), ("URL", "https://example.invalid/fork"),
])
def test_module_version_rejects_unidentified_or_unpinned_source(field, value):
    info = upstream_module()
    (info["Origin"] if field in ("Hash", "VCS", "URL") else info)[field] = value
    with pytest.raises(ValueError, match="module"):
        artifact.module_version(info, COMMIT)



def test_versioned_upstream_replacements_are_preserved_and_local_paths_refused():
    versioned = {"Old": {"Path": "example.com/lib"}, "New": {"Path": "example.com/fork", "Version": "v1.4.0"}}
    artifact.check_replacements({"Replace": [versioned]})
    for override in ({"Old": versioned["Old"], "New": {"Path": "../unverified"}},
                     {"Old": {"Path": "github.com/2dust/AndroidLibXrayLite"}, "New": versioned["New"]}):
        with pytest.raises(ValueError, match="module replacement"):
            artifact.check_replacements({"Replace": [override]})


def test_elf_must_embed_one_canonical_wrapper_and_the_resolved_checksum():
    info = upstream_module()
    dep = {key: info[key] for key in ("Path", "Version", "Sum")}
    artifact.check_linked_module({"Deps": [dep]}, info)
    for deps in ([], [dep, dep], [{**dep, "Replace": {"Path": "/tmp/machine-dependent"}}],
                 [{**dep, "Version": "v1.0.0"}], [{**dep, "Sum": "h1:different"}]):
        with pytest.raises(ValueError, match="linked"):
            artifact.check_linked_module({"Deps": deps}, info)
