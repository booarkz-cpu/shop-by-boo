# Журнал автоматизации и аудита

Формат записи: дата, что сделано, чем подтверждено, что осталось. Записи не переписываются задним
числом: если проверка не проводилась, так и указано.

## 2026-10 — аудит v28.54.0

**Контекст.** Дистрибутив `v28.54.0`, runtime/API `21.5.1`, миграция `0088_filter_and_regions`.
Работа велась на клоне `booarkz-cpu/shop-by-boo` (коммит `aad96649`), рабочее дерево чистое.

**Окружение проверки.** Песочница Linux, Python 3.13.16, Node.js 20.20.2, npm 10.8.2, ruff 0.14.2.
Docker, PostgreSQL-сервер, Android SDK и Xcode отсутствуют — соответствующие проверки помечены
`BLOCKED_ACCESS`.

### Инвентаризация репозиториев

Изучены семь репозиториев. Права на запись: `shop-by-boo`, `remnawave-manager`. Остальные пять —
только чтение (чужие проекты).

| Репозиторий | Роль | Код включён в проект |
| --- | --- | --- |
| `booarkz-cpu/shop-by-boo` | основной магазин | — (это он и есть) |
| `booarkz-cpu/remnawave-manager` | управление Remnawave | нет, отдельный сервис |
| `eGamesAPI/remnawave-reverse-proxy` | reverse proxy | нет, только референс |
| `Case211/remnawave-admin` | админка | нет, только референс |
| `BEDOLAGA-DEV/remnawave-bedolaga-telegram-bot` | бот | нет, только референс |
| `BEDOLAGA-DEV/bedolaga-cabinet` | кабинет | нет, только референс |
| `STEP-CORP/StepBot` | бот | нет, только референс |

Сторонний код не копировался: лицензии не проверены на совместимость, а магазин имеет собственные
реализации (`backend/app/remnawave.py`, `remnawave_events.py`, `remnawave_shop_api.py`).

### Выполненные проверки

| Проверка | Команда | Результат |
| --- | --- | --- |
| Lint | `ruff check backend scripts tests` | PASS — All checks passed |
| Shell-синтаксис | `bash -n` по всем `*.sh` | PASS |
| Компиляция | `python -m compileall -q app worker.py` | PASS |
| Backend-тесты | `pytest -q tests` | PASS — 2507 собрано, 0 падений |
| Typecheck admin | `tsc --noEmit` + `tsc -p tsconfig.ui.json` | PASS |
| Typecheck cabinet | `tsc --noEmit` | PASS |
| Build admin | `next build` | PASS — 3/3, csp-externalize 12 скриптов |
| Build cabinet | `next build` | PASS — 3/3 |
| Контракт документации | `check-current-docs.py` | PASS |
| Заглушки | `check-runtime-placeholders.py` | PASS |
| Карта проекта | `generate-project-map.py --check` | PASS |
| Миграции | `alembic heads` | PASS — один head, 88 миграций |
| Docker Compose | `docker compose config` | BLOCKED_ACCESS — нет Docker; YAML разобран программно |

### Найденные и исправленные дефекты

| Дефект | Причина | Исправление | Файл | Проверка |
| --- | --- | --- | --- | --- |
| В разделе «Обновления» вместо версии — заглушка «корпоративный контур» | Жёстко вписанный текст остался от ранней вёрстки | Вывод фактической версии из ответа `/api/admin/github-update` | `admin/src/main.tsx` | typecheck чист, профильные тесты 31 passed |

### Перепроверенные исторические симптомы

Все симптомы из задания проверены на текущем коде. Ни один не воспроизвёлся.

- `Cannot read properties of undefined (reading 'trim')` — 104 вызова `.trim()`, ни одного на
  possibly-undefined.
- `(s || []).map is not a function` — паттерн отсутствует.
- Чёрные страницы админки и кабинета — обе сборки успешны и prerender'ят страницы.
- `AsyncSessionLocal` vs `SessionLocal` — не дефект: `db.py` объявляет
  `SessionLocal = async_sessionmaker(...)`; `AsyncSessionLocal` не существует нигде.
- Ошибка установщика «около строки 427» — `install.sh` 77 строк; реальный установщик
  `deploy/install-vps.sh` проходит `bash -n`.

### Ложная тревога, зафиксированная честно

`tests/test_v44_enterprise_suite.py::test_payment_provider_health_bootstraps_without_admin_page`
падал при первом прогоне. Причина — отсутствие `PAYMENTS_SANDBOX=true` и `APP_ENV=test` в моём
окружении, а не дефект кода: песочница платежей разрешена только вне production
(`backend/app/sandbox_mode.py`). С переменными как в CI — 5 passed, 2 skipped. Как баг не
зарегистрирован.

### Созданные документы

`docs/AUTO_UPDATE.md`, `docs/AUTO_UPDATE_SECURITY.md`, `docs/AUTO_UPDATE_TROUBLESHOOTING.md`,
`docs/AUTO_UPDATE_TESTING.md`, `docs/TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md`,
`docs/RELEASE_CHECKLIST.md`, `docs/RELEASE_LIMITATIONS.md`, `docs/EXTERNAL_DEPENDENCIES.md`,
`docs/CLAUDE_GITHUB_AUTOMATION.md`, `docs/AUTOMATION_LOG.md`, `docs/MASTER_ROADMAP_VPN_SHOP.md`,
`docs/ROADMAP_UI_AND_SCREENSHOTS.md`, `.github/workflows/claude-roadmap.yml`.

Существующие `docs/modules/auto_update_and_rollback.md` и 13 workflow не дублировались — новые
документы на них ссылаются.

### Выявленная зависимость порядка работ

`scripts/generate-project-map.py --check` сверяет `docs/PROJECT_FILE_MAP.md` со списком
**отслеживаемых git файлов**. Добавление документов без перегенерации карты роняет CI-шаг
«Current release documentation contract». Поэтому порядок: `git add` новых файлов →
`generate-project-map.py` → коммит вместе с картой.

### Оставшиеся задачи

| Приоритет | Задача | Блокер |
| --- | --- | --- |
| P0 | Живой прогон платежей хотя бы у одного провайдера | нет ключей |
| P0 | Проверка восстановления из `scripts/backup.sh` | нет сервера |
| P1 | Живая синхронизация с Remnawave | нет токена панели |
| P1 | Docker build и запуск 17 сервисов | нет Docker |
| P1 | Установщик на чистом VPS | нет VPS |
| P1 | Ночное автообновление по расписанию | нет systemd/root |
| P2 | Сборка и подпись мобильных приложений | нет SDK/ключей |
| P2 | Живая проверка `initData` Mini App | нет `BOT_TOKEN` |
| P3 | Публикация Wiki на трёх языках | нужны права Wiki; эквивалент — структура `docs/{ru,en,uk}` |

Подробно — [RELEASE_LIMITATIONS.md](RELEASE_LIMITATIONS.md).
