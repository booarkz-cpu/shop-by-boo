#!/usr/bin/env python3
"""Payment providers of the master prompt against the code (REQ-PAY-0003, 0004, 0007–0025, 0032).

Reads the registries from the source (no import of the backend, no keys needed) and writes
docs/PAYMENT_PROVIDER_INVENTORY.md: for every provider named by the owner — is there an adapter, which methods
the code routes to it, what the prompt expects, which tests exercise it. Nothing here says a provider works with
real money: that needs the owner's keys (O7 in docs/ru/new/BACKLOG.md).

    python scripts/audit/check_payment_provider_registry.py           # rewrite the document
    python scripts/audit/check_payment_provider_registry.py --check   # CI: the document matches the code
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'backend/app'
OUTPUT = ROOT / 'docs/PAYMENT_PROVIDER_INVENTORY.md'

# The owner's list (docs/prompts/MASTER_PROMPT_V6.md, lines 256, 260, 272–346): name, config id, expected methods.
PROMPT = [
    ('Telegram Stars', 'telegram_stars', None), ('Tribute', 'tribute', None), ('CryptoBot', 'cryptobot', None),
    ('Heleket', 'heleket', None), ('YooKassa', 'yookassa', 'card; sbp'), ('MulenPay', 'mulenpay', None),
    ('Pal24', 'pal24', 'sbp; card'), ('Platega', 'platega', 'динамические — проверить'), ('WATA', 'wata', None),
    ('FreeKassa', 'freekassa', 'sbp; card'), ('FreeKassa SBP', 'freekassa_sbp', None), ('FreeKassa Card', 'freekassa_card', None),
    ('CloudPayments', 'cloudpayments', 'выбор на странице провайдера'), ('Kassa AI', 'kassa_ai', 'sbp; card; sberpay'),
    ('RioPay', 'riopay', None), ('SeverPay', 'severpay', None), ('RollyPay', 'rollypay', 'sbp; card; crypto'),
    ('Overpay', 'overpay', 'динамические — проверить'), ('AuraPay', 'aurapay', 'card; sbp'),
    ('Etoplatezhi', 'etoplatezhi', 'card; sbp'), ('Antilopay', 'antilopay', 'card; sbp; sberpay'), ('Jupiter', 'jupiter', 'sbp'),
    ('Donut', 'donut', 'card; sbp; sbp_qr'), ('Lava', 'lava', 'card; sbp'), ('CisPay', 'cispay', 'card; sbp; crypto'),
    ('Anore', 'anore', 'sbp; card; yoomoney; crypto'), ('TabPay', 'tabpay', 'card; sbp'), ('ParityPay', 'paritypay', 'card; sbp'),
    ('Cashera', 'cashera', 'динамические — проверить'), ('Stripe', 'stripe', None), ('PayPal', 'paypal', None),
    ('Apple StoreKit', 'apple', None), ('Google Play Billing', 'google', None), ('Crypto Gateway', 'crypto', None),
    ('Sandbox', 'sandbox', None),
]
# Providers that are not checkout gateways: where their code lives.
OTHER = {
    'telegram_stars': ('telegram_stars.py', 'Счёт в боте: invoice, pre-checkout, successful_payment; подписки за Stars'),
    'tribute': ('tribute.py', 'Пополнение кошелька по ссылке Tribute, вебхук с подписью'),
    'stripe': ('payment_platform.py', 'Класс StripePlatform'), 'paypal': ('payment_platform.py', 'Класс PayPalPlatform'),
    'crypto': ('payment_platform.py', 'Класс CryptoGatewayPlatform'),
    'apple': ('payment_platform.py', 'Класс AppleStorePlatform: проверка покупки на сервере'),
    'google': ('payment_platform.py', 'Класс GooglePlayPlatform: проверка покупки на сервере'),
    'sandbox': ('payments.py', 'Класс SandboxProvider: тестовая касса без денег'),
}
CLASS = {'stripe': 'StripePlatform', 'paypal': 'PayPalPlatform', 'crypto': 'CryptoGatewayPlatform', 'apple': 'AppleStorePlatform',
         'google': 'GooglePlayPlatform', 'sandbox': 'SandboxProvider'}


def literal(path: Path, name: str):
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise SystemExit(f'{path}: {name} not found')


def tests_for(key: str) -> list[str]:
    word = re.compile(rf'(?<![a-z_]){re.escape(key)}(?![a-z_])', re.I)
    names = {'apple': 'AppleStore', 'google': 'GooglePlay', 'crypto': 'CryptoGateway'}
    pattern = re.compile(names[key]) if key in names else word
    found = [p.name for p in sorted((ROOT / 'tests').glob('test_*.py')) if 'requirements_register' not in p.name and pattern.search(p.read_text(encoding='utf-8'))]
    return found


def build() -> tuple[str, list[str]]:
    agents = literal(APP / 'payment_policy.py', 'PAYMENT_AGENTS')
    features = literal(APP / 'payment_policy.py', 'PROVIDER_CAPABILITIES')
    methods = literal(APP / 'payment_methods.py', 'CAPABILITIES')
    errors = []
    for agent in agents:  # the registries must agree with each other
        if agent not in features:
            errors.append(f'{agent}: в очереди касс, но нет в PROVIDER_CAPABILITIES')
        if agent not in methods:
            errors.append(f'{agent}: в очереди касс, но нет в payment_methods.CAPABILITIES')
    known = {key for _, key, _ in PROMPT}
    for agent in agents:
        if agent not in known:
            errors.append(f'{agent}: касса есть в коде, но её нет в списке владельца — добавьте в PROMPT')
    rows, present, absent = [], 0, []
    for title, key, expected in PROMPT:
        if key in agents:
            f = features[key]
            extra = [name for name, on in (('автопродление', f['recurring']), ('возврат', f['refunds'])) if on]
            where, what = 'Касса в очереди оплаты', '; '.join(sorted(methods[key])) + (' · ' + ', '.join(extra) if extra else '')
        elif key in ('freekassa_sbp', 'freekassa_card') and key.split('_')[1] in methods.get('freekassa', ()):
            where, what = 'Способ оплаты кассы `freekassa`', key.split('_')[1]
        elif key in OTHER and (APP / OTHER[key][0]).is_file() and (key not in CLASS or f'class {CLASS[key]}' in (APP / OTHER[key][0]).read_text(encoding='utf-8')):
            where, what = f'`backend/app/{OTHER[key][0]}`', OTHER[key][1]
        else:
            where, what = '**Нет в коде**', '—'
            absent.append(title)
        if where != '**Нет в коде**':
            present += 1
        tests = tests_for('freekassa' if key.startswith('freekassa_') else key) if where != '**Нет в коде**' else []
        shown = ', '.join(f'`{name}`' for name in tests[:3]) + (f' и ещё {len(tests) - 3}' if len(tests) > 3 else '') if tests else '—'
        state = '—' if where == '**Нет в коде**' else '`IMPLEMENTED`'
        rows.append(f'| {title} | `{key}` | {state} | {where} | {what} | {expected or "—"} | {shown} |')
    differ = []
    for title, key, expected in PROMPT:
        if key in agents and expected and ';' in expected:
            want = {m.strip() for m in expected.split(';')}
            have = set(methods[key])
            if want - have:
                differ.append(f'- {title}: владелец ждёт ещё `{"`, `".join(sorted(want - have))}`; в коде — `{"`, `".join(sorted(have))}`.')
    text = '\n'.join([
        '# Платёжные провайдеры: список владельца и код',
        '',
        '<!-- Файл создаёт scripts/audit/check_payment_provider_registry.py. Не править руками. -->',
        '',
        'Таблица собрана из исходного кода: `backend/app/payment_policy.py` (очередь касс, автопродление, возвраты),',
        '`backend/app/payment_methods.py` (способы оплаты) и модулей платформ. Список владельца — из мастер-промпта',
        '(`docs/prompts/MASTER_PROMPT_V6.md`, строки 256–346).',
        '',
        '**Что таблица доказывает и чего нет.** «Есть в коде» значит: адаптер написан и проверяется тестами с подменой',
        'кассы. Работа с настоящими деньгами не проверена ни для одной кассы: нужны тестовые ключи владельца',
        '(пункт O7 в [BACKLOG.md](ru/new/BACKLOG.md)).',
        '',
        'Статус — по шкале владельца. `IMPLEMENTED`: адаптер есть и покрыт тестами. До `CONFIGURED`, `SANDBOX_VERIFIED`',
        'и `PRODUCTION_VERIFIED` не дошла ни одна касса: для них нужны ключи. Прочерк — адаптера нет.',
        '',
        f'Из {len(PROMPT)} названий владельца в коде есть **{present}**, нет **{len(absent)}**: {", ".join(absent)}.',
        '',
        '| Провайдер | ID | Статус | Где в коде | Что умеет в коде | Что ждёт владелец | Тесты |',
        '| --- | --- | --- | --- | --- | --- | --- |',
        *rows,
        '',
        '## Расхождения по способам оплаты',
        '',
        'Код знает три способа: `sbp`, `card`, `crypto`. Способов `sberpay`, `yoomoney`, `sbp_qr` в коде нет.',
        '',
        *(differ or ['Расхождений нет.']),
        '',
        '## Чего нет и почему это не сделано сразу',
        '',
        'Адаптер нельзя написать честно без официального описания API кассы и тестового магазина: подпись вебхука,',
        'поля суммы и заказа, коды статусов у каждой кассы свои. Для касс из списка «нет в коде» нужно одно из двух:',
        'ссылка на документацию API или тестовые ключи.',
        '',
    ])
    return text, errors


def main() -> int:
    text, errors = build()
    if '--check' in sys.argv:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding='utf-8') != text:
            errors.append('docs/PAYMENT_PROVIDER_INVENTORY.md устарел: запустите scripts/audit/check_payment_provider_registry.py')
    elif not errors:
        OUTPUT.write_text(text, encoding='utf-8')
    for error in errors:
        print(f'x:1:1: {error}', file=sys.stderr)
    print('payment provider inventory ' + ('FAILED' if errors else 'OK'))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
