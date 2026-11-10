#!/usr/bin/env python3
"""Requirements register of the owner's master prompt (docs/prompts/MASTER_PROMPT_V6.md).

Every requirement of the prompt gets a stable ID, the exact source lines and its text word for word
(nothing is shortened). The status of a requirement is not guessed: it is taken from
docs/requirements/status.json, and a requirement without a record there is NOT_TESTED.

    python scripts/audit/requirements_register.py           # rewrite the register
    python scripts/audit/requirements_register.py --check   # CI: the register matches the prompt and the statuses

--check also refuses: a status record for an unknown ID, a PASS/PARTIAL without evidence, evidence that
points to a file that does not exist, and a requirement that disappeared from the register.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'docs/prompts/MASTER_PROMPT_V6.md'
STATUS = ROOT / 'docs/requirements/status.json'
REGISTER = ROOT / 'docs/requirements/register.json'
OUTPUT = ROOT / 'docs/REQUIREMENTS_MASTER_REGISTER.md'

STATUSES = ('PASS', 'PARTIAL', 'FAIL', 'NOT_IMPLEMENTED', 'BLOCKED_EXTERNAL', 'BLOCKED_SECRETS',
            'SOURCE_UNAVAILABLE', 'NOT_APPLICABLE', 'NOT_TESTED', 'RETIRED_BY_OWNER')
NEED_EVIDENCE = {'PASS', 'PARTIAL'}

# Part I: top heading (and, where one section mixes products, a deeper heading) -> ID prefix.
PART1 = {
    'Document Purpose': 'GOV', 'Critical Rule': 'GOV', 'Role': 'GOV', 'Primary Repository': 'MIG',
    'Source Repositories': 'MIG', 'Monorepo': 'MIG', 'Full Audit': 'QA', 'Payment Ecosystem': 'PAY',
    'Remnawave': 'RW', 'Masque': 'MASQUE', 'Node Manager': 'NODE', 'Server Installation Maintenance': 'NODE',
    'Auto Selection': 'AUTO', 'Additional Infrastructure': 'INFRA', 'Backend Api Database': 'API', 'Ui Ux': 'UI',
    'User Cabinet Telegram': 'SHOP', 'Mobile': 'MOBILE', 'Docker Installer Vps Termux': 'INFRA',
    'Github Cicd': 'CI', 'Documentation': 'DOC', 'Screenshot Coverage': 'QA', 'Balanced Development': 'GOV',
    'Acceptance Checklist': 'GOV', 'Audit Automation': 'QA', 'Autonomous Cycle': 'GOV', 'State Tracking': 'GOV',
    'Final Reports': 'GOV', 'Git Security': 'SEC', 'First Execution Sequence': 'GOV', 'Acceptance Criteria': 'GOV',
    'Non Loss Rule': 'GOV', 'Final Objective': 'GOV', 'Instruction To Claude': 'GOV',
}
DEEPER = {
    'Корги Люси: Клиент': 'CLIENT', 'VPN Shop by Corgi Lucy': 'SHOP', 'Lucy Admin': 'ADMIN',
    'Autonomous Execution Strict': 'GOV', 'Repository Migration Expanded': 'MIG',
    'Vpn Shop Brand And Customer Content': 'BRAND', 'Server Maintenance Screenshot Acceptance': 'NODE',
    'Protocol Repair': 'NODE', 'Node Reconnect Matrix': 'NODE', 'Auto Selection Pool Ui': 'AUTO',
    'Network And Censorship Diagnostics': 'NODE', 'Product And Service Reliability': 'QA',
    'Expanded Test Matrix': 'QA', 'Expanded State Requirements': 'GOV',
}
PART2 = {'II.1': 'QA', 'II.2': 'NODE', 'II.3': 'AUTO', 'II.4': 'BRAND', 'II.5': 'DOC', 'II.6': 'GOV', 'II.7': 'GOV'}
PART4 = {23: 'GOV', 24: 'ARCH', 25: 'CLIENT', 26: 'SHOP', 27: 'ADMIN', 28: 'PAY', 29: 'RW', 30: 'INFRA', 31: 'INFRA',
         32: 'SEC', 33: 'UI', 34: 'QA', 35: 'CI', 36: 'PERF', 37: 'DOC', 38: 'GOV', 39: 'GOV', 40: 'GOV'}
PRODUCT = {'CLIENT': 'Клиент', 'SHOP': 'Магазин', 'BRAND': 'Магазин', 'ADMIN': 'Админка'}
AREA = {
    'GOV': 'Правила работы и приёмка', 'MIG': 'Монорепозиторий и перенос', 'CLIENT': '«Корги Люси: Клиент»',
    'SHOP': 'Магазин, кабинет, Telegram', 'BRAND': 'Бренд и тексты', 'ADMIN': 'Lucy Admin', 'PAY': 'Платежи',
    'RW': 'Remnawave', 'MASQUE': 'MASQUE', 'NODE': 'Ноды: установка, обслуживание, защита', 'AUTO': 'Автовыбор',
    'INFRA': 'Инфраструктура, установщик, копии', 'API': 'Backend, API, база', 'UI': 'Интерфейсы', 'MOBILE': 'Мобильные приложения',
    'CI': 'CI/CD и выпуски', 'DOC': 'Документация', 'QA': 'Аудит, тесты, скриншоты', 'SEC': 'Безопасность',
    'ARCH': 'Архитектура', 'PERF': 'Производительность и стоимость',
}
FILE_NAME = re.compile(r'(?<![\w/.-])((?:\.github/|docs/|scripts/|artifacts/)[\w./-]+\.(?:md|py|yml|json)|[A-Z][A-Z0-9_]{5,}\.md|(?:check|generate|run)_[a-z_]+\.py)')


def parse() -> list[dict]:
    lines = SOURCE.read_text(encoding='utf-8').split('\n')
    part2 = next(i for i, line in enumerate(lines) if line.startswith('## Часть II.'))
    part3 = next(i for i, line in enumerate(lines) if line.startswith('## Часть III.'))
    part4 = next(i for i, line in enumerate(lines) if line.startswith('# ЧАСТЬ IV.'))
    items: list[dict] = []

    def add(prefix: str, path: list[str], first: int, last: int, text: str) -> None:
        text = text.strip()
        if text:
            items.append({'prefix': prefix, 'path': ' → '.join(path), 'lines': [first + 1, last + 1], 'text': text})

    # Part I: a requirement is the text under a heading, up to the next heading.
    path: list[tuple[int, str]] = []
    start = next(i for i, line in enumerate(lines) if line.startswith('## Часть I.'))
    block: list[tuple[int, str]] = []

    def flush1() -> None:
        if not block:
            return
        names = [name for _, name in path]
        prefix = PART1.get(names[0], 'GOV') if names else 'GOV'
        for name in names:
            prefix = DEEPER.get(name, prefix)
        add(prefix, ['Часть I'] + names, block[0][0], block[-1][0], '\n'.join(text for _, text in block))
        block.clear()

    for i in range(start + 1, part2):
        line = lines[i]
        heading = re.match(r'^(#{3,6}) (.+)$', line)
        if heading:
            flush1()
            level = len(heading.group(1))
            path[:] = [p for p in path if p[0] < level] + [(level, heading.group(2).strip())]
        elif line.strip():
            block.append((i, re.sub(r'^<text>(.*)</text>$', r'\1', line.strip())))
    flush1()

    # Parts II and IV: a requirement is a bullet or a numbered item (with its nested lines), or a paragraph.
    def bullets(first: int, last: int, part: str, prefix_of) -> None:
        heads: list[tuple[int, str]] = []
        current: list[tuple[int, str]] = []

        def flush() -> None:
            if current:
                names = [name for _, name in heads]
                add(prefix_of(names), [part] + names, current[0][0], current[-1][0], '\n'.join(t for _, t in current))
                current.clear()

        for i in range(first, last):
            line = lines[i]
            heading = re.match(r'^(#{2,4}) (.+)$', line)
            if heading:
                flush()
                level = len(heading.group(1))
                heads[:] = [h for h in heads if h[0] < level] + [(level, heading.group(2).strip())]
            elif not line.strip() or line.startswith('>') or line.strip() == '---':
                flush()
            elif re.match(r'^(- |\d+\. )', line):
                flush()
                current.append((i, line.strip()))
            elif line.startswith(' ') and current:
                current.append((i, line.rstrip()))
            else:
                if current and re.match(r'^(- |\d+\. )', current[0][1]):
                    flush()
                current.append((i, line.strip()))
        flush()

    bullets(part2 + 1, part3, 'Часть II', lambda names: PART2[names[0].split('.')[0] + '.' + names[0].split('.')[1][:1]] if names else 'GOV')
    bullets(part4 + 1, len(lines), 'Часть IV', lambda names: PART4.get(int(re.match(r'(\d+)', names[0]).group(1)), 'GOV') if names else 'GOV')

    counters: Counter[str] = Counter()
    for item in items:
        counters[item['prefix']] += 1
        item['id'] = f"REQ-{item['prefix']}-{counters[item['prefix']]:04d}"
        item['sha'] = hashlib.sha256(item['text'].encode()).hexdigest()[:12]
        item['product'] = PRODUCT.get(item['prefix'], 'Все три')
        item['files'] = sorted(set(FILE_NAME.findall(item['text'])))
    return items


def find(name: str) -> str | None:
    """Where a file named in the prompt lives in the repository (the prompt often gives only the name)."""
    if (ROOT / name).is_file():
        return name
    base = name.rsplit('/', 1)[-1]
    for variant in (base, base.replace('_', '-')):  # the repository names its scripts with hyphens
        for folder in ('scripts/audit', 'scripts'):
            if variant.endswith('.py') and (ROOT / folder / variant).is_file():
                return f'{folder}/{variant}'
    for folder in ('docs', 'docs/ru', 'docs/ru/new', 'docs/architecture', 'scripts/audit', 'scripts', '.'):
        if (ROOT / folder / base).is_file():
            return str(Path(folder) / base) if folder != '.' else base
    return None


def render(items: list[dict], status: dict) -> str:
    def state(item):
        return status.get(item['id'], {}).get('status', 'NOT_TESTED')

    total = len(items)
    count = Counter(state(item) for item in items)
    confirmed = count['PASS']
    out = [
        '# Реестр требований мастер-промпта',
        '',
        '<!-- Файл создаёт scripts/audit/requirements_register.py. Не править руками: статусы — в docs/requirements/status.json. -->',
        '',
        'Источник: [`docs/prompts/MASTER_PROMPT_V6.md`](prompts/MASTER_PROMPT_V6.md) — мастер-промпт владельца, сохранён слово в слово.',
        'Каждое требование взято из него без сокращений, с номерами строк. Часть III промпта (исходный XML) повторяет Часть I и служит для сверки.',
        '',
        'Статус ставится только по проверке с доказательством. Требование без записи в `docs/requirements/status.json` — `NOT_TESTED`:',
        'это значит «ещё не сверено с кодом», а не «не сделано».',
        '',
        '## Итог',
        '',
        f'- Требований: **{total}**, у всех есть ссылка на строки источника.',
        f'- Подтверждено (`PASS`): **{confirmed}** — {confirmed * 100 / total:.1f}%.',
        '',
        '| Статус | Сколько | Что значит |',
        '| --- | ---: | --- |',
    ]
    meaning = {
        'PASS': 'Проверено, доказательство указано', 'PARTIAL': 'Сделано частично, остаток описан', 'FAIL': 'Проверка не пройдена',
        'NOT_IMPLEMENTED': 'Функции нет', 'BLOCKED_EXTERNAL': 'Нужен внешний ресурс: сервер, устройство, аккаунт',
        'BLOCKED_SECRETS': 'Нужны ключи или токены владельца', 'SOURCE_UNAVAILABLE': 'Точный текст задачи не найден в доступных источниках',
        'NOT_APPLICABLE': 'Не относится к проекту', 'NOT_TESTED': 'Ещё не сверено с кодом', 'RETIRED_BY_OWNER': 'Отменено владельцем',
    }
    for name in STATUSES:
        if count[name]:
            out.append(f'| `{name}` | {count[name]} | {meaning[name]} |')
    out += ['', '| Раздел | Требований | PASS | PARTIAL | Блокировано | Не сверено |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for prefix, title in AREA.items():
        group = [item for item in items if item['prefix'] == prefix]
        if group:
            c = Counter(state(item) for item in group)
            blocked = c['BLOCKED_EXTERNAL'] + c['BLOCKED_SECRETS'] + c['SOURCE_UNAVAILABLE']
            out.append(f"| {title} | {len(group)} | {c['PASS']} | {c['PARTIAL']} | {blocked} | {c['NOT_TESTED']} |")
    for prefix, title in AREA.items():
        group = [item for item in items if item['prefix'] == prefix]
        if not group:
            continue
        out += ['', f'## {title}', '']
        for item in group:
            record = status.get(item['id'], {})
            first, last = item['lines']
            where = f'строка {first}' if first == last else f'строки {first}–{last}'
            out += [f"### {item['id']} — `{state(item)}`", '',
                    f"- Источник: {item['path']} ({where}). Продукт: {item['product']}."]
            if record.get('platforms'):
                out.append(f"- Платформы: {record['platforms']}.")
            if item['files']:
                found = [f'`{name}` — ' + (f'есть (`{find(name)}`)' if find(name) else 'нет') for name in item['files']]
                out.append('- Названные файлы: ' + '; '.join(found) + '.')
            if record.get('evidence'):
                out.append('- Доказательство: ' + '; '.join(f'`{path}`' for path in record['evidence']) + '.')
            if record.get('note'):
                out.append(f"- Примечание: {record['note']}")
            out += ['', *('> ' + line if line else '>' for line in item['text'].split('\n')), '']
    return '\n'.join(out).rstrip() + '\n'


def main() -> int:
    check = '--check' in sys.argv
    items = parse()
    status = json.loads(STATUS.read_text(encoding='utf-8')) if STATUS.exists() else {}
    errors = []
    ids = {item['id'] for item in items}
    for key, record in status.items():
        if key not in ids:
            errors.append(f'{key}: статус для неизвестного требования')
            continue
        if record.get('status') not in STATUSES:
            errors.append(f"{key}: неизвестный статус {record.get('status')}")
        if record.get('status') in NEED_EVIDENCE and not record.get('evidence'):
            errors.append(f'{key}: {record["status"]} без доказательства')
        for path in record.get('evidence', []):
            if not (ROOT / path.split('::')[0].split('#')[0]).exists():
                errors.append(f'{key}: доказательство не найдено: {path}')
        if record.get('status') not in ('PASS', 'NOT_TESTED', 'NOT_APPLICABLE') and not record.get('note'):
            errors.append(f'{key}: для статуса {record.get("status")} нужно примечание, что осталось или что мешает')
    register = json.dumps([{k: item[k] for k in ('id', 'lines', 'sha', 'path')} for item in items], ensure_ascii=False, indent=1) + '\n'
    text = render(items, status)
    if check:
        if not REGISTER.exists() or REGISTER.read_text(encoding='utf-8') != register:
            errors.append('docs/requirements/register.json не совпадает с промптом: требование изменено или пропало')
        if not OUTPUT.exists() or OUTPUT.read_text(encoding='utf-8') != text:
            errors.append('docs/REQUIREMENTS_MASTER_REGISTER.md устарел: запустите scripts/audit/requirements_register.py')
    else:
        if REGISTER.exists():
            gone = {entry['id'] for entry in json.loads(REGISTER.read_text(encoding='utf-8'))} - ids
            if gone:
                errors.append(f'требования пропали из реестра (удалять запрещено): {sorted(gone)}')
        if not errors:
            REGISTER.write_text(register, encoding='utf-8')
            OUTPUT.write_text(text, encoding='utf-8')
    for error in errors:
        print(f'x:1:1: {error}' if check else error, file=sys.stderr)
    count = Counter(status.get(item['id'], {}).get('status', 'NOT_TESTED') for item in items)
    print(f'requirements: {len(items)}; ' + ', '.join(f'{name} {count[name]}' for name in STATUSES if count[name]))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
