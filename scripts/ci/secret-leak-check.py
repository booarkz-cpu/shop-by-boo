#!/usr/bin/env python3
"""No secrets in the repository (requirement REQ-INFRA-0021): environment files, private keys, database dumps,
backup bundles and tokens must never be committed.

    python3 scripts/ci/secret-leak-check.py          # the files git tracks
    python3 scripts/ci/secret-leak-check.py <dir>    # every file under <dir> (tests)

Exit 1 with the list of findings — the path and the kind, never the secret itself. A finding that is a deliberate test
fixture (a key generated for a test, a fake token) is listed in ALLOWED with the reason.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Paths that may contain secret-shaped text on purpose: (path prefix, why).
ALLOWED = {
    ".env.example": "образец без значений",
    ".env.test.example": "образец для тестов",
    "support-pro/.env.example": "образец без значений",
    "scripts/ci/secret-leak-check.py": "эта проверка сама описывает шаблоны",
    "tests/": "тестовые данные: ключи и токены сгенерированы для тестов и нигде не действуют",
    "docs/archive/": "история выпусков, без действующих значений",
}
FILE_NAMES = (
    (re.compile(r"(^|/)\.env(\.[^/]*)?$"), "файл окружения .env"),
    (re.compile(r"\.(pem|key|p12|pfx|jks|keystore)$", re.I), "файл ключа или хранилища ключей"),
    (re.compile(r"\.(sql|dump|vpb)(\.gz)?$", re.I), "дамп базы или резервная копия"),
    (re.compile(r"(^|/)id_(rsa|ed25519|ecdsa)$"), "приватный SSH-ключ"),
)
CONTENT = (
    # A header alone is a placeholder (an input hint, an example in the docs); a key has its body after it.
    (re.compile(rb"-----BEGIN (RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----(\r?\n|\\n)[A-Za-z0-9+/=]{40,}"), "приватный ключ в тексте"),
    (re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "токен GitHub"),
    (re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{60,}\b"), "токен GitHub"),
    (re.compile(rb"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b"), "токен Telegram-бота"),
    (re.compile(rb"\bAKIA[0-9A-Z]{16}\b"), "ключ AWS"),
    (re.compile(rb"\bsk-(live|proj)-[A-Za-z0-9]{20,}\b"), "секретный ключ API"),
)
SAMPLE_NAMES = (".example", ".sample", ".template")


def allowed(path: str) -> bool:
    return path in ALLOWED or any(path.startswith(p) for p in ALLOWED if p.endswith("/"))


def tracked(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode().split("\0") if p]


def scan(root: Path, paths: list[str]) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for path in sorted(paths):
        if allowed(path):
            continue
        name_hit = next((why for rx, why in FILE_NAMES if rx.search(path)), None)
        if name_hit and not path.endswith(SAMPLE_NAMES):
            findings.append((path, name_hit))
            continue
        file = root / path
        try:
            if not file.is_file() or file.stat().st_size > 5_000_000:
                continue
            data = file.read_bytes()
        except OSError:
            continue
        for rx, why in CONTENT:
            if rx.search(data):
                findings.append((path, why))
                break
    return findings


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        root = Path(argv[1]).resolve()
        paths = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    else:
        root, paths = ROOT, tracked(ROOT)
    findings = scan(root, paths)
    for path, why in findings:
        print(f"x:1:1: {path}: {why} — секретов в репозитории быть не должно")
    print(f"secret leak check: {len(paths)} files, {len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
