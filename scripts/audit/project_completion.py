"""Summarise the requirement register by domain without assigning acceptance statuses."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from requirements_register import STATUSES

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "docs/PROJECT_COMPLETION_MATRIX.md"


def render(register, status):
    by_domain = defaultdict(Counter)
    total = Counter()
    for entry in register:
        requirement = entry["id"]
        value = status.get(requirement, {}).get("status", "NOT_TESTED")
        if value not in STATUSES:
            raise ValueError(f"Unknown status {value} for {requirement}")
        by_domain[requirement.split("-")[1]][value] += 1
        total[value] += 1

    columns = [value for value in STATUSES if total[value]]
    lines = ["# Выполнение требований по разделам", "",
             "Каждое требование учитывается один раз в разделе своего ID. При отсутствии явной записи "
             "используется статус `NOT_TESTED` согласно правилам реестра. Доля выполнения равна отношению "
             "числа `PASS` к общему числу требований.", "",
             "| Раздел | " + " | ".join(columns) + " | Всего |",
             "| --- |" + " ---: |" * (len(columns) + 1)]
    for domain, counts in [*sorted(by_domain.items()), ("**Итого**", total)]:
        cells = [domain, *(str(counts[value]) for value in columns), str(counts.total())]
        lines.append("| " + " | ".join(cells) + " |")
    percent = (100 * total["PASS"] / total.total()) if total else 0
    formatted = f"{percent:.2f}".replace(".", ",")
    lines += ["", f"Доля требований со статусом PASS — {formatted} %.", "",
              "Тексты, пути к доказательствам и оставшиеся условия приёмки приведены в "
              "[полном реестре](REQUIREMENTS_MASTER_REGISTER.md). При изменении статусов пересоберите "
              "таблицу командой `python3 scripts/audit/project_completion.py`.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    register = json.loads((ROOT / "docs/requirements/register.json").read_text())
    status = json.loads((ROOT / "docs/requirements/status.json").read_text())
    result = render(register, status)
    if args.check:
        if not TARGET.is_file() or TARGET.read_text() != result:
            raise SystemExit("Project completion matrix is stale")
    else:
        TARGET.write_text(result)
