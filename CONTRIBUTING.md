# Как вносить изменения

[English summary below](#english-summary)

## Порядок

1. Ветка от свежего `main`. Прямых коммитов в `main` нет — только PR.
2. PR сливается только при полностью зелёном CI, включая iOS. Слияние — squash.
3. Смена версии запускает выпуск на GitHub автоматически. После смены версии обновите вручную:
   - `release_title` в `release-manifest.template.json`;
   - раздел «Новое в» в README и CHANGELOG;
   - `docs/ru/RELEASE_V28_X_0.md`.

## Правила кода

- `backend/app/main.py` короче 1000 строк. Новые модули — отдельными роутерами (`backend/app/routers.py`).
- База данных меняется только миграциями Alembic (`backend/alembic/versions/`), с тестом туда и обратно.
- Никаких секретов в репозитории, логах и скриншотах. Демо-данные — без настоящих e-mail, телефонов, токенов и ссылок подписок.
- Без заглушек и «пустых» переключателей: функция либо работает, либо её нет в интерфейсе.
- iOS: режим Swift 6, строгая проверка многопоточности без замечаний ([IOS_ARCHITECTURE](docs/ru/new/IOS_ARCHITECTURE.md)).

## Проверки перед PR

```bash
ruff check backend scripts tests support-pro
python3 scripts/check-current-docs.py
python3 scripts/check-doc-links.py
python3 scripts/check-runtime-placeholders.py
python3 scripts/generate-project-map.py --check
```

Новый раздел админки:
- зарегистрировать в `apps/lucy-admin/web/src/sections.ts`;
- добавить модуль в `backend/app/admin_center.py`;
- снять скриншот на стенде `tests/passkey_browser_server.py`: `cd apps/lucy-admin/web && node scripts/screenshots-catalog.mjs "$PWD/../../.."`. Без скриншота `tests/test_screenshots.py` не пройдёт.

## Безопасность

Об уязвимостях — не в открытых issue, а по [SECURITY.md](SECURITY.md).

## English summary

- Branch from `main` and open a pull request; it is squash-merged only when every CI check, iOS included, is green.
- Database changes go through Alembic migrations only. Keep `backend/app/main.py` under 1000 lines.
- Never commit secrets or real customer data.
- Run the checks above before opening a PR.
- A new admin section needs a screenshot (`tests/test_screenshots.py`).
- Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
