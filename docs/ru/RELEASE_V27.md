# v27 — zero-placeholder runtime и актуальный дистрибутив

Дата выпуска: 9 октября 2026 года. Тег: `v27`. Внутренняя версия runtime/API: `21.5.1`.

## Контракт версии

| Контракт | Значение |
| --- | --- |
| GitHub tag | `v27` |
| Runtime/API | `21.5.1` |
| Миграция магазина | `0062_support_delivery_identity` |
| Support Pro | `0006` / 3.6 |
| Канал | stable |

## Изменения

- удалены `pass` и `NotImplementedError` из production Python-кода и шаблонов миграций;
- пустые exception/ORM-классы получили явные документированные контракты;
- подавление ошибок доставки, cleanup, Remnawave, меню, логотипов и node-agent заменено журналированием или безопасным fallback;
- добавлена AST-проверка zero-placeholder runtime;
- все текущие команды установки и обновления закреплены за `v27`;
- README, карта покрытия, changelog и документационные указатели синхронизированы.

## Установка

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v27/install.sh -o /root/shop-install.sh
sudo BRANCH=v27 bash /root/shop-install.sh
```

Или:

```bash
git clone --branch v27 --depth 1 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
sudo bash deploy/install-vps.sh
```

## Проверка исходников

```bash
python3 scripts/check-runtime-placeholders.py
python3 scripts/check-current-docs.py
python3 -m compileall -q backend/app support-pro/app
bash -n install.sh deploy/*.sh scripts/*.sh
```

Полный GitHub CI дополнительно выполняет backend и Support Pro tests, миграции PostgreSQL, frontend typecheck/build, Chromium E2E, Android/iOS и контейнерные проверки.

## Честные внешние ограничения

GitHub CI не заменяет реальные provider credentials и инфраструктуру владельца. Коммерческий gate остаётся закрытым, пока не сохранены evidence application E2E v2 для включённых платёжных агентов, отдельного Remnawave-стенда, SMTP, restore drill и подписанных мобильных пакетов. Эти пункты нельзя завершить фиктивными данными или только изменением документации.
