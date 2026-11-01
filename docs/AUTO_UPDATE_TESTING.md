# Автообновление: проверки

Дистрибутив `v28.57.0`, runtime/API `21.5.1`. Механизм: [AUTO_UPDATE.md](AUTO_UPDATE.md).

Документ фиксирует, что можно проверить **без production-сервера** (в репозитории и в CI) и что
требует хоста с systemd и root. Не отмечайте сценарий как пройденный, пока не получен результат.

## 1. Что покрыто автоматическими тестами

Оба файла проходят в песочнице на текущем коммите.

```bash
cd backend && MEDIA_DIR=/tmp/media APP_SECRET=ci-only-secret APP_ENV=test \
  python -m pytest -q ../tests/test_auto_update_api.py ../tests/test_auto_update_agent.py
```

| Файл | Что проверяет |
| --- | --- |
| `tests/test_auto_update_api.py` | Формат запроса, права, `409` при параллельном запуске, `pending_run`, `503` при недоступном каталоге, отсутствие живого агента |
| `tests/test_auto_update_agent.py` | Чтение и валидация запроса (только `enabled`/`time`/`check_now`), устойчивость к битому JSON, генерация юнитов, расписание, режим восстановления |

Дополнительно профильные проверки:

```bash
python -m pytest -q ../tests -k "auto_update or github_update or backup or release"
```

Результат в песочнице: `370 passed, 9 skipped`.

## 2. Статическая проверка в CI

| Шаг | Команда | Что ловит |
| --- | --- | --- |
| Lint | `ruff check backend scripts tests` | `F` (undefined name), `E9` (syntax), `B006`, `B023` |
| Shell-синтаксис | `bash -n` по всем `*.sh` | синтаксические ошибки в `auto-update.sh`, `update-from-github.sh` |
| Компиляция | `python -m compileall -q app worker.py` | синтаксис модулей |
| Контракт документации | `python3 scripts/check-current-docs.py` | расхождение версий в документах |
| Карта проекта | `python3 scripts/generate-project-map.py --check` | устаревшая `docs/PROJECT_FILE_MAP.md` |

## 3. Матрица сценариев

Статусы: `PASS` — проверено и прошло; `FAIL` — проверено и упало; `BLOCKED_ACCESS` — нужен хост/root;
`BLOCKED_SECRETS` — нужны секреты; `NOT_RUN` — не выполнялось; `NOT_APPLICABLE`.

| № | Сценарий | Как воспроизвести | Ожидаемый результат | Статус в репозитории | Статус на VPS |
| --- | --- | --- | --- | --- | --- |
| 1 | Нет обновления | `auto-update.sh run` при актуальной версии | `last_result: current`, файлы не меняются | PASS (тест агента) | NOT_RUN |
| 2 | Есть новая версия | Опубликовать релиз `vX.Y.Z+1` | `last_result: updated`, версия в статусе сменилась | PASS (тест проверки версий) | NOT_RUN |
| 3 | GitHub недоступен | Заблокировать `api.github.com` | `502` в API, `last_result: failed`, установка не начата | PASS (тест API) | NOT_RUN |
| 4 | Нет прав | Вызвать `POST /run` без `settings.runtime.write` | `403` | PASS (тест API) | NOT_RUN |
| 5 | Неправильный артефакт | Релиз без `.sha256`/манифеста | `update_available: false`, установка не начинается | PASS (тест `release_status`) | NOT_RUN |
| 6 | Несовпадение SHA-256 | Подменить байт в архиве | Отказ до распаковки, установка не тронута | PASS (тест fetch) | NOT_RUN |
| 7 | Несовместимость версии | Тег `vX.Y.Z-beta`/`prerelease` | Релиз отклонён | PASS (тест `release_status`) | NOT_RUN |
| 8 | Недостаточно места | Заполнить диск, запустить обновление | Сбой на распаковке/снимке, откат | NOT_RUN | NOT_RUN |
| 9 | Ошибка резервного копирования | `chmod 000` на `.rollback` | Обновление остановлено, файлы целы | NOT_RUN | NOT_RUN |
| 10 | Ошибка миграции | Добавить падающую миграцию | `trap rollback ERR` → откат, `recovery_mode` | NOT_RUN | NOT_RUN |
| 11 | Ошибка перезапуска | Сломать образ backend | Откат, `last_result: failed` | NOT_RUN | NOT_RUN |
| 12 | Неуспешный health check | Вернуть 500 на `/health/ready` | Откат, `last_result: failed` | NOT_RUN | NOT_RUN |
| 13 | Параллельные запросы | Два `POST /run` подряд | Второй → `409` | PASS (тест API) | NOT_RUN |
| 14 | Повторный запуск | Повторная метка `check_now` | Обрабатывается один раз (`handled_check_now`) | PASS (тест агента) | NOT_RUN |
| 15 | Ручной запуск | «Обновить сейчас» в панели | Метка в запросе, исполнение ≤ 1 мин | PASS (тест API) | NOT_RUN |
| 16 | Ночной запуск | Дождаться 03:00 МСК (+15 мин) | `trigger: timer`, `last_run_at` обновился | BLOCKED_ACCESS | NOT_RUN |
| 17 | Отключение расписания | `auto-update.sh disable` | Юниты удалены, `enabled: false` | PASS (тест юнитов) | NOT_RUN |
| 18 | Восстановление | `rollback.sh` с архивом и дампом | Установка вернулась, `RECOVERY_MODE` | NOT_RUN | NOT_RUN |
| 19 | Отображение истории | Открыть «Выпуски → Обновления» | Версии, время, `log_tail`, `next_run` | PASS (build + typecheck) | NOT_RUN |

