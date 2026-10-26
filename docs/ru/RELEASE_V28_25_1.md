# Выпуск v28.25.1 — обновление зависимостей и понятные ошибки в админке

Дистрибутив: `v28.25.1`. Runtime/API: `21.5.1`. Head магазина: `0076_growth` (без новых миграций). Support Pro: `0008` / 3.8. Дата и commit фиксируются тегом выпуска.

## Что изменилось

**Зависимости** (разобраны первые PR Dependabot)

- Магазин: FastAPI 0.161, Starlette 1.9, SQLAlchemy 2.1.6, Alembic 1.20.1, asyncpg 0.32, uvicorn 0.54, pydantic-settings 2.16 и патч-версии aiohttp, cryptography, pyjwt, paramiko, python-multipart, boto3. SQLAlchemy 2.1 больше не ставит `greenlet` сам — зависимость указана как `sqlalchemy[asyncio]`, без этого бэкенд не запускался.
- Support Pro: те же FastAPI, Starlette, SQLAlchemy, Alembic, asyncpg, а также redis 8.1, aiofiles 25.1, multidict 7.1, aiohttp 3.14.5, uvicorn, uvloop, websockets и др. `pydantic` остаётся 2.13: `aiogram` 3.31 не поддерживает 2.14.
- Админка и кабинет: React 19.3.1, TypeScript 7.0.2, lucide-react 1.61, Radix UI, Vitest 5.0.5, jsdom 30.1.3, Playwright 1.64.1.
- GitHub Actions: setup-node 7, setup-java 6, github-script 9, upload-artifact 7, download-artifact 8.

**Support Pro: один список версий.** Рядом с `support-pro/requirements.txt` (его ставят тесты и образ, его обновляет Dependabot) лежала копия `support-pro/app/requirements.txt`, которую проверял только аудит уязвимостей. Копия удалена; `tests/test_dependency_locks.py` следит, чтобы образ ставил тот же файл, что и тесты.

**Правила Dependabot:** мажорные версии `@types/node` не предлагаются (рантайм — Node 22), `pydantic` для Support Pro — ниже 2.14 до поддержки в `aiogram`. Порядок работы с обновлениями — [модуль 27](modules/27-releases-updates.md#обновления-зависимостей-dependabot).

**Админка: понятные ошибки проверки.** Если сервер отклоняет форму (ответ 422), админка показывает причину — например, «Ссылка должна начинаться с https://, tg:// или #раздел» — а не «HTTP 422».

## Обновление

Миграций нет.

```bash
cd /opt/vpn-shop && bash scripts/backup.sh
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.25.1 bash /opt/vpn-shop/scripts/update-from-github.sh
```

Ожидаемые head: магазин `0076_growth`, Support Pro `0008`.

## Проверка

- Полные наборы магазина и Support Pro на новых версиях, сборки админки, кабинета и Mini App, e2e админки, vitest кабинета, `pip-audit` списков Support Pro.
- `tests/test_dependency_locks.py` — один список версий Support Pro и `greenlet` для SQLAlchemy 2.1; `admin/e2e/app-config.spec.ts` — читаемая ошибка проверки.
