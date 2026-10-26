> Актуальная инструкция дистрибутива v28.26.0. Runtime/API `21.5.1`, head магазина `0076_growth`, Support Pro `0008`.

# 27. Диагностика и обновления

## Для чего

- **Диагностика** — проверка подключений к базе, Redis и Remnawave.
- **Обновления** — установленная версия, последний выпуск на GitHub, команда обновления.
- **Развёртывания** — журнал поэтапного выпуска: версия, доля трафика, ошибки, продвижение и откат.

## Где и кто

| Раздел | Что делает | Права |
| --- | --- | --- |
| **Система → Диагностика** | Общий статус и проверки PostgreSQL, Redis, Remnawave; «Проверить снова»; блок «Готовность production» | `ops.diagnostics` (оператор, администратор) |
| **Система → Обновления** | Текущая версия, релиз GitHub, «Обновление доступно» или «Актуальная версия», команда на сервере, история | `ops.releases` |
| **Система → Развёртывания** | Записи поэтапного выпуска | `ops.releases` |

Панель только показывает статус. Само обновление выполняется командой на сервере: она сверяет SHA-256 архива, сохраняет `.env` и запускает `scripts/update.sh` со снимком для отката.

## Версии

| Что | Где смотреть |
| --- | --- |
| Тег дистрибутива (например `v28.26.0`) | Выпуски GitHub, **Обновления** |
| Версия runtime/API (`21.5.1`) | **Все разделы**, `/health/ready`, `docker compose exec -T backend python -c 'from app.main import APP_VERSION; print(APP_VERSION)'` |
| Миграции магазина | `docker compose exec -T backend alembic current` |
| Миграции Support Pro | `docker compose exec -T support_db psql -U support -d support -Atc 'SELECT version_num FROM alembic_version'` |

Тег дистрибутива и версия API — разные числа. Тег растёт с каждым выпуском, версия API — только при изменении контракта API.

## Обновление

1. Прочитайте заметки выпуска (`docs/ru/RELEASE_V…`): какие миграции, что проверить после обновления.
2. Сделайте согласованную копию: `cd /opt/vpn-shop && bash scripts/backup.sh` ([модуль 30](30-backups-recovery.md)). Скопируйте архив с сервера.
3. Обновите:

```bash
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.26.0 bash /opt/vpn-shop/scripts/update-from-github.sh
```

Без `RELEASE_TAG` берётся последний стабильный выпуск. Если сервер ставился до появления `update-from-github.sh`, используйте первый способ из [регламента обновления](../DISTRIBUTION_UPGRADE_CURRENT.md).

4. Проверьте:

```bash
cd /opt/vpn-shop
docker compose ps
bash scripts/doctor.sh
docker compose exec -T backend alembic current
docker compose logs --tail=100 backend worker bot
```

**PostgreSQL 18 (с v28.23.0).** При первом обновлении на v28.23.0 и новее `update.sh` запускает `scripts/upgrade-postgres.sh`: останавливает сервисы, поднимает старую базу PostgreSQL 16 во временном контейнере без сети, снимает дамп `pg_dump -Fc` (копия — в `.rollback/postgres16-*.dump`), восстанавливает его в PostgreSQL 18 на новом томе (`postgres18_data`, `support_postgres18_data`), сверяет число строк в каждой таблице и делает `ANALYZE`. Закреплённый образ `POSTGRES_IMAGE=postgres:16…` в `.env` и `.env.images` заменяется на PostgreSQL 18. Старые тома `postgres_data` и `support_postgres_data` не удаляются: удалите их вручную (`docker volume rm …`), когда убедитесь, что всё работает. Повторный запуск ничего не делает. Если в новой базе уже есть данные, скрипт остановится; заменить их данными PostgreSQL 16 можно с `PG_UPGRADE_FORCE=1`. Отдельный Support Pro: `PG_UPGRADE_SPEC="db:pgdata:pgdata18:<POSTGRES_USER>:<POSTGRES_DB>" bash scripts/upgrade-postgres.sh`.

Скрипт обновления сам откатывает файлы и основную базу при ошибке. Базу Support Pro он не откатывает, поэтому копия из шага 2 обязательна.

## Обновления зависимостей (Dependabot)

Раз в неделю (по понедельникам) Dependabot открывает PR с обновлениями: Python-пакеты магазина (`backend/requirements.txt`) и Support Pro (`support-pro/requirements.txt`), npm-пакеты админки и кабинета, базовый образ backend и GitHub Actions. Минорные и патч-обновления приходят одним PR на проект, мажорные — отдельными.

Каждый PR проходит полный CI: тесты магазина и Support Pro, сборки, e2e в Chromium и аудит уязвимостей. Мержить можно только зелёный PR; мажорные обновления дополнительно читайте в заметках пакета.

Правила проекта:

- **Support Pro — один список версий** `support-pro/requirements.txt`: его ставят и тесты, и образ (контекст сборки — `support-pro`). Вторая копия `support-pro/app/requirements.txt` удалена, чтобы версии не расходились (`tests/test_dependency_locks.py`).
- **SQLAlchemy 2.1+ ставится как `sqlalchemy[asyncio]`**: иначе не установится `greenlet` и асинхронный движок не запустится.
- **`@types/node` — только мажорная версия рантайма** (образы и CI на Node 22); мажорные обновления типов Dependabot не предлагает.
- **`pydantic` в Support Pro — ниже 2.14**, пока `aiogram` не поддержит новее.

Ограничения записаны в `.github/dependabot.yml` с комментариями; снимайте их, когда причина ушла.

## Диагностика

**Диагностика** → «Проверить снова». Проверяются подключения к PostgreSQL и Redis (с задержкой) и доступность Remnawave. Блок «Готовность production» напоминает, что реальные платежи открываются только после staging E2E: диагностика production gate не снимает.

С сервера `bash scripts/doctor.sh` проверяет:

- конфигурацию Compose и состояние контейнеров;
- `health/ready` API;
- ответы admin, miniapp и cabinet.

Полная картина зависимостей — в **Состоянии системы** ([модуль 02](02-health-incidents-monitoring.md)).

## Развёртывания

Магазин работает одним набором контейнеров, поэтому «Развёртывания» — журнал решений, а не балансировщик трафика. Запишите версию, стратегию и долю, затем продвигайте (поднять долю нельзя при ошибках от 5%) или откатывайте с причиной. Удобно, если вы выпускаете версии через собственный балансировщик или несколько серверов.

## Проблемы

| Симптом | Причина | Что делать |
| --- | --- | --- |
| «GitHub не ответил» | Нет доступа к GitHub с сервера | Проверьте сеть; обновление можно выполнить с другим `RELEASE_TAG` позже |
| Обновление прервалось | Ошибка сборки или миграции | Скрипт откатил файлы и основную базу; смотрите вывод и `docker compose logs` |
| После обновления 502 | Контейнеры ещё запускаются | `docker compose ps`, подождите healthcheck |
| Миграция не на ожидаемом head | Обновление не завершилось | Повторите обновление; не правьте `alembic_version` руками |

## API

`GET /api/admin/v41/diagnostics`, `GET /api/admin/releases`, `POST /api/admin/releases/check`, `GET /api/admin/github-update`, `/api/admin/deployments`.

## Подробнее

[Обновление дистрибутива](../DISTRIBUTION_UPGRADE_CURRENT.md) · [Миграции и согласованный откат](../WORKSPACE_UPGRADE.md) · [Регламент эксплуатации](../PRODUCTION_CURRENT.md).
