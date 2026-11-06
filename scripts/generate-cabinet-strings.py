#!/usr/bin/env python3
"""BACKLOG A4 (v28.88.0): the cabinet's texts as the admin panel edits them.

The cabinet keeps its texts in cabinet/src/i18n.tsx: the Russian text is the key, EN and UK are tables (plus
``Object.assign`` additions). This script reads those tables and writes backend/app/assets/cabinet_strings.json —
{key: {"en": …, "uk": …}} — which the backend uses to list and check the texts the owner may replace.

    python scripts/generate-cabinet-strings.py           # write
    python scripts/generate-cabinet-strings.py --check   # fail if the file is stale
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cabinet/src/i18n.tsx"
TARGET = ROOT / "backend/app/assets/cabinet_strings.json"
HEADER = re.compile(r"export const (EN|UK)\b[^=]*=\s*\{|Object\.assign\((EN|UK),\s*\{")
PAIR = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"')


def tables(text: str) -> dict[str, dict[str, str]]:
    end = text.index("const TABLES")
    heads = list(HEADER.finditer(text, 0, end))
    out: dict[str, dict[str, str]] = {"EN": {}, "UK": {}}
    for i, head in enumerate(heads):
        stop = heads[i + 1].start() if i + 1 < len(heads) else end
        name = head.group(1) or head.group(2)
        for key, value in PAIR.findall(text, head.end(), stop):
            out[name][json.loads(f'"{key}"')] = json.loads(f'"{value}"')
    return out


def build() -> str:
    found = tables(SOURCE.read_text(encoding="utf-8"))
    keys = sorted(set(found["EN"]) | set(found["UK"]))
    data = {key: {"en": found["EN"].get(key, ""), "uk": found["UK"].get(key, "")} for key in keys}
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main() -> int:
    text = build()
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
            print("cabinet_strings.json is stale: run python scripts/generate-cabinet-strings.py", file=sys.stderr)
            return 1
        print(f"cabinet strings OK: {len(json.loads(text))}")
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"cabinet strings: {len(json.loads(text))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
