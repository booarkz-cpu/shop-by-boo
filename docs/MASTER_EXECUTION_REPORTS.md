# Отчёт о выполнении — VPN Shop by Corgi Lucy

Дистрибутив `v28.56.0`, runtime/API `21.5.1`, миграция `0088_filter_and_regions`.

Каждый отчёт содержит: исходное состояние, первопричину, изменённые файлы, фактическую проверку и остаточные
ограничения. Реестр статусов — [MASTER_EXECUTION_PROGRESS.md](MASTER_EXECUTION_PROGRESS.md).

---

## TASK REPORT · AUD-01 / BE-01 / AUD-11

**Название:** затенённый `GET /api/me/traffic`.
**Исходный раздел:** 7, 8.

### 1. Исходное состояние

Путь `GET /api/me/traffic` был объявлен дважды:

* `backend/app/operations_api.py` — счётчики `traffic_used_bytes`, `traffic_limit_bytes`, `devices`;
* `backend/app/panel_usage.py` — разбивка по дням `days`, `nodes`, `total_bytes` для «Моей статистики».

Starlette обслуживает первый совпавший маршрут.

### 2. Обнаруженные проблемы

* Кабинет, Mini App и мобильные приложения получали ответ **без** `days` и `nodes`.
  `cabinet/src/keys.tsx` читает `data.days.length` → падение
  `Cannot read properties of undefined (reading 'length')`, блок статистики исчезал.
* Маршрут `GET /api/admin/users/{user_id}/traffic` из `panel_usage.py` не попадал в таблицу маршрутов —
  кнопка «Трафик» в карточке клиента админки не работала.
* Первопричина одна: два модуля объявили один путь с несовместимыми контрактами, дубликат никто не ловил.

Доказательство (`tests/app_contract.py`, порядок разрешения):

```
0: app.panel_usage   <- зарегистрирован первым
1: app.operations_api
```

### 3. Выполненные действия

* `panel_usage.my_traffic` отвечает **обоими** контрактами: счётчики из подписки и панели плюс разбивка по дням.
* Счётчики вынесены в `_subscription_traffic()`; при отсутствии подписки, `remnawave_uuid` или недоступной
  панели возвращается `available: false` с предельным лимитом из снимка плана — ошибка не маскируется пустым
  массивом.
* Если у панели нет `bandwidth-stats`, разбивка формируется из `shape({})`: `days` — пустой **список**.
* Дубликат удалён из `operations_api.py`, имя убрано из `__all__`.

### 4. Изменённые файлы

* `backend/app/panel_usage.py` — объединённый обработчик и `_subscription_traffic`.
* `backend/app/operations_api.py` — удалён дубликат маршрута и запись в `__all__`.
* `tests/test_v34_hardening.py` — тест переписан на проверку поведения.

### 5. Тесты

```
python -m pytest tests/test_v34_hardening.py tests/test_subscription_middleware.py \
                 tests/test_v32_operations.py tests/test_freekassa.py -q
→ 417 passed, 13 skipped
```

Добавлены: `test_no_path_answers_twice`, `test_me_traffic_answers_both_contracts`,
`test_me_traffic_still_answers_when_the_panel_has_no_statistics`.

### 6. Критерии приёмки

| Критерий | Результат |
| --- | --- |
| Путь объявлен один раз | PASS — `shadowed: 0` из 836 маршрутов |
| Кабинет получает `days` и `nodes` | PASS |
| Мобильные клиенты получают `traffic_used_bytes` | PASS |
| Нет статистики панели → пустой список, не `undefined` | PASS |
| Кнопка «Трафик» видит маршрут | PASS |

### 7. Ограничения

Живой ответ Remnawave не проверен — нет `REMNAWAVE_TOKEN` (B-01).

### 8. Статус: **PASS**

---

## TASK REPORT · AUD-06 / FE-06

**Название:** чёрные страницы панели и кабинета.
**Исходный раздел:** 7, 12, 15.

### 1. Исходное состояние

