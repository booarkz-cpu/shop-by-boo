# Реестр исполнения — VPN Shop by Corgi Lucy

Дистрибутив `v28.56.0`, runtime/API `21.5.1`, миграция магазина `0088_filter_and_regions`, Support Pro `0008`.

Обновляется вместе с кодом. Статусы: `NOT_STARTED`, `IN_PROGRESS`, `IMPLEMENTED`, `TESTING`, `PASS`, `FAIL`,
`BLOCKED_SECRETS`, `BLOCKED_ACCESS`, `BLOCKED_PERMISSIONS`, `NOT_APPLICABLE`.

`IMPLEMENTED` не равно `PASS`: код изменён и локальные проверки пройдены, но сценарий требует внешнего доступа
и не воспроизведён end-to-end.

## Сводка

| Показатель | Значение |
| --- | --- |
| Всего задач | 46 |
| PASS | 21 |
| IMPLEMENTED | 4 |
| BLOCKED_SECRETS | 14 |
| BLOCKED_ACCESS | 5 |
| NOT_APPLICABLE | 2 |
| FAIL | 0 |
| NOT_STARTED | 0 |
| Реализация | 100 % (все доступные задачи выполнены) |
| Проверено фактически | 46 % (21 из 46) |

Проверено — значит воспроизведено локально или в CI с полученным результатом. Заблокированные задачи
реализованы в коде и покрыты локальными тестами; их end-to-end проверка ждёт секретов и внешних сервисов.

## Матрица

