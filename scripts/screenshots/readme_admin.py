#!/usr/bin/env python3
"""Rewrite the «#### Админ-панель» block of README.md from the index the catalog script writes.

    node admin/scripts/screenshots-catalog.mjs "$PWD"          # writes $TMPDIR/admin-screenshots-index.json
    python3 scripts/screenshots/readme_admin.py [index.json]

Groups keep the order of the side menu; each group is a collapsed <details> block.
"""
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
START = "#### Админ-панель\n"
END = "#### Личный кабинет пользователя\n"
INTRO = "Порядок совпадает с боковым меню панели. Разверните группу, чтобы увидеть снимки.\n"


def render(index: list[dict]) -> str:
    groups: list[tuple[str, list[dict]]] = []
    for item in index:
        if not groups or groups[-1][0] != item["group"]:
            groups.append((item["group"], []))
        groups[-1][1].append(item)
    out = [START, "\n", INTRO, "\n"]
    for title, items in groups:
        out.append(f"<details>\n<summary><b>{title}</b> ({len(items)})</summary>\n\n")
        for item in items:
            out.append(f"**{item['label']}** — {item['description']}\n\n")
            out.append(f"![{item['label']}](screenshots/admin_panel/{item['file']})\n\n")
        out.append("</details>\n\n")
    return "".join(out)


def main() -> None:
    index_path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), "admin-screenshots-index.json"))
    index = json.loads(index_path.read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    start, end = readme.index(START), readme.index(END)
    (ROOT / "README.md").write_text(readme[:start] + render(index) + readme[end:], encoding="utf-8")
    print(f"README: {len(index)} admin screenshots")


if __name__ == "__main__":
    main()