`admin/src/app/page.tsx` и `cabinet/src/app/page.tsx` монтируют корень с `ssr: false`. Файлов
`error.tsx` / `global-error.tsx` не было ни в одном приложении. В кабинете `SectionBoundary` защищал только
контент раздела, корневые провайдеры — ничем.

### 2. Обнаруженные проблемы

Исключение в `LangProvider`, `AppConfigProvider` или `App` размонтировало всё дерево React: посетитель видел
пустой документ без текста, без причины и без выхода. Это в точности механизм исторического симптома
«чёрная страница».

### 3. Выполненные действия

* `admin/src/app/error.tsx`, `cabinet/src/app/error.tsx` — экран ошибки Next.js: причина, «Попробовать снова»
  (`reset`, сессия сохраняется), «Перезагрузить».
* `CabinetRootBoundary` в `cabinet/src/main.tsx` и `AdminErrorBoundary`, навешенный на корень
  `admin/src/main.tsx`, — ловят сбой **выше** страницы, в самих провайдерах.
* Текст экрана прямо говорит, что подписка и платежи не затронуты: сбой отрисовки не должен выглядеть как
  потеря доступа.

### 4. Изменённые файлы

`admin/src/app/error.tsx` (новый), `cabinet/src/app/error.tsx` (новый), `admin/src/main.tsx`,
`cabinet/src/main.tsx`, `tests/test_v34_hardening.py`.

### 5. Тесты

```
cd admin   && ./node_modules/.bin/tsc --noEmit && ./node_modules/.bin/tsc --noEmit -p tsconfig.ui.json  → 0
cd cabinet && ./node_modules/.bin/tsc --noEmit                                                          → 0
cd admin   && ./node_modules/.bin/next build                                                            → ok
cd cabinet && ./node_modules/.bin/next build                                                            → ok
grep "Кабинет не открылся" cabinet/dist → чанки 2ute4361j5zb2.js, 43nc-uziquipr.js
grep "Панель не открылась" admin/dist   → чанк 0pfendy-vyusc.js
```

Добавлен `test_both_frontends_render_an_error_screen_instead_of_a_black_page`.

### 6. Критерии приёмки

| Критерий | Результат |
| --- | --- |
| `app/error.tsx` в обоих приложениях | PASS |
| Корень обёрнут в boundary | PASS |
| Экран попал в собранный артефакт | PASS |
| Typecheck и build | PASS |

### 7. Ограничения

Визуальная проверка в браузере не выполнялась: Playwright в песочнице не запускался (Chromium не установлен).

### 8. Статус: **PASS**

---

## TASK REPORT · BE-02

**Название:** уникальные `operationId` OpenAPI.
**Исходный раздел:** 8.

### 1. Исходное состояние

`/api/webhooks/freekassa` обслуживался одним `api_route` с `methods=["GET","POST"]`.

### 2. Обнаруженные проблемы

FastAPI выводит `operationId` из имени функции, поэтому оба метода получали
`freekassa_webhook_api_webhooks_freekassa_post`, и второй перезаписывал первый в схеме. Предупреждение
`Duplicate Operation ID` печаталось на каждом построении `openapi()`. Сгенерированные клиенты получили бы
задвоенную операцию.

### 3. Выполненные действия

Методы разведены на отдельные маршруты `freekassa_webhook_get` и `freekassa_webhook_post`. Логика подписи,
сверки суммы и подтверждения через API v1 не тронута.

### 4. Изменённые файлы

`backend/app/payments_api.py`, `tests/test_v34_hardening.py`.

### 5. Тесты

```
python -m pytest tests/test_freekassa.py tests/test_v34_hardening.py -q  → passed
Предупреждений «Duplicate Operation ID»: 0 (было 1)
ids: {'get': 'freekassa_webhook_get', 'post': 'freekassa_webhook_post'}
```

### 6. Критерии приёмки