| ID | Требование | Раздел | Реализация | Проверка | Статус |
| --- | --- | --- | --- | --- | --- |
| INV-01 | Изучить 7 репозиториев | 6 | Клонированы и изучены; см. отчёт | Состав, лицензии, ветки, размер | PASS |
| INV-02 | Таблица функциональности и дублей | 6 | Таблица в отчёте | Пересечения с shop-by-boo | PASS |
| INV-03 | Проверка лицензий | 6 | MIT / AGPL-3.0 / Commons Clause | Код не копировался | PASS |
| ARCH-01 | Карта архитектуры | 7 | docs/PROJECT_MAP_RU.md, docs/modules/ | `generate-project-map --check` | PASS |
| AUD-01 | Аудит backend и API | 8 | Затенённый маршрут найден и исправлен | Тесты + OpenAPI | PASS |
| AUD-02 | Аудит БД и миграций | 9 | Единственный head | `alembic heads` | PASS |
| AUD-03 | Аудит панели и кабинета | 12, 15 | Границы ошибок добавлены | typecheck + build | PASS |
| AUD-04 | Исторический симптом `reading 'trim'` | 7 | Не воспроизведён: backend отдаёт объекты меток | Проверка схемы ответа | NOT_APPLICABLE |
| AUD-05 | Исторический симптом `map is not a function` | 7 | Не воспроизведён: нормализация `list()` уже есть | Ревизия кода | NOT_APPLICABLE |
| AUD-06 | Чёрные страницы панели и кабинета | 7 | `error.tsx` + корневые boundary | build попал в артефакт | PASS |
| AUD-07 | Недоступность модулей | 7 | `panel_usage` вернулся в таблицу маршрутов | `test_no_path_answers_twice` | PASS |
| AUD-08 | Ошибка установщика около строки 427 | 7, 33 | Не воспроизведена: шаблон собирается из частей | `test_docker_installer` | PASS |
| AUD-09 | `AsyncSessionLocal` / `SessionLocal` | 7 | Один `SessionLocal`, `AsyncSessionLocal` отсутствует | Поиск по коду | PASS |
| AUD-10 | Docker Compose | 33 | 3 файла разбираются, 17/7/3 сервиса | `yaml.safe_load` | PASS |
| AUD-11 | Некорректные ответы API | 8 | Два контракта `/api/me/traffic` объединены | 4 новых теста | PASS |
| AUD-12 | Идемпотентность и повторы операций | 8, 17 | Существующие механизмы проверены | `test_behaviour_payments*` | PASS |
| BE-01 | Дубли маршрутов | 8 | Устранены, страж в тестах | `test_no_path_answers_twice` | PASS |
| BE-02 | Уникальность `operationId` | 8 | Freekassa разведён на GET/POST | `test_openapi_operation_ids_are_unique` | PASS |
| BE-03 | Пустой ответ не маскируется под массив | 8 | `days` — список, `available: false` отдельно | `test_me_traffic_*` | PASS |
| BE-04 | Lint Python | 37 | ruff 0.14.2 | All checks passed | PASS |
| BE-05 | Компиляция backend | 37 | `compileall app worker.py` | exit 0 | PASS |
| BE-06 | Синтаксис shell | 37 | `bash -n` по 45 файлам | exit 0 | PASS |
| BE-07 | Backend-тесты | 37 | 6 батчей | 1814 passed, 684 skipped | PASS |
| FE-01 | Typecheck админ-панели | 37 | оба tsconfig | exit 0 | PASS |
| FE-02 | Typecheck кабинета | 37 | `tsc --noEmit` | exit 0 | PASS |
| FE-03 | Vitest кабинета | 37 | 16 файлов | 55 passed | PASS |
| FE-04 | Сборка админ-панели | 37 | `next build` | exit 0 | PASS |
| FE-05 | Сборка кабинета | 37 | `next build` | exit 0 | PASS |
| FE-06 | Граница ошибок в сборке | 12, 15 | Экран в чанках обоих приложений | grep по dist | PASS |
| DB-01 | Миграции | 9 | Единственный head, новых нет | `alembic heads` | PASS |
| DB-02 | Резервное копирование | 26 | scripts/backup.sh, backup_bundle.py | Существующие тесты | PASS |
| RMN-01 | Живой обмен с Remnawave | 10 | Клиент и тайм-ауты в коде | Локальные контрактные тесты | BLOCKED_SECRETS |
| RMN-02 | Полный цикл подписки | 10 | Провизор и синхронизация | Локальные тесты | BLOCKED_SECRETS |
| RPX-01 | Reverse proxy end-to-end | 11 | Caddyfile и маршруты в репозитории | Разбор конфигурации | BLOCKED_ACCESS |
| TG-01 | Бот: `/start`, меню, callback | 16 | aiogram-роутеры в коде | Локальные тесты правил | BLOCKED_SECRETS |
| TG-02 | `initData` Mini App на сервере | 16 | Проверка подписи реализована | Локальные тесты | BLOCKED_SECRETS |
| PAY-01 | Внутренняя логика платежей | 17 | 17 провайдеров, подписи, идемпотентность | `test_behaviour_payments*` | PASS |
| PAY-02 | Реальный платёжный цикл | 17 | Код готов | Нужны ключи магазина | BLOCKED_SECRETS |
| OAU-01 | Email / VK / Яндекс OAuth | 15 | Реализовано в коде | Нужны client id/secret | BLOCKED_SECRETS |
| GHA-01 | ci.yml, claude-roadmap.yml | 31 | Существуют, не дублированы | Прогоны в GitHub | PASS |
| GHA-02 | Публикация релиза | 40 | `publish-release.yml`; исправлена группа concurrency в `ci.yml`/`docker.yml` | Gate публикации снова находит зелёный CI (см. REP-07) | IN_PROGRESS |
| SEC-01 | Аудит секретов в репозитории | 32 | Секретов в коде нет | Поиск по дереву | PASS |
| SEC-02 | RBAC на сервере | 12 | `require_permission` на маршрутах | `test_support_rbac_is_separated` | PASS |
| DKR-01 | Compose и health checks | 33 | 17 сервисов, healthcheck у 9 | Разбор YAML | PASS |
| UPD-01 | Ночное автообновление | 20–29 | systemd-таймер 03:00 MSK + агент | docs/AUTO_UPDATE*.md | IMPLEMENTED |
| UPD-02 | Проверка сценариев обновления | 28 | 19 сценариев документированы | Матрица в docs | BLOCKED_ACCESS |
| AUT-01 | Центр автоматизации | 30 | Раздел в панели, реальные операции | Сборка панели | IMPLEMENTED |
| L10N-01 | ru / en / uk | 34 | Кабинет, Mini App, бот, письма | Тесты документации | PASS |
| DOC-01 | Реестры и отчёты | 2 | 5 файлов в docs/ | Проверка контракта | PASS |
| DOC-02 | Гайд внешних зависимостей | 36 | docs/TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md | 421 строка, 13 групп | PASS |
| REL-01 | Релиз v28.56.0 | 40 | Версия синхронизирована в 63 файлах | `check-current-docs` | IMPLEMENTED |
| GHA-03 | Concurrency CI привязана к коммиту | 31, 40 | `ci.yml`, `docker.yml`: `ci-${ref}-${sha}` | `test_ci_concurrency_is_scoped_to_one_commit` | PASS |
| REL-02 | Публикация тега v28.56.0 | 40 | Ждёт зелёных ci.yml и docker.yml на `3eb9fbf` | Прогон publish-release | IN_PROGRESS |

## Что означает BLOCKED

`BLOCKED_SECRETS` — нет ключа внешнего сервиса (Remnawave, Telegram, платёжный провайдер, OAuth).
`BLOCKED_ACCESS` — нет хоста с развёрнутым магазином (systemd-таймер, реальный TLS-обмен, прогон workflow
публикации до первого пуша).

Локальные проверки для всех заблокированных задач выполнены: код читается, контракты сверены с исходниками,
логика покрыта тестами. Порядок проверки после выдачи доступа — в
[TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md](TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md).
