#!/usr/bin/env python3
"""Run repository consistency checks and retain a complete, explicitly limited audit report."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKS = (
    ("requirements", "scripts/audit/requirements_register.py", "--check"),
    ("source-traceability", "scripts/audit/source_traceability.py", "--check"),
    ("project-map", "scripts/generate-project-map.py", "--check"),
    ("release-notes", "scripts/audit/check_release_changelog.py"),
    ("documentation-links", "scripts/check-doc-links.py"),
    ("runtime-placeholders", "scripts/check-runtime-placeholders.py"),
    ("tracked-secrets", "scripts/ci/secret-leak-check.py"),
)
LIMITATIONS = [
    "Проверена согласованность исходников и документов; полный набор продуктовых тестов здесь не запускается.",
    "Статусы и пути evidence объявлены реестром. Этот запуск не подтверждает повторное выполнение исторических проверок.",
    "Критерии и зависимости, не выделенные в структурированные поля, остаются в полном исходном тексте; неизвестные связи не выдумываются.",
    "Сборки, платежи, VPN, физические устройства, VPS, подписи и production-проверки требуют отдельных подтверждений.",
]


def module(root: Path, name: str):
    spec = importlib.util.spec_from_file_location("audit_" + name, root / "scripts/audit" / (name + ".py"))
    if spec is None or spec.loader is None:
        raise ValueError("Audit module could not be loaded: " + name)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def redact(value: str) -> str:
    for key, secret in os.environ.items():
        if re.search(r"secret|token|password|credential|api_?key", key, re.I) and len(secret) >= 8:
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)\S+", r"\1[REDACTED]", value)
    return re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", value)


def run_check(root: Path, command: list[str], timeout: float = 180) -> dict:
    start = time.monotonic()
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, errors="replace",
                                timeout=timeout, check=False)
        code, output = result.returncode, result.stdout + result.stderr
        reason = None
    except subprocess.TimeoutExpired as exc:
        def decoded(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        code, output, reason = 124, decoded(exc.stdout) + decoded(exc.stderr), "timeout"
    except OSError as exc:
        code, output, reason = 127, str(exc), "execution_error"
    return {"command": [redact(value) for value in command], "exit_code": code, "status": "PASS" if code == 0 else "FAIL",
            "reason": reason, "duration_seconds": round(time.monotonic() - start, 3),
            "output": redact(output)}


def checklist(root: Path, canonical: list[dict], register: list[dict], statuses: dict) -> list[dict]:
    expected = [{key: item[key] for key in ("id", "lines", "sha", "path")} for item in canonical]
    ids = [item["id"] for item in canonical]
    if not ids or len(ids) != len(set(ids)) or expected != register or set(statuses) - set(ids):
        raise ValueError("Canonical requirements do not match the registered identities, hashes or order")
    rows = []
    for item in canonical:
        record = statuses.get(item["id"], {})
        rows.append({
            "id": item["id"], "product": item["product"],
            "source": {key: item[key] for key in ("path", "lines", "sha", "text")},
            "declared_status": record.get("status", "NOT_TESTED"),
            "declared_evidence": record.get("evidence", []),
            "note": record.get("note", ""), "platforms": record.get("platforms"),
            "acceptance_criteria": record.get("acceptance_criteria"),
            "dependencies": record.get("dependencies"),
            "declared_release_evidence": record.get("release_evidence", []),
            "execution_in_this_audit": None,
        })
    return rows


def collect(root: Path) -> tuple[list[dict], dict]:
    parser = module(root, "requirements_register")
    register = json.loads((root / "docs/requirements/register.json").read_text(encoding="utf-8"))
    statuses = json.loads((root / "docs/requirements/status.json").read_text(encoding="utf-8"))
    readiness = module(root, "check_release_readiness").inspect(root)
    return checklist(root, parser.parse(), register, statuses), readiness


def git_value(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                                timeout=10, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def escape(value: object) -> str:
    return str(value).replace("|", r"\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


def render(report: dict) -> str:
    meta = report["run"]
    rows = ["# Полный перечень требований: отчёт ограниченного автономного аудита", "",
            "Проверки этого запуска охватывают согласованность реестра, исходников и документации. "
            "Зелёный аудит не означает готовность продукта к релизу.", "",
            f"Commit: `{meta['commit']}`; branch: `{meta['branch']}`; "
            f"environment: `{meta['environment']}`; UTC: `{meta['generated_at']}`.",
            f"Python: `{meta['python_version']}`; Git: `{meta['git_version']}`.",
            f"Workflow: {meta['workflow_run_url'] or 'Не сопоставлен'}.", "",
            f"Результат проверок аудита: **{'PASS' if report['audit_passed'] else 'FAIL'}**. "
            f"Полнота перечня: **{report['checklist_complete']}**. "
            "Повторное выполнение всех продуктовых проверок: **нет**.", "",
            "## Выполненные команды", "",
            "| Проверка | Команда | Код выхода | Результат | Секунды | Лог |",
            "| --- | --- | ---: | --- | ---: | --- |"]
    for check in report["checks"]:
        rows.append("| " + " | ".join(escape(value) for value in (
            check["id"], " ".join(check["command"]), check["exit_code"],
            check["status"], check["duration_seconds"], check["log_path"])) + " |")
    rows += ["", "## Заявленные статусы требований", "",
             "`checklist-results.json` содержит полный исходный текст, диапазон, SHA, продукт, статус, "
             "примечание и объявленные evidence каждого требования. Неизвестные критерии и зависимости "
             "не подменяются автоматически придуманными связями.", "",
             "| Статус | Требований |", "| --- | ---: |"]
    counts = Counter(item["declared_status"] for item in report["requirements"])
    rows += [f"| {name} | {count} |" for name, count in sorted(counts.items())]
    readiness = report["release_readiness_declarations"]
    if readiness is not None:
        rows += ["", f"Объявленная готовность к новому релизу: **{readiness['ready']}**. "
                 f"Незавершённых требований: **{len(readiness['pending'])}**.",
                 "Флаги манифеста: `" + json.dumps(readiness["flags"], sort_keys=True) + "`."]
    rows += ["", "## Полный перечень", "",
             "| ID | Заявленный статус | Источник и SHA | Примечание |",
             "| --- | --- | --- | --- |"]
    for item in report["requirements"]:
        source = item["source"]
        rows.append("| " + " | ".join(escape(value) for value in (
            item["id"], item["declared_status"],
            f"{source['path']}; L{source['lines'][0]}–L{source['lines'][1]}; {source['sha']}",
            item["note"] or "Не сопоставлено")) + " |")
    rows += ["", "## Ошибки аудита", ""]
    rows += ["- " + escape(error) for error in report["errors"]] or ["Ошибок согласованности не обнаружено."]
    rows += ["", "## Ограничения", ""]
    rows += ["- " + item for item in report["limitations"]]
    rows += ["", "Счётчики продуктовых тестов, skipped tests и coverage этим запуском не измеряются. "
             "Поля test_counts и skipped_tests остаются null. Скриншоты не создаются; "
             "ссылки на отдельные внешние артефакты не придумываются.", ""]
    return "\n".join(rows)


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args(argv)
    output = root / "artifacts/audit"
    output.mkdir(parents=True, exist_ok=True)
    (output / "logs").mkdir(exist_ok=True)
    checks = []
    for identity, script, *options in CHECKS:
        result = run_check(root, [sys.executable, script, *options])
        log_path = "logs/" + identity + ".txt"
        (output / log_path).write_text(result.pop("output"), encoding="utf-8")
        checks.append({"id": identity, **result, "log_path": log_path})
    errors = []
    try:
        requirements, readiness = collect(root)
    except (OSError, ValueError, KeyError, TypeError, ImportError, SyntaxError) as exc:
        requirements, readiness = [], None
        errors.append(redact(str(exc)))
    run_id = os.environ.get("GITHUB_RUN_ID")
    repository = os.environ.get("GITHUB_REPOSITORY")
    report = {
        "schema_version": 1,
        "run": {"commit": git_value(root, "rev-parse", "HEAD"),
                "branch": git_value(root, "symbolic-ref", "--quiet", "--short", "HEAD"),
                "workflow_ref": os.environ.get("GITHUB_REF"),
                "environment": "GitHub Actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "python_version": sys.version.split()[0], "git_version": git_value(root, "--version"),
                "workflow_run_url": f"https://github.com/{repository}/actions/runs/{run_id}" if repository and run_id else None},
        "audit_passed": not errors and all(item["exit_code"] == 0 for item in checks),
        "checklist_complete": not errors, "full_product_verification": False,
        "checks": checks, "requirements": requirements, "release_readiness_declarations": readiness,
        "test_counts": None, "skipped_tests": None, "screenshots": [], "artifact_links": [],
        "errors": errors, "limitations": LIMITATIONS,
    }
    (output / "checklist-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "FULL_AUDIT_REPORT.md").write_text(render(report), encoding="utf-8")
    print(f"Autonomous audit: {'PASS' if report['audit_passed'] else 'FAIL'}; "
          f"requirements: {len(requirements)}; release declarations ready: {readiness['ready'] if readiness else False}")
    print("Reports: artifacts/audit/checklist-results.json; artifacts/audit/FULL_AUDIT_REPORT.md")
    return 0 if report["audit_passed"] and (not args.require_ready or readiness is not None and readiness["ready"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
