# Автообновление из GitHub

Дистрибутив `v28.56.0`, runtime/API `21.5.1`, миграция магазина `0088_filter_and_regions`.

Документ описывает **фактически реализованный** механизм. Всё, что здесь написано, проверено по
исходному коду `scripts/auto_update.py`, `scripts/github_release_fetch.py`,
`backend/app/auto_update_api.py`, `admin/src/autoUpdate.tsx`. То, что нельзя проверить без VPS,
помечено явно.

Подробности цикла и откат: [modules/auto_update_and_rollback.md](modules/auto_update_and_rollback.md).
Требования безопасности: [AUTO_UPDATE_SECURITY.md](AUTO_UPDATE_SECURITY.md).
Диагностика: [AUTO_UPDATE_TROUBLESHOOTING.md](AUTO_UPDATE_TROUBLESHOOTING.md).
Матрица проверок: [AUTO_UPDATE_TESTING.md](AUTO_UPDATE_TESTING.md).

## 1. Выбранная архитектура

Отдельного сервера-планировщика нет. Планировщик — это **systemd на том же хосте**, где уже
работает магазин. Второй компонент — API, который только пишет файл-запрос и читает файл-состояние.

Причина выбора: приложение уже развёрнуто на VPS через Docker Compose под systemd/root, а
GitHub Actions не имеет доступа к файловой системе хоста и не может выполнить `docker compose`
на сервере без отдельного SSH-секрета и SSRF-риска. Поэтому ночное обновление выполняет хост,
а GitHub служит только источником проверенных релизов.

| Где | Что | Файл |
| --- | --- | --- |
| Хост (root, systemd) | Ночной таймер `vpn-shop-update` и агент `vpn-shop-update-agent` | `scripts/auto_update.py`, `scripts/auto-update.sh` |
| Хост | Загрузка и проверка релиза (SHA-256, манифест, commit) | `scripts/github_release_fetch.py` |
| Хост | Снимок, замена файлов, сборка, миграции, health, откат | `scripts/update.sh`, `scripts/rollback.sh` |
| backend | Экран «Обновления» и запрос «Обновить сейчас» | `backend/app/auto_update_api.py` |
| admin | UI «Автообновление с GitHub» | `admin/src/autoUpdate.tsx` |

```
admin (браузер)
   │  PUT /api/admin/auto-update        {enabled, time}
   │  POST /api/admin/auto-update/run   →
   ▼
backend  ── пишет ──▶  $APP_DIR/.control/auto-update.request.json
                              │
                        (раз в минуту)
                              ▼
                       vpn-shop-update-agent
                              │ применяет настройки, выполняет check_now
                              ▼
                    scripts/update-from-github.sh
                              │ SHA-256 + манифест + tag_commit
                              ▼
                       scripts/update.sh
                          снимок + дамп БД → build → migrate → health
                              │ при сбое
                              ▼
                       scripts/rollback.sh
                              │
backend  ◀── читает ──  $APP_DIR/.control/auto-update.status.json
```

## 2. Каналы связи между панелью и агентом

Ровно два JSON-файла, никакого RPC. Панель физически не может выполнить на сервере ничего, кроме
записи трёх полей.

### `auto-update.request.json` — пишет панель, читает агент

```json
{
  "enabled": true,
  "time": "03:00",
  "check_now": "20261031T120000.000000Z",
  "updated_by": "admin@example.com",
  "updated_at": "2026-10-31T12:00:00+00:00"
}
```

Агент принимает из этого файла **только три** поля — `enabled`, `time`, `check_now` — и проверяет
их формат: `time` по `^([01]\d|2[0-3]):[0-5]\d$`, `check_now` по `^[A-Za-z0-9:._-]{1,64}$`.
Все остальные ключи игнорируются.

### `auto-update.status.json` — пишет агент, читает панель

Ключи: `enabled`, `time`, `installed`, `latest`, `running`, `started_at`, `last_run_at`,
`last_result`, `last_message`, `next_run`, `trigger`, `recovery_mode`, `failed_release`,
`log_tail`, `agent_seen_at`, `handled_check_now`.

