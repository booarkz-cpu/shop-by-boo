#!/usr/bin/env python3
"""Check the currently inventoried RU/EN/UK UI resources with real Hunspell dictionaries."""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[2]
LANGUAGES = {"ru": "ru_RU,en_US", "en": "en_US", "uk": "uk_UA,en_US"}
JSON_SOURCES = ("packages/localization/admin.json", "packages/localization/user.json")
# Product names, protocol identifiers and technical units only. Ordinary prose must use dictionaries.
TERMS = {
    "ai", "api", "autostart", "corgi", "geoip", "geosite", "github", "happ", "hiddify",
    "html", "http", "https", "localhost", "lusi", "mbit", "mbps", "ms", "otp", "passkey",
    "passkeys", "pin", "qr", "regexp", "remnawave", "streisand", "telegram", "tls",
    "v2rayng", "vk", "vpn", "yandex", "корги", "коргі", "люси", "люсі",
}
TOKEN = re.compile(r"[^\W_]+(?:['’ʼ][^\W_]+)*", re.UNICODE)
NON_PROSE = re.compile(
    r"https?://[^\s<>]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"\{[^{}]*\}|%(?:\d+\$)?[-+#0 ]*\d*(?:\.\d+)?[A-Za-z%]|"
    r"<[^>]+>|\x60[^\x60]*\x60"
)


class Resource(NamedTuple):
    path: str
    language: str
    key: str
    text: str


def resources(root: Path):
    for name in JSON_SOURCES:
        data = json.loads((root / name).read_text(encoding="utf-8"))
        if set(data) != set(LANGUAGES):
            raise ValueError(f"{name}: expected exactly ru/en/uk")
        for language, values in data.items():
            if not isinstance(values, dict) or not values:
                raise ValueError(f"{name}: empty or invalid {language} resources")
            for key, value in values.items():
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{name}: invalid string {language}/{key}")
                yield Resource(name, language, key, value)
    paths = sorted((root / "apps").glob("*/android/app/src/main/res/values*/strings.xml"))
    if not paths:
        raise ValueError("Android string resources were not found")
    for path in paths:
        qualifier = path.parent.name
        language = {"values": "ru", "values-en": "en", "values-uk": "uk"}.get(qualifier)
        if language is None:
            raise ValueError(f"Uninventoried Android language: {path.relative_to(root)}")
        for element in ET.parse(path).getroot():
            if element.attrib.get("translatable") == "false":
                continue
            if element.tag == "string":
                yield Resource(path.relative_to(root).as_posix(), language,
                               element.attrib["name"], "".join(element.itertext()))
            elif element.tag in {"plurals", "string-array"}:
                for index, item in enumerate(element):
                    yield Resource(path.relative_to(root).as_posix(), language,
                                   f"{element.attrib['name']}[{index}]", "".join(item.itertext()))


def words(text: str) -> set[str]:
    text = unicodedata.normalize("NFC", html.unescape(text))
    text = NON_PROSE.sub(" ", text).replace("\\n", " ").replace("\\t", " ")
    return {word.replace("’", "'").replace("ʼ", "'") for word in TOKEN.findall(text)
            if not word.isdecimal() and word.casefold() not in TERMS}


class Engine:
    def __init__(self, binary: str = "hunspell"):
        self.binary = binary

    def unknown(self, language: str, tokens: set[str]) -> set[str]:
        if not tokens:
            return set()
        result = subprocess.run(
            [self.binary, "-l", "-i", "UTF-8", "-d", LANGUAGES[language]],
            input="\n".join(sorted(tokens)) + "\n", text=True, encoding="utf-8",
            capture_output=True, timeout=60, check=False,
        )
        if result.returncode or result.stderr.strip():
            raise RuntimeError(f"Hunspell {language} failed: {result.stderr.strip()}")
        return set(result.stdout.splitlines())


def self_test(engine: Engine) -> None:
    # A missing/wrong dictionary must not silently turn a green job into a false PASS.
    for language, valid, invalid in [
        ("ru", "подключение", "подклчение"),
        ("en", "connection", "conection"),
        ("uk", "підключення", "підклчення"),
    ]:
        if engine.unknown(language, {valid, invalid}) != {invalid}:
            raise RuntimeError(f"Hunspell positive/negative control failed for {language}")


def check(root: Path, engine: Engine) -> int:
    entries = list(resources(root))
    tokens = {language: set() for language in LANGUAGES}
    for entry in entries:
        tokens[entry.language].update(words(entry.text))
    unknown = {language: engine.unknown(language, value) for language, value in tokens.items()}
    count = 0
    for entry in entries:
        for word in sorted(words(entry.text) & unknown[entry.language]):
            # Report identifiers and tokens only, never entire user-visible messages.
            print(f"{entry.path}: {entry.language}/{entry.key}: {word}")
            count += 1
    print(f"Spelling: {len(entries)} strings in {len({e.path for e in entries})} files; "
          f"{sum(map(len, tokens.values()))} distinct language/word pairs; {count} findings.")
    print("Scope: localization JSON and Android XML; other surfaces still require an audit.")
    return int(count > 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        engine = Engine()
        if args.self_test:
            self_test(engine)
        return check(ROOT, engine)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, ET.ParseError) as exc:
        print(f"Spelling check could not run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
