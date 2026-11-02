#!/usr/bin/env python3
"""Generate the current API catalogue from the shipped FastAPI application."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


PREFIX_ACCESS = (
    ('/api/admin/auth', 'вход администратора'),
    ('/api/admin/', 'право (проверяет обработчик)'),
    ('/api/webhooks/', 'подпись провайдера'),
    ('/api/payments/webhooks/', 'подпись провайдера'),
    ('/api/me', 'сессия клиента'),
    ('/api/auth/', 'вход клиента'),
    ('/api/agent/', 'токен агента ноды'),
    ('/api/probe/', 'токен пробы'),
    ('/api/plugin/', 'ключ плагина'),
    ('/api/reseller/', 'ключ партнёра'),
    ('/api/internal/', 'служебный токен'),
    ('/api/standby/', 'токен резерва'),
    ('/metrics', 'токен `X-Metrics-Token`'),
)


def access_table(app):
    """(METHOD, path) -> who may call it: the RBAC permission of an administrative route, else the kind
    of caller the route checks (v28.59.0, stage 5). Read from the dependencies, not from the docs."""
    from fastapi.routing import APIRoute

    def walk(routes, prefix=''):
        for route in routes:
            if hasattr(route, 'original_router'):
                yield from walk(route.original_router.routes, prefix + route.include_context.prefix)
            elif isinstance(route, APIRoute):
                yield route, prefix + route.path

    def permissions(dependant):
        for dep in dependant.dependencies:
            name = getattr(dep.call, 'required_permission', None)
            if name:
                yield name
            yield from permissions(dep)

    import inspect
    import re
    session = re.compile(r'user_from_token|_owner\(|\bowner\(|\bcustomer\(request|_authenticated\(|current_user')

    def body_access(endpoint):
        try:
            head = '\n'.join(inspect.getsource(endpoint).splitlines()[:40])
        except (OSError, TypeError):
            return None
        return 'сессия клиента' if session.search(head) else None

    table = {}
    for route, path in walk(app.routes):
        found = sorted(set(permissions(route.dependant)))
        access = ', '.join(f'право `{p}`' for p in found) if found else next(
            (label for prefix, label in PREFIX_ACCESS if path.startswith(prefix)), None) or body_access(route.endpoint) or 'открытый'
        for method in route.methods:
            table[(method.upper(), path)] = access
    return table


def render():
    os.environ.setdefault('APP_ENV', 'test')
    sys.path.insert(0, str(ROOT/'backend'))
    from app.main import app
    manifest = json.loads((ROOT/'release-manifest.template.json').read_text())
    access = access_table(app)
    rows = []
    for path, operations in sorted(app.openapi()['paths'].items()):
        for method, info in sorted(operations.items()):
            if method.lower() not in {'get','post','put','patch','delete','head','options'}:
                continue
            title = (info.get('summary') or info.get('operationId') or '').replace('|','\\|').replace('\n',' ')
            rows.append(f'| `{method.upper()}` | `{path}` | {title} | {access.get((method.upper(), path), "открытый")} |')
    return f'''# Каталог API — {manifest['distribution_tag']} / API v{manifest['version']}

Сгенерирован из OpenAPI текущих исходников. Миграция: `{manifest['migration_head']}`.
Авторизация, права, CSRF и принадлежность записей проверяются сервером; схема маршрута не заменяет права роли.
Сценарии: [руководство](ru/WORKSPACE_USER_GUIDE.md), [рефералы](ru/REFERRALS_CURRENT.md), [HTTP API](../API_REFERENCE_RU.md).

Legacy callbacks прежних агентов служат историческим операциям. Новые покупки используют YooKassa/Platega/RollyPay;
production gate остаётся закрытым без полного application E2E. Mobile purchase verify закрыт ответом 410.

Обновление: `PYTHONPATH=backend python scripts/generate-api-docs.py`; проверка: добавьте `--check`.
Колонка «Доступ» берётся из зависимостей маршрута: для админки — право роли (RBAC, `backend/app/security.py`),
для остальных — кто вызывает маршрут. Правила общие для всех маршрутов — в [API.md](ru/new/API.md).

| Метод | Путь | Операция | Доступ |
| --- | --- | --- | --- |
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