| Критерий | Результат |
| --- | --- |
| Предупреждений о дубле нет | PASS |
| Все `operationId` уникальны | PASS — `test_openapi_operation_ids_are_unique` |
| Повторное уведомление отвечает `YES` и не выдаёт подписку дважды | PASS — `test_freekassa.py` |

### 7. Ограничения

Реальный webhook Freekassa не вызывался — нет ключей (B-03).

### 8. Статус: **PASS**

---

## TASK REPORT · INV-01 / INV-02 / INV-03

**Название:** инвентаризация и совместимость 7 репозиториев.
**Исходный раздел:** 6.

### Результат

| Репозиторий | Назначение | Лицензия | Отношение к проекту |
| --- | --- | --- | --- |
| `booarkz-cpu/shop-by-boo` | магазин: API, бот, панель, кабинет, Mini App, мобильные | NOASSERTION (свой) | основной, права admin |
| `booarkz-cpu/remnawave-manager` | shell-менеджер установки Remnawave | MIT | права admin; код не переносился |
| `eGamesAPI/remnawave-reverse-proxy` | reverse proxy для Remnawave | MIT | только чтение; архитектура сверена |
| `Case211/remnawave-admin` | альтернативный админ-бот | NOASSERTION | только чтение; пересечение по панели |
| `BEDOLAGA-DEV/remnawave-bedolaga-telegram-bot` | бот-магазин подписок | Commons Clause | **несовместима** с переносом кода |
| `BEDOLAGA-DEV/bedolaga-cabinet` | веб-кабинет | AGPL-3.0 | **несовместима** с закрытым распространением |
| `STEP-CORP/StepBot` | конструктор ботов | MIT | только чтение |

Пересечения по функциям: продажа подписок, выдача конфигурации, панель администратора, уведомления.
**Ни одна строка стороннего кода не переносилась**: две лицензии не допускают этого для проекта, остальные —
не требуют, потому что соответствующая функциональность уже реализована в `shop-by-boo` и покрыта тестами.

### Статус: **PASS**

---

## TASK REPORT · AUD-04 / AUD-05

**Название:** исторические симптомы `reading 'trim'` и `map is not a function`.

### Проверено

* `reading 'trim'`: единственные места, где `.trim()` вызывается на значении метки, — обработчики
  `admin/src/mobileLayout.tsx` (строки 183, 211), читающие `v.ru`/`v.en`/`v.uk`. Backend отдаёт
  `texts` как `dict[str, Label]` с полями `ru`/`en`/`uk` (`backend/app/mobile_layout.py`, классы
  `Label`, `LongText`) и `strings` как `dict[str, LongText]`. Форма совпадает, воспроизвести падение на
  текущем коде нельзя.
* `map is not a function`: нормализация `list()` уже есть в `admin/src/main.tsx` и обрабатывает `items`,
  `results`, `data`. В кабинете списки читаются через `?.`/`|| []`.

### Решение

Спекулятивная правка не делалась: менять код под невоспроизводимый симптом значило бы маскировать ошибку.
Форма ответа закреплена тестом `test_me_traffic_answers_both_contracts`, который проверяет типы полей.

### Статус: **NOT_APPLICABLE** (не воспроизводится на текущем коде)

---

## TASK REPORT · REL-01

**Название:** выпуск `v28.56.0`.

### Выполнено

* Версия синхронизирована в 63 файлах (`v28.55.0` → `v28.56.0`, артефакт
  `remnawave_vpn_shop_v28_56_0_full_release.zip`). Исторические записи не тронуты: `CHANGELOG.md`
  получил новую секцию сверху, `docs/AUTOMATION_LOG.md` и `docs/ru/RELEASE_V28_55_0.md` сохранены как есть.
* `backend/app/release_identity.py`: `DISTRIBUTION_TAG = "v28.56.0"`, `RUNTIME_VERSION = "21.5.1"`.
* `release-manifest.template.json`: тег, заголовок, release notes, имена артефактов. Флаги
  `production_ready`, `full_function_transfer`, `production_e2e_verified`, `signed` оставлены `false` —
  это честное состояние, а не готовность к production.
