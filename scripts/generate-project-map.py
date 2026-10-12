#!/usr/bin/env python3
"""Generate the complete tracked-file map without local or generated products."""
from __future__ import annotations
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs/PROJECT_FILE_MAP.md"
AREAS = {"admin": "Админ-панель", "backend": "API, бот и worker", "cabinet": "Кабинет", "miniapp": "Telegram Mini App",
         "support-pro": "Support Pro", "mobile": "Мобильные приложения", "tests": "Проверки", "scripts": "Эксплуатация и релиз",
         "deploy": "Установка", "docs": "Документация", ".github": "GitHub CI/CD"}


def render() -> str:
    manifest = json.loads((ROOT / "release-manifest.template.json").read_text())
    paths = sorted(p.decode() for p in subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0") if p)
    rows = ["# Полная карта файлов проекта", "",
            f"Дистрибутив `{manifest['distribution_tag']}`; runtime/API `{manifest['version']}`.", "",
            "Карта строится из отслеживаемых Git файлов. Локальные секреты, зависимости и результаты сборки сюда не входят.", "",
            f"Всего файлов: **{len(paths)}**. Пересобрать: `python3 scripts/generate-project-map.py`; проверить: `python3 scripts/generate-project-map.py --check`.", "",
            "| Файл | Область |", "| --- | --- |"]
    for name in paths:
        area = AREAS.get(name.split("/", 1)[0], "Корень проекта")
        rows.append(f"| [{name}](../{name}) | {area} |")
    return "\n".join(rows) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != content:
            raise SystemExit("Project map is stale; stage new files and regenerate it")
        print("project file map OK")
    else:
        TARGET.write_text(content)
        print(TARGET.relative_to(ROOT))


if __name__ == "__main__":
    main()