`last_result` принимает значения `updated`, `current`, `skipped`, `failed`.

## 3. Расписание

| Юнит | Расписание | Назначение |
| --- | --- | --- |
| `vpn-shop-update.timer` | `OnCalendar=*-*-* HH:MM:00 Europe/Moscow`, `RandomizedDelaySec=900`, `Persistent=true` | Ночная проверка релизов |
| `vpn-shop-update-agent.timer` | `OnBootSec=1min`, `OnUnitInactiveSec=1min`, `AccuracySec=10s` | Применение настроек из панели, выполнение `check_now` |

По умолчанию `{"enabled": true, "time": "03:00"}` (`DEFAULT` в `scripts/auto_update.py`).

Важные следствия, которые нужно понимать оператору:

- `RandomizedDelaySec=900` — таймер сработает **не ровно в 03:00**, а в случайный момент в течение
  15 минут после. Это защита от одновременного обновления парка серверов.
- `Persistent=true` — если сервер был выключен в 03:00, обновление выполнится при следующей загрузке.
- Часовой пояс фиксирован — `Europe/Moscow`, независимо от TZ хоста.
- `next_run` в панели берётся из `systemctl show ... NextElapseUSecRealtime`. Если systemd недоступен,
  поле будет пустым — это не ошибка.

## 4. Источник обновлений

Единственный источник — **стабильные GitHub Releases** репозитория `booarkz-cpu/shop-by-boo`
(`GITHUB_REPO` в `backend/app/github_update.py`). Обновление из ветки `main` не поддерживается
этим механизмом: канала «main» в коде нет, и включать его настройкой нельзя.

`release_status()` в `backend/app/github_update.py` считает релиз пригодным, только если:

1. тег строго соответствует `^v\d+\.\d+\.\d+$`;
2. `draft == false` и `prerelease == false`;
3. в релизе есть ассеты `remnawave_vpn_shop_v<X_Y_Z>_full_release.zip` и тот же файл + `.sha256`;
4. при обновлении с другой версии дополнительно требуется `<zip>_manifest.json`;
5. `browser_download_url` каждого ассета совпадает с ожидаемым префиксом
   `https://github.com/<repo>/releases/download/<tag>/<name>`;
6. `version_tuple(latest) > version_tuple(current)`.

`scripts/github_release_fetch.py` проверяет дополнительно: SHA-256 скачанного архива, поля
манифеста (`distribution_tag`, `version`, `artifact`, `sha256`) и `commit == tag_commit(tag)`.

Актуальный стабильный релиз на момент документа: `v28.56.0`, опубликован `2026-10-29T14:27:31Z`.

## 5. Процесс обновления

1. Проверка окружения: существует `.env` в `$APP_DIR`, иначе выход с кодом 2.
2. Запрос `releases/latest` к GitHub API (`scripts/github_release_fetch.py`).
3. Сравнение тегов; если версия не новее — результат `current`, установка не выполняется.
4. Скачивание архива и `.sha256`, сверка контрольной суммы.
5. Скачивание манифеста, сверка `sha256`, `version`, `artifact`, `commit`.
6. Распаковка во временный каталог (`mktemp -d`, очистка через `trap`).
7. `scripts/update.sh`: снимок текущего дерева в `.rollback/*.tar.gz` и дамп БД.
8. Замена файлов (`.env`, `.env.*`, `.git`, `.rollback`, `.control` исключены).
9. Сборка образов и запуск: `deploy/build-production.sh`, миграции Alembic.
10. Проверки здоровья: `/health`, `/health/live`, `/health/ready`.
11. Запись результата в `auto-update.status.json`.
12. При ошибке на любом шаге срабатывает `trap rollback ERR` → `scripts/rollback.sh`.

`rollback.sh` требует **и** архив файлов, **и** дамп БД (`.sql`); без дампа он отказывается
работать и не трогает установку. Перед откатом создаётся `pre-rollback-<STAMP>.tar.gz` и флаг
`RECOVERY_MODE`.

## 6. Интерфейс панели

