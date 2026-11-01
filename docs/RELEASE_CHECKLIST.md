# Чек-лист релиза

Дистрибутив `v28.57.0`, runtime/API `21.5.1`, миграция магазина `0088_filter_and_regions`,
Support Pro `0008`.

Отмечайте пункт только при наличии подтверждения. Правило простое: то, что не проверено, остаётся
непроверенным — см. [RELEASE_LIMITATIONS.md](RELEASE_LIMITATIONS.md).

## 1. Перед началом

- [ ] Рабочая директория чистая или изменения осознаны: `git status --porcelain`
- [ ] Текущая ветка — `main`, история синхронизирована: `git fetch && git status -sb`
- [ ] Чужие незакоммиченные изменения сохранены (`git stash list` не теряет работу)
- [ ] Определена версия: тег `vX.Y.Z` и версия runtime независимы (`release_identity.py`)

## 2. Проверки кода

```bash
ruff check backend scripts tests
while IFS= read -r -d '' f; do bash -n "$f" || echo "FAIL $f"; done < <(git ls-files -z '*.sh')
cd backend && python -m compileall -q app worker.py
```

- [ ] Lint Python — чисто
- [ ] Синтаксис всех shell-скриптов — чисто
- [ ] Компиляция backend — чисто

## 3. Тесты

```bash
cd backend
export MEDIA_DIR=/tmp/media APP_SECRET=ci-only-secret APP_ENV=test COOKIE_SECURE=false
export PAYMENTS_SANDBOX=true MOBILE_REQUIRE_PROOF=false AUTO_RENEW_ENABLED=false
python -m pytest -q ../tests --timeout=120
```

- [ ] Backend-тесты зелёные (эталон: 2507 собранных тестов, 0 падений)
- [ ] `tests/test_auto_update_api.py` и `tests/test_auto_update_agent.py` проходят
- [ ] Live-тесты либо пройдены, либо помечены `BLOCKED_*` в гайде

Помните: без `PAYMENTS_SANDBOX=true` и `APP_ENV=test`
`test_payment_provider_health_bootstraps_without_admin_page` падает — это окружение, а не дефект.

## 4. Фронтенды

```bash
cd admin   && npm ci && npm run typecheck && npm run build
cd cabinet && npm ci && npm run typecheck && npm test && npm run build
```

- [ ] admin: typecheck (оба tsconfig) — чисто
- [ ] admin: build — успешно
- [ ] cabinet: typecheck — чисто
- [ ] cabinet: vitest — успешно
- [ ] cabinet: build — успешно

## 5. Миграции и схема

```bash
cd backend
alembic heads     # один head: 0088_filter_and_regions
alembic upgrade head
```

- [ ] Один head, цепочка линейна
- [ ] Миграции применяются на чистой БД
- [ ] Миграции применяются на копии боевой БД
- [ ] Нет необратимых операций (`DROP COLUMN`, `DROP TABLE`) без процедуры восстановления
- [ ] Проверен откат: `alembic downgrade -1` на тестовой копии

## 6. Контракты документации

```bash
python3 scripts/check-current-docs.py
python3 scripts/check-runtime-placeholders.py
python3 scripts/generate-project-map.py --check
```

- [ ] Все три шага проходят
- [ ] Если добавлены новые файлы — карта перегенерирована:
      `git add <новые файлы> && python3 scripts/generate-project-map.py`
- [ ] Версии в `README.md`, `DOCUMENTATION.md`, `CHANGELOG.md`, `release-manifest.template.json`
      согласованы

## 7. Docker

```bash
cp .env.example .env && cp support-pro/.env.example support-pro/.env
docker compose -f docker-compose.yml config --quiet
docker compose --env-file .env.test -f docker-compose.test.yml config --quiet
docker compose build
docker compose up -d
docker compose ps
```

- [ ] `config` валиден
- [ ] Образы собираются
- [ ] Контейнеры запускаются не от root (где это требуется)
- [ ] Redis требует аутентификацию
- [ ] Образы PostgreSQL закреплены по digest

## 8. Health checks

```bash
curl -s localhost:8000/health/live  | jq .
curl -s localhost:8000/health/ready | jq .
curl -s localhost:8000/health       | jq .
```

- [ ] `/health/live` → `ok: true`, версия совпадает с `APP_VERSION`
- [ ] `/health/ready` → `database: true`, `redis: true`
- [ ] `/health` → `ok: true`

## 9. Ключевые сценарии (smoke)

- [ ] Админка открывается, разделы грузятся, чёрных страниц нет
- [ ] Личный кабинет открывается
- [ ] Вход админа, выход, повторный вход
- [ ] Тарифы отображаются, названия согласованы
- [ ] Создание платежа в sandbox выдаёт подписку
- [ ] Подписка появляется в Remnawave (если ключи есть)
- [ ] `/start` в боте отвечает
- [ ] Раздел «Обновления» показывает фактическую версию (не заглушку)

## 10. Безопасность

- [ ] Нет секретов в отслеживаемых файлах: `git grep -nE 'sk_live|ghp_|github_pat_'`
- [ ] `.env` не в индексе: `git ls-files | grep -c '^\.env$'` → `0`
- [ ] Права на админские эндпоинты проверяются на сервере (`require_permission`)
- [ ] Webhook-подписи проверяются
- [ ] `scripts/security-scan.sh` выполнен
- [ ] Зависимости без известных критических CVE (`pip-audit` / Dependabot)

## 11. Резервное копирование и восстановление

- [ ] `scripts/backup.sh` создаёт шифрованный пакет
- [ ] Пакет **восстановлен** на тестовой машине (не просто создан)
- [ ] Известно время восстановления
- [ ] `.rollback` содержит актуальный снимок перед релизом

## 12. Релиз

- [ ] `CHANGELOG.md` обновлён
- [ ] Release notes подготовлены
- [ ] Ограничения зафиксированы в [RELEASE_LIMITATIONS.md](RELEASE_LIMITATIONS.md)
- [ ] Тег создан: `git tag -a vX.Y.Z -m "..."` и запушен
- [ ] CI зелёный на этом коммите
- [ ] `publish-release.yml` опубликовал релиз (публикация только при зелёных `ci.yml` и `docker.yml`)
- [ ] Проверены ассеты релиза: `.zip`, `.zip.sha256`, `_manifest.json`
- [ ] Ссылка на релиз проверена открытием

## 13. После релиза

- [ ] Автообновление видит новую версию: `scripts/auto-update.sh status`
- [ ] Тестовый сервер обновился ночью без вмешательства
- [ ] Production обновлён и health checks зелёные
- [ ] Журналы без новых ошибок за сутки
- [ ] Отчёт о релизе составлен с реальными ссылками

## Откат, если что-то пошло не так

```bash
sudo bash scripts/rollback.sh                      # последний снимок + latest.sql
sudo bash scripts/rollback.sh <snapshot.tar.gz> <dump.sql>
```

`rollback.sh` требует **и** архив, **и** дамп БД. Без дампа он откажется работать и не тронет
установку. После отката ставится флаг `RECOVERY_MODE` — автообновление остановлено до ручной
проверки. Снятие флага описано в
[AUTO_UPDATE_TROUBLESHOOTING.md](AUTO_UPDATE_TROUBLESHOOTING.md).