* Новый отчёт выпуска `docs/ru/RELEASE_V28_56_0.md`; контракт `scripts/check-current-docs.py` переведён на него.
* `scripts/generate-project-map.py` перегенерировал карту файлов.

### Проверки

```
python scripts/check-current-docs.py           → OK: distribution v28.56.0, runtime v21.5.1
python scripts/check-runtime-placeholders.py   → OK
python scripts/generate-project-map.py --check → OK
python -m alembic heads                        → 0088_filter_and_regions (head)
```

### Статус: **IMPLEMENTED** (публикация — B-07)

---

## REP-07. CI-перезапуск отменял прогон нового коммита и блокировал публикацию релиза

**ID:** GHA-03 · **Исходный раздел:** 31, 40 · **Дата:** 2026-10-31

### Исходное состояние

Версия `v28.56.0` была синхронизирована по 63 файлам, документация и тесты проходили локально,
коммит `a8f22a7` ушёл в `main`. GitHub показывал по нему «Publish GitHub release — completed / success»,
но релиза `v28.56.0` не появлялось: тега нет, страница релизов заканчивалась на `v28.55.0`.

### Обнаруженная проблема

В прогоне публикации шаги «Package deterministic distribution» и «Publish verified files» были
**skipped**, то есть gate не выдал `ready=true`, а сам workflow отчитался успехом — красного прогона
в истории не было.

Цепочка причин:

1. `ci.yml` и `docker.yml` имели `concurrency.group: ci-${github.ref}` / `docker-${github.ref}`.
2. В 21:57 был перезапущен CI на **старом** коммите `81c0a51` (attempt 2).
3. В 22:00 стартовал CI **нового** коммита `a8f22a7`; обе группы совпали, и
   `cancel-in-progress: true` отменил новый прогон в 22:00:15.
4. Прогон `a8f22a7` получил `conclusion: cancelled`, а не `success`.
5. Gate в `publish-release.yml` требует success и для `ci.yml`, и для `docker.yml` на том же SHA,
   поэтому вернул `ready=false`.

Первый коммит `a8f22a7` при этом **прошёл** шаг контракта документации — предыдущее падение на
«Project map is stale» относилось к `81c0a51` и уже было исправлено этим коммитом.

### Реализованное исправление

* `.github/workflows/ci.yml` — группа `ci-${{ github.ref }}-${{ github.sha }}`;
* `.github/workflows/docker.yml` — группа `docker-${{ github.ref }}-${{ github.sha }}`.

Повторный запуск того же коммита по-прежнему вытесняет предыдущий (сохранено `cancel-in-progress: true`),
но прогон другого коммита больше ничего не отменяет.

### Тестирование

| Проверка | Команда | Результат |
| --- | --- | --- |
| Новый тест правила | `pytest tests/test_production_installer_v2016.py` | 6 passed |
| Lint | `ruff check backend scripts tests` | All checks passed |
| Контракт документации | `python scripts/check-current-docs.py` | OK, v28.56.0 |
| Карта проекта | `python scripts/generate-project-map.py --check` | project file map OK |
| Node-инварианты | `node --test tests/release-publisher.test.cjs tests/dependabot-automerge.test.cjs` | 9 pass, 0 fail |
| Alembic | `alembic heads` | один head `0088_filter_and_regions` |

### Изменённые файлы

* `.github/workflows/ci.yml` — группа concurrency;
* `.github/workflows/docker.yml` — группа concurrency;
* `tests/test_production_installer_v2016.py` — `test_ci_concurrency_is_scoped_to_one_commit`.

### Git

Коммит `3eb9fbf` в `main`, отправлен в `booarkz-cpu/shop-by-boo`.

### Ограничения

Публикация тега становится возможной только после зелёных `ci.yml` **и** `docker.yml` на `3eb9fbf`;
полный прогон CI занимает около 30 минут, поэтому статус на момент отчёта — `IN_PROGRESS`.
