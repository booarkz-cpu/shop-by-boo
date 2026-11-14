#!/usr/bin/env python3
"""Stage 18: evidence for every module of the admin control matrix (docs/ru/new/ADMIN_CONTROL_MATRIX.md).

For each administrative API route of a module the script looks for a test that exercises it:
* a backend test that calls the endpoint function (``module.function(`` or ``function(``) or uses its path;
* a browser test (apps/lucy-admin/web/e2e) or the panel code path used by an end-to-end spec.
It also checks that every section of the module has a screenshot (tests/test_screenshots.py makes the catalog).

Status per module: PASS — every route that changes something is exercised by a test and every section has a
screenshot; PARTIAL — some changing routes are not exercised (listed); the list is the work left. Static
evidence, not a substitute for running the tests: the tests themselves run in CI.

    python scripts/verify-admin-matrix.py            # writes docs/ru/new/ADMIN_VERIFICATION.md
    python scripts/verify-admin-matrix.py --check    # fails when the file is stale"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
OUT = ROOT / "docs/ru/new/ADMIN_VERIFICATION.md"


def sources() -> tuple[str, str]:
    py = "\n".join(p.read_text(errors="ignore") for p in sorted((ROOT / "tests").rglob("*.py")))
    e2e = "\n".join(p.read_text(errors="ignore") for p in sorted((ROOT / "apps/lucy-admin/web/e2e").glob("*.ts")))
    return py, e2e


def e2e_covers(e2e: str) -> set[str]:
    """Routes a browser test drives through the panel's buttons, declared next to the test:
    ``// covers: POST /api/admin/runtime-settings/stage, POST /api/admin/runtime-settings/changes/{change_id}/apply``."""
    out = set()
    for line in re.findall(r"//\s*covers:\s*(.+)", e2e):
        out |= {x.strip() for x in line.split(",") if x.strip()}
    return out


def path_regex(path: str) -> re.Pattern:
    parts = [re.escape(x) if not x.startswith("{") else r"[^/\"'`\s?]+" for x in path.strip("/").split("/")]
    return re.compile(r"/" + "/".join(parts) + r"(?![A-Za-z0-9_-])")


def main() -> int:
    from app import admin_center
    from app.main import app
    py, e2e = sources()
    declared = e2e_covers(e2e)
    shots = {p.name.split("_", 1)[1].removesuffix(".png") for p in (ROOT / "screenshots/admin_panel").glob("[0-9]*_*.png")}
    routes = [(r, p) for r, p in admin_center._walk(app.routes) if p.startswith("/api/admin/")]
    rows, total, covered_total = [], 0, 0
    for number, name, tabs, prefixes, _missing in admin_center.MODULES:
        mine = [(r, p) for r, p in routes if any(p == f"/api/admin/{x}" or p.startswith(f"/api/admin/{x}/") or p.startswith(f"/api/admin/{x}.")
                                                for x in prefixes)]
        changing = [(r, p) for r, p in mine if r.methods & {"POST", "PUT", "PATCH", "DELETE"}]
        uncovered = []
        for r, p in changing:
            fn = r.endpoint.__name__
            by_call = re.search(rf"\b{re.escape(fn)}\(", py) is not None
            by_path = path_regex(p).search(py) or path_regex(p).search(e2e)
            by_e2e = any(f"{m} {p}" in declared for m in r.methods)
            if not (by_call or by_path or by_e2e):
                uncovered.append(f"{'/'.join(sorted(r.methods))} {p}")
        no_shot = [t for t in tabs if t not in shots]
        total += len(changing); covered_total += len(changing) - len(uncovered)
        status = "PASS" if not uncovered and not no_shot else "PARTIAL"
        rows.append((number, name, len(mine), len(changing), len(changing) - len(uncovered), no_shot, uncovered, status))
    lines = ["# Проверка админки по модулям", "",
             "Сгенерировано `python scripts/verify-admin-matrix.py` (этап 18). Для каждого модуля "
             "[матрицы управляемости](ADMIN_CONTROL_MATRIX.md) проверено, что каждый маршрут API, который что-то меняет "
             "(POST, PUT, PATCH, DELETE), вызывается тестом — backend-тестом или браузерным e2e. Также проверено, что у каждого "
             "раздела модуля есть скриншот. Сами тесты выполняются в CI; здесь — какой тест что покрывает.", "",
             "**PASS** — все изменяющие маршруты покрыты тестами, у всех разделов есть скриншот. "
             "**PARTIAL** — ниже перечислено, что не покрыто.", "",
             f"Изменяющих маршрутов: **{covered_total} из {total}** покрыты тестами; "
             f"модулей PASS: **{sum(1 for r in rows if r[7] == 'PASS')} из {len(rows)}**.", "",
             "| № | Модуль | Маршрутов | Изменяющих | Покрыто тестами | Статус |", "| --- | --- | --- | --- | --- | --- |"]
    for n, name, all_, ch, cov, _ns, _un, st in rows:
        lines.append(f"| {n} | {name} | {all_} | {ch} | {cov} | {st} |")
    left = [r for r in rows if r[7] != "PASS"]
    if left:
        lines += ["", "## Что не покрыто", ""]
        for n, name, _a, _c, _v, no_shot, uncovered, _s in left:
            lines.append(f"**{n}. {name}**")
            lines += [f"- нет скриншота раздела `{t}`" for t in no_shot]
            lines += [f"- `{u}`" for u in uncovered]
            lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print("docs/ru/new/ADMIN_VERIFICATION.md is stale: run python scripts/verify-admin-matrix.py", file=sys.stderr)
            return 1
        print("admin verification OK")
        return 0
    OUT.write_text(text)
    print(f"{covered_total}/{total} changing routes covered; PASS {sum(1 for r in rows if r[7] == 'PASS')}/{len(rows)}")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("APP_ENV", "test")
    raise SystemExit(main())