Сценарии 8–12 и 18 требуют управляемого сбоя на реальном хосте. Их нельзя честно выполнить в CI:
они проверяют именно поведение `update.sh`/`rollback.sh` с Docker и файловой системой.

## 4. Как провести проверку на тестовом сервере

Используйте **отдельный** VPS, не production. Пошагово:

```bash
# 0. Подготовка
export APP_DIR=/opt/vpn-shop
cd $APP_DIR && git log -1 --format='%h %s'

# 1. Резервная копия до начала
sudo BACKUP_BUNDLE_PASSWORD='<пароль>' bash scripts/backup.sh
ls -la /var/backups/vpn-shop/

# 2. Установка таймеров
sudo bash scripts/auto-update.sh install
sudo systemctl list-timers 'vpn-shop-update*' --no-pager

# 3. Сценарий 1: актуальная версия
sudo bash scripts/auto-update.sh run
# ожидается: last_result = current

# 4. Сценарий 2: новая версия
#    опубликуйте тестовый релиз vX.Y.Z+1 с полным набором ассетов,
#    затем:
sudo bash scripts/auto-update.sh run
cat $APP_DIR/.control/auto-update.status.json | jq '.status | {installed, latest, last_result}'

# 5. Сценарий 3: недоступный GitHub
sudo iptables -I OUTPUT -d 140.82.121.6 -j REJECT   # адрес проверьте через dig api.github.com
sudo bash scripts/auto-update.sh run
sudo iptables -D OUTPUT -d 140.82.121.6 -j REJECT

# 6. Сценарий 6: подмена контрольной суммы
#    вручную измените один байт скачанного архива в /tmp и запустите проверку —
#    установка должна отказать ДО распаковки

# 7. Сценарий 16: ночной запуск
sudo systemctl start vpn-shop-update.timer
journalctl -u vpn-shop-update -f   # дождаться OnCalendar
```

## 5. Критерии приёмки

Автообновление считается проверенным на конкретной установке, когда одновременно:

- сценарии 1, 2, 3, 13, 15 дают ожидаемый результат;
- сценарий 6 (подмена SHA-256) приводит к отказу установки, а не к установке;
- сценарий 10 или 12 приводит к откату и `recovery_mode: true`, а магазин остаётся доступным;
- сценарий 18 восстанавливает рабочую версию;
- `journalctl -u vpn-shop-update` не содержит значений из `.env`;
- хотя бы один ночной запуск (сценарий 16) прошёл без ручного вмешательства.

## 6. Очистка после тестов

```bash
# удалить тестовые снимки, оставив последний
ls -lt $APP_DIR/.rollback/*.tar.gz | tail -n +2 | xargs -r rm --

# снять флаг восстановления, если ставился
sudo rm -f $APP_DIR/.rollback/RECOVERY_MODE

# сбросить блокировку неудачного релиза
sudo rm -f /etc/vpn-shop/auto-update.failed

# вернуть расписание в исходное состояние
sudo bash scripts/auto-update.sh install

# удалить тестовый релиз на GitHub (не затрагивая стабильные)
gh release delete vX.Y.Z --yes
```

Дата и результат проверки: заполняется оператором при прохождении. В репозитории на момент
`v28.57.0` сценарии с 8 по 12, 16 и 18 имеют статус `NOT_RUN` — они требуют хоста.
