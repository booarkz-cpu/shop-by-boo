#!/usr/bin/env python3
"""Generate the current API catalogue from the shipped FastAPI application."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def render():
    os.environ.setdefault('APP_ENV', 'test')
    sys.path.insert(0, str(ROOT/'backend'))
    from app.main import app
    manifest = json.loads((ROOT/'release-manifest.template.json').read_text())
    rows = []
    for path, operations in sorted(app.openapi()['paths'].items()):
        for method, info in sorted(operations.items()):
            if method.lower() not in {'get','post','put','patch','delete','head','options'}:
                continue
            title = (info.get('summary') or info.get('operationId') or '').replace('|','\\|').replace('\n',' ')
            rows.append(f'| `{method.upper()}` | `{path}` | {title} |')
    return f'''# Каталог API — {manifest['distribution_tag']} / API v{manifest['version']}

Сгенерирован из OpenAPI текущих исходников. Миграция: `{manifest['migration_head']}`.
Авторизация, права, CSRF и принадлежность записей проверяются сервером; схема маршрута не заменяет права роли.
Сценарии: [руководство](ru/WORKSPACE_USER_GUIDE.md), [рефералы](ru/REFERRALS_CURRENT.md), [HTTP API](../API_REFERENCE_RU.md).

Legacy callbacks прежних агентов служат историческим операциям. Новые покупки используют YooKassa/Platega/RollyPay;
production gate остаётся закрытым без полного application E2E. Mobile purchase verify закрыт ответом 410.

Обновление: `PYTHONPATH=backend python scripts/generate-api-docs.py`; проверка: добавьте `--check`.

| Метод | Путь | Операция |
| --- | --- | --- |
'''+'\n'.join(rows)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    target = ROOT/'docs/API_ENDPOINTS.md'
    content = render()
    if args.check:
        if target.read_text() != content:
            raise SystemExit('API catalogue is stale: run scripts/generate-api-docs.py')
    else:
        target.write_text(content)


if __name__ == '__main__':main()