Раздел админки: **Выпуски → Обновления** (вкладка `releases`, `admin/src/sections.ts`).
Внутри — карточка «Автообновление с GitHub» (`admin/src/autoUpdate.tsx`) и карточка «Релиз GitHub»
(`Releases` в `admin/src/main.tsx`).

Отображается: доступность агента, включённость, время, установленная и доступная версии,
состояние (`running`), время последнего запуска, `last_result` и `last_message`, `next_run`,
признак режима восстановления, `failed_release`, хвост журнала (`log_tail`, 40 строк).

Реальные действия в UI:

| Кнопка | Запрос | Право |
| --- | --- | --- |
| Сохранить расписание | `PUT /api/admin/auto-update` | `settings.runtime.write` |
| Проверить и обновить сейчас | `POST /api/admin/auto-update/run` | `settings.runtime.write` |
| Чтение состояния | `GET /api/admin/auto-update` | `ops.releases` |

`POST /run` возвращает `409`, если обновление уже идёт (`running`) или запрос уже отправлен
(`pending_run`) — защита от повторного запуска. Метка `check_now` генерируется сервером.

Если каталог `.control` не доступен на запись, API отвечает `503` и подсказывает команду установки
(`SETUP_HINT`). Панель не выдумывает статус: показывает `setup_hint`.

## 7. Установка на сервер

```bash
sudo bash /opt/vpn-shop/scripts/auto-update.sh install   # включить таймеры
sudo bash /opt/vpn-shop/scripts/auto-update.sh status    # версия, расписание, итог
sudo bash /opt/vpn-shop/scripts/auto-update.sh run       # проверить и обновить сейчас
sudo bash /opt/vpn-shop/scripts/auto-update.sh disable   # выключить (таймеры удаляются)
```

Установщик `deploy/install-vps.sh` вызывает `install` сам. На хостах без systemd (CI, непривилегированные
сборки) агент только создаёт каталог `.control` и не регистрирует таймеры — это ожидаемое поведение,
а не ошибка.

## 8. Пути и переменные окружения

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `APP_DIR` | `/opt/vpn-shop` | Корень установки |
| `AUTO_UPDATE_CONF_DIR` | `/etc/vpn-shop` | `auto-update.json`, `auto-update.failed`, `auto-update.handled` |
| `AUTO_UPDATE_SYSTEMD_DIR` | `/etc/systemd/system` | Куда пишутся юниты |
| `AUTO_UPDATE_CONTROL_DIR` | `$APP_DIR/.control` | Обмен с панелью; в контейнере — `/data/control` |

Файлы состояния:

- `/etc/vpn-shop/auto-update.json` — действующее расписание;
- `/etc/vpn-shop/auto-update.failed` — релиз, который не установился и ночью повторно не ставится;
- `/etc/vpn-shop/auto-update.handled` — обработанная метка `check_now`;
- `$APP_DIR/.control/auto-update.status.json` — состояние для панели;
- `$APP_DIR/.rollback/` — снимки (хранится `KEEP_SNAPSHOTS = 5`).

## 9. Статус реализации

| Компонент | Статус | Чем подтверждено |
| --- | --- | --- |
| Агент, таймеры, расписание | Реализовано | `scripts/auto_update.py`, тесты `tests/test_auto_update_agent.py` |
| Проверка релиза, SHA-256, манифест | Реализовано | `scripts/github_release_fetch.py`, `backend/app/github_update.py` |
| API панели, права, защита от повтора | Реализовано | `tests/test_auto_update_api.py` — проходит |
| UI «Автообновление» | Реализовано | `admin/src/autoUpdate.tsx`, typecheck и build проходят |
| Снимок и откат при сбое | Реализовано | `scripts/update.sh`, `scripts/rollback.sh` |
| Реальный ночной прогон на VPS | **Не проверено** | Нужен хост с systemd и root — `BLOCKED_ACCESS` |

Прежде чем считать автообновление проверенным на конкретной установке, пройдите
[AUTO_UPDATE_TESTING.md](AUTO_UPDATE_TESTING.md) на тестовом сервере.
