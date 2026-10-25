#!/usr/bin/env python3
"""Create a publisher key and sign Corgi shop plugin packages.

    python3 scripts/sign-plugin.py keygen publisher.key      # prints the public key for the admin panel
    python3 scripts/sign-plugin.py sign publisher.key docs/examples/plugin acme-crm-1.0.0.zip
    python3 scripts/sign-plugin.py catalog publisher.key catalog.json catalog.signed.json

A catalog lists packages for one-click install in the admin panel. catalog.json is
{"catalog": 1, "name": "...", "plugins": [{"id", "name", "version", "description",
"package_url" (https), "sha256" (of the zip), "homepage"}]}; the signed copy adds
public_key and signature. Publish it on HTTPS and add its address in the admin panel.

A package contains manifest.json and an optional README.md. The signature covers the
SHA-256 of every file, so any change after signing is rejected by the shop.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from base64 import b64encode
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PACKAGE_FILES = ("manifest.json", "README.md")


def digest(files: dict[str, bytes]) -> bytes:
    lines = "".join(f"{name}\0{hashlib.sha256(data).hexdigest()}\n" for name, data in sorted(files.items()))
    return hashlib.sha256(lines.encode()).digest()


def keygen(path: Path) -> None:
    if path.exists():
        raise SystemExit(f"{path} already exists; refusing to overwrite a publisher key")
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(pem)
    print(public_key(key))


def public_key(key: Ed25519PrivateKey) -> str:
    return b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def sign(key_path: Path, source: Path, out: Path) -> None:
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("The key is not an Ed25519 private key")
    files = {name: (source / name).read_bytes() for name in PACKAGE_FILES if (source / name).is_file()}
    if "manifest.json" not in files:
        raise SystemExit(f"{source}/manifest.json is missing")
    json.loads(files["manifest.json"])  # fail early on invalid JSON
    signature = {"public_key": public_key(key), "signature": b64encode(key.sign(digest(files))).decode()}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
        archive.writestr("signature.json", json.dumps(signature))
    print(f"{out}: {hashlib.sha256(out.read_bytes()).hexdigest()}")


def sign_catalog(key_path: Path, source: Path, out: Path) -> None:
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("The key is not an Ed25519 private key")
    index = json.loads(source.read_text())
    body = {"catalog": index.get("catalog", 1), "name": index.get("name", ""), "plugins": index.get("plugins", [])}
    digest_ = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).digest()
    signed = {**body, "public_key": public_key(key), "signature": b64encode(key.sign(digest_)).decode()}
    out.write_text(json.dumps(signed, ensure_ascii=False, indent=1))
    print(f"{out}: {len(body['plugins'])} plugins signed")


def main(argv: list[str]) -> None:
    if len(argv) == 2 and argv[0] == "keygen":
        keygen(Path(argv[1]))
    elif len(argv) == 4 and argv[0] == "sign":
        sign(Path(argv[1]), Path(argv[2]), Path(argv[3]))
    elif len(argv) == 4 and argv[0] == "catalog":
        sign_catalog(Path(argv[1]), Path(argv[2]), Path(argv[3]))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
