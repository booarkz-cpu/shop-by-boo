#!/usr/bin/env python3
"""Generate docs/ru/new/ADMIN_CONTROL_MATRIX.md and docs/ru/new/ADMIN_MODULES.md from the routes of the
application (v28.60.0 / v28.62.0, stage 6).

The same data feeds «Система → Админ-центр» (``backend/app/admin_center.py``); section names and
descriptions come from ``admin/src/sections.ts``. ``--check`` fails when a document is stale;
tests/test_admin_center.py runs it in CI."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs/ru/new/ADMIN_CONTROL_MATRIX.md"
MODULES_TARGET = ROOT / "docs/ru/new/ADMIN_MODULES.md"
OPS = ["read", "create", "update", "delete", "search", "settings", "diagnostics", "audit"]


def tab_labels() -> dict[str, str]:
    text = (ROOT / "admin/src/sections.ts").read_text()
    return dict(re.findall(r'\{tab: "([A-Za-z0-9]+)", label: "([^"]+)"', text))


def tab_descriptions() -> dict[str, tuple[str, str]]:
    text = (ROOT / "admin/src/sections.ts").read_text()
    return {tab: (label, description) for tab, label, description
            in re.findall(r'\{tab: "([A-Za-z0-9]+)", label: "([^"]+)", description: "([^"]+)"', text)}


OP_WORDS = {"read": "просмотр", "create": "создание", "update": "изменение", "delete": "удаление", "search": "поиск и фильтры",
            "settings": "настройки", "diagnostics": "проверка", "audit": "запись в журнал действий"}


def render_modules() -> str:
    os.environ.setdefault("APP_ENV", "test")
    sys.path.insert(0, str(ROOT / "backend"))
    from app.admin_center import matrix

    manifest = json.loads((ROOT / "release-manifest.template.json").read_text())
    sections = tab_descriptions()
    rows = matrix()
    lines = [
        f"# Модули админ-панели — {manifest['distribution_tag']}",
        "",
        "Сгенерировано командой `python scripts/generate-admin-matrix.py`: модули и их API — из `backend/app/admin_center.py` "
        "и маршрутов приложения, разделы и их описания — из `admin/src/sections.ts`. Сводная таблица операций — "
        "[ADMIN_CONTROL_MATRIX](ADMIN_CONTROL_MATRIX.md), права ролей — [RBAC](RBAC.md), работа с панелью — "
        "[ADMIN_PANEL_GUIDE](ADMIN_PANEL_GUIDE.md).",
        "",
        "Состояние всех частей установки (backend, база, Redis, Remnawave, узлы, Caddy, TLS, платежи, Telegram, фоновые задачи, "
        "резервные копии, обновления) собрано на одном экране «Аналитика → Состояние системы» (модуль 20).",
    ]
    for m in rows:
        lines += ["", f"## {m['number']}. {m['module']}", ""]
        if m["missing"]:
            lines.append(f"**Не реализован** — {m['missing']}. В панели нет его раздела и кнопок: функция появится вместе с работающим backend.")
            continue
        ops = ", ".join(OP_WORDS[k] for k, v in m["operations"].items() if v)
        perms = ", ".join(f"`{p}`" for p in m["permissions"])
        lines += [f"Статус: `{m['status']}`. Маршрутов API: {m['routes']}. Операции: {ops}.", "",
                  "| Раздел панели | Что в нём |", "| --- | --- |"]
        for tab in m["tabs"]:
            label, description = sections.get(tab, (tab, ""))
            lines.append(f"| {label} | {description} |")
        lines += ["", "API: " + ", ".join(f"`/api/admin/{p}`" for p in m["api_prefixes"]) + f". Права: {perms}."]
    return "\n".join(lines) + "\n"


def render() -> str:
    os.environ.setdefault("APP_ENV", "test")
    sys.path.insert(0, str(ROOT / "backend"))
    from app.admin_center import matrix, outside_modules

    manifest = json.loads((ROOT / "release-manifest.template.json").read_text())
    labels = tab_labels()
    rows = matrix()
    ready = sum(1 for m in rows if not m["missing"])
    lines = [
        f"# Управляемость из админки — {manifest['distribution_tag']}",
        "",
        "Сгенерировано командой `python scripts/generate-admin-matrix.py` из маршрутов приложения "
        "(`backend/app/admin_center.py`). Те же данные показывает «Система → Админ-центр».",
        "",
        "Операции определяются по маршрутам API: GET → чтение, POST → создание, PUT/PATCH → изменение, DELETE → удаление; "
        "поиск/фильтр — параметры запроса (`status`, `q`, `actor`, `since`…); настройки и проверка — по путям (`config`, `test`, `health`…); "
        "журнал — изменяющий обработчик пишет в `audit_logs`. Статус `IMPLEMENTED` значит: раздел и API есть. "
        "Работа каждой кнопки в интерфейсе проверяется на этапе 18, после этого статус станет `PASS` или `FAIL`.",
        "",
        f"Модулей с разделом в панели: **{ready} из {len(rows)}**.",
        "",
        "| № | Модуль | Разделы панели | Маршрутов API | Чтение | Создание | Изменение | Удаление | Поиск/фильтр | Настройки | Проверка | Журнал | Права | Статус |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for m in rows:
        tabs = ", ".join(labels.get(t, t) for t in m["tabs"]) or "—"
        marks = ["—" if m["missing"] else ("✓" if m["operations"][op] else "·") for op in OPS]
        perms = ", ".join(f"`{p}`" for p in m["permissions"]) or "—"
        status = f"{m['status']} ({m['missing']})" if m["missing"] else m["status"]
        lines.append(f"| {m['number']} | {m['module']} | {tabs} | {m['routes']} | " + " | ".join(marks) + f" | {perms} | {status} |")
    lines += ["", "«·» — у модуля нет маршрута для этой операции; это не обязательно недостаток. Например, у журнала действий нет удаления: записи неизменяемы."]
    rest = outside_modules()
    lines += ["", "## Разделы вне 30 модулей задания", "",
              f"Ещё {sum(rest.values())} административных маршрутов относятся к разделам, которых нет в списке задания: "
              "поддержка, кабинет и приложения, конкурсы, опросы, страницы, корпоративные клиенты и другие. Они управляются из своих разделов панели. "
              "Префиксы и число маршрутов: " + ", ".join(f"`{k}` {v}" for k, v in rest.items()) + "."]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for target, content in ((TARGET, render()), (MODULES_TARGET, render_modules())):
        if args.check:
            if not target.exists() or target.read_text() != content:
                raise SystemExit(f"{target.name} is stale: run scripts/generate-admin-matrix.py")
        else:
            target.write_text(content)


if __name__ == "__main__":
    main()
