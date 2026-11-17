#!/usr/bin/env python3
"""Render all source-to-evidence relationships without inventing execution or release evidence."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "docs/SOURCE_TRACEABILITY_MATRIX.md"


def cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ")


def render(root: Path) -> str:
    spec = importlib.util.spec_from_file_location("project_requirements", root / "scripts/audit/requirements_register.py")
    if spec is None or spec.loader is None:
        raise ValueError("Canonical source parser could not be loaded")
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    canonical = {item["id"]: item for item in parser.parse()}
    register = json.loads((root / "docs/requirements/register.json").read_text(encoding="utf-8"))
    status = json.loads((root / "docs/requirements/status.json").read_text(encoding="utf-8"))
    ids = [entry["id"] for entry in register]
    if not ids or len(ids) != len(set(ids)) or set(status) - set(ids) or set(ids) != set(canonical):
        raise ValueError("Missing, duplicated or unknown requirement identity")
    rows = ["# Матрица трассировки источников и доказательств", "",
            "Источник: [MASTER_PROMPT_V6.md](prompts/MASTER_PROMPT_V6.md). Полные тексты и статусы: "
            "[REQUIREMENTS_MASTER_REGISTER.md](REQUIREMENTS_MASTER_REGISTER.md).", "",
            f"Всего требований: **{len(register)}**. Каждая запись источника представлена ровно один раз.",
            "Команда обновления: `python scripts/audit/source_traceability.py`; проверка: "
            "`python scripts/audit/source_traceability.py --check`.", "",
            "Код, тесты и другие evidence взяты из записей реестра; проверены исходные SHA и наличие путей. "
            "Наличие файла не означает выполнение проверки. Пропуски не заменяются предположениями. "
            "Связь с опубликованным релизом указывается только через отдельный release_evidence; "
            "отсутствующая связь остаётся «Не сопоставлен». Матрица не доказывает production-готовность.", "",
            "| Требование | Источник и SHA | Статус | Код | Тесты и проверки | Прочие evidence | Релиз |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    for entry in register:
        first, last = entry["lines"]
        if any(canonical[entry["id"]][key] != entry[key] for key in ("id", "lines", "sha", "path")):
            raise ValueError(f"{entry['id']}: source range/hash mismatch")
        record = status.get(entry["id"], {})
        code, tests, other = [], [], []
        for evidence in record.get("evidence", []):
            name = evidence.split("::")[0].split("#")[0]
            path = (root / name).resolve()
            # A removed generated matrix can be rebuilt; --check still refuses an absent output.
            if name != "docs/SOURCE_TRACEABILITY_MATRIX.md" and (
                not path.is_relative_to(root.resolve()) or not path.exists()
            ):
                raise ValueError(f"{entry['id']}: evidence path is absent or outside the project")
            if name.startswith(("tests/", ".github/workflows/", "scripts/audit/", "scripts/ci/")) or "/test/" in name or "/androidTest/" in name or ".test." in name or any(part.endswith(("Test", "Tests")) for part in Path(name).parts[:-1]):
                tests.append(evidence)
            elif name.startswith(("apps/", "services/", "packages/", "scripts/")):
                code.append(evidence)
            else:
                other.append(evidence)
        show = lambda values: "; ".join("`" + cell(value) + "`" for value in values) if values else "Не сопоставлено"
        location = f"{entry['path']}; L{first}" + (f"–L{last}" if first != last else "")
        release = record.get("release_evidence", [])
        rows.append("| " + " | ".join([
            "`" + entry["id"] + "`", cell(location) + "; `" + entry["sha"] + "`",
            "`" + record.get("status", "NOT_TESTED") + "`", show(code), show(tests), show(other),
            show(release) if release else "Не сопоставлен",
        ]) + " |")
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        text = render(ROOT)
        if args.check:
            if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
                raise ValueError("Source traceability matrix is absent or stale")
            print("Source traceability matrix matches every source requirement and declared evidence path")
        else:
            TARGET.write_text(text, encoding="utf-8")
            print(TARGET.relative_to(ROOT))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Source traceability check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
