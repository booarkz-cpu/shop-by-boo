# Автоматизация GitHub и Claude Code

Дистрибутив `v28.56.0`, runtime/API `21.5.1`.

Как устроена автоматизация репозитория, какие права нужны, и что намеренно **не** автоматизировано.

## 1. Существующие workflow

| Файл | Триггер | Назначение |
| --- | --- | --- |
| `ci.yml` | `pull_request`, `push` в `main`, `workflow_dispatch` | Backend, lint, тесты, фронтенды, compose, контейнеры, Android, iOS |
| `docker.yml` | push, dispatch | Сборка образов |
| `publish-release.yml` | `workflow_run` после `ci.yml` и `docker.yml` | Публикация релиза при зелёных проверках |
| `deploy.yml` | `workflow_dispatch`, `workflow_run` | Деплой на сервер по SSH |
| `dependabot-automerge.yml` | расписание | Автослияние зависимостей |
| `build-mobile.yml`, `mobile-release.yml`, `mobile-screenshots.yml` | dispatch | Мобильные сборки |
| `hetzner-live.yml`, `load-live.yml`, `load-security.yml`, `payments-acceptance.yml`, `remnawave-live.yml` | dispatch | Live-проверки с секретами |

Добавлен этим релизом: `.github/workflows/claude-roadmap.yml` (§3).

## 2. Принципы, заложенные в существующие workflow

Проверено по файлам:

- `permissions: contents: read` на уровне workflow в `ci.yml` — минимальные права;
- `concurrency` с `cancel-in-progress` в `ci.yml`, `cancel-in-progress: false` в `publish-release.yml`
  и `deploy.yml` — релиз и деплой не отменяются на середине;
- `publish-release.yml` не публикует релиз, если `ci.yml` или `docker.yml` не завершились успешно
  **на том же коммите**, что и текущий `main`;
- `deploy.yml` не выполняется, если секреты деплоя пусты (`HAS_HOST`, `HAS_USER`, `HAS_KEY`,
  `HAS_PATH` → `skip`), и требует `vars.AUTO_DEPLOY == 'true'` для автоматического запуска;
- `timeout-minutes` заданы на долгих job'ах;
- тесты запускаются с `--timeout` и `--timeout-method=thread`, вывод пишется в файл, а не в pipe —
  чтобы зависший дочерний процесс не блокировал шаг.

## 3. `claude-roadmap.yml`

Ночная детерминированная проверка состояния репозитория. **Не вызывает внешние LLM API** и не
требует секретов: если бы workflow обращался к модели, он зависел бы от ключа и мог бы сам
изменять код без проверки — это противоречит требованию не публиковать непроверенный код.

Что делает:

1. `scripts/check-current-docs.py` — согласованность версий;
2. `scripts/check-runtime-placeholders.py` — отсутствие заглушек и `pass` в production-коде;
3. `scripts/generate-project-map.py --check` — актуальность карты файлов;
4. `ruff check backend scripts tests`;
5. `alembic heads` — ровно один head;
6. сверка `docs/AUTOMATION_LOG.md` на наличие записи о текущем месяце.

Защита от рекурсии и зацикливания:

- `permissions: contents: read` — workflow не может ничего закоммитить;
- `concurrency` без `cancel-in-progress` — не отменяет сам себя;
- нет триггера `push`, только `schedule` и `workflow_dispatch` — не порождает цепочку запусков;
- `timeout-minutes: 15`.

Умышленно не делает: не коммитит, не пушит, не создаёт PR, не трогает секреты. Автоматический
коммит сгенерированного кода без ревью — источник непроверенных изменений.

## 4. Права и секреты

| Имя | Тип | Нужен для |
| --- | --- | --- |
| `GITHUB_TOKEN` | автоматический | Публикация релиза (`contents: write` объявлен в самом workflow) |
| `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH`, `DEPLOY_PORT` | secrets | `deploy.yml` |
| `HETZNER_API_TOKEN` | secret | `hetzner-live.yml`, автомасштабирование |
| `LOAD_TARGET_URL`, `WEBHOOK_BASE_URL` | secrets | нагрузочные и webhook-проверки |
| `AUTO_DEPLOY` | variable | Разрешение автодеплоя (`'true'`) |
| `IOS_EXPORT_METHOD` | variable | Метод экспорта iOS |

Платёжные и мобильные секреты — в [TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md](TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md).

Правила: не печатать секреты в лог, не передавать их в `pull_request_target` от форков, не
повышать `permissions` сверх необходимого.

## 5. Публикация релиза

Порядок, реализованный в `publish-release.yml`:

1. Дождаться завершения `ci.yml` и `docker.yml` на `main`.
2. Убедиться, что проверяемый SHA — актуальный `main`; иначе ждать следующий коммит.
3. Найти успешные прогоны обоих workflow именно для этого SHA.
4. `check-current-docs.py`, затем `package-distribution.py --ci-run <url>`.
5. Опубликовать ассеты и запустить Docker с тегом.

Следствие: релиз нельзя опубликовать в обход CI. Это правильно и менять не нужно.

## 6. Ограничения автоматизации

| Ограничение | Причина |
| --- | --- |
| Нет автоматического ночного мержа в `main` | Непроверенный код не должен попадать в стабильный канал |
| `claude-roadmap.yml` не вызывает LLM | Зависимость от секрета и отсутствие ревью |
| Автообновление не идёт из `main` | Только стабильные релизы с проверкой SHA-256 |
| Деплой по умолчанию выключен | Нужны секреты и `AUTO_DEPLOY=true` |
| Ветки `audit/*` не удаляются автоматически | История аудитов сохраняется осознанно |

## 7. Локальный эквивалент CI

```bash
ruff check backend scripts tests
cd backend && python -m compileall -q app worker.py && alembic heads
python3 scripts/check-current-docs.py
python3 scripts/check-runtime-placeholders.py
python3 scripts/generate-project-map.py --check
cd admin && npm ci && npm run typecheck && npm run build
cd ../cabinet && npm ci && npm run typecheck && npm test && npm run build
```

Журнал фактически выполненных работ: [AUTOMATION_LOG.md](AUTOMATION_LOG.md).
