# Автообновление и откат

Сервер обновляется с GitHub сам, без SSH и без участия владельца. Управление — в админке
«Выпуски → Автообновление». Если выпуск не прошёл проверки, сервер откатывается к прежней версии.

## Участники

| Где | Что | Файл |
| --- | --- | --- |
| Хост (root, systemd) | Агент: ночной таймер `vpn-shop-update` и таймер `vpn-shop-update-agent` (раз в минуту) | `scripts/auto_update.py`, `scripts/auto-update.sh` |
| Хост | Загрузка и проверка выпуска (SHA-256, манифест) | `scripts/update-from-github.sh`, `scripts/github_release_fetch.py` |
| Хост | Снимок, замена файлов, сборка, откат при ошибке | `scripts/update.sh`, `scripts/rollback.sh` |
| Хост | Сборка образов, переключение без простоя, проверки здоровья | `deploy/build-production.sh`, `scripts/zero-downtime-backend.sh` |
| backend | Экран в админке, запрос «Обновить сейчас» | `backend/app/auto_update_api.py` |

Панель и агент связаны только двумя файлами в `$APP_DIR/.control` (в контейнере — `/data/control`):

* `auto-update.request.json` пишет панель: `{"enabled", "time", "check_now"}`. Агент принимает только
  эти три поля и проверяет их формат, поэтому панель не может выполнить на сервере ничего другого.
* `auto-update.status.json` пишет агент: версии, расписание, итог последнего запуска, хвост журнала.

## Цикл

```mermaid
sequenceDiagram
    participant A as Админка
    participant G as Агент (host)
    participant U as update.sh
    participant D as Docker / Caddy
    A->>G: request.json: check_now
    G->>U: update-from-github.sh (SHA-256, манифест)
    U->>U: снимок файлов (.rollback/*.tar.gz) и дамп базы
    U->>D: build-production.sh: сборка, standby, проверка /health/ready
    alt проверки пройдены
        D-->>U: 200
        U-->>G: Update completed
        G->>A: status.json: updated, новая версия; уведомление в Telegram
    else ошибка
        U->>U: trap rollback: файлы и база из снимка, сборка прежней версии
        G->>A: status.json: failed; выпуск записан в auto-update.failed
    end
```

## Правила

* **Неудачный выпуск не повторяется каждую ночь.** Его номер хранится в `/etc/vpn-shop/auto-update.failed`;
  ночной запуск ждёт следующего выпуска. Кнопка «Повторить» в панели (trigger `panel`) пробует снова.
* **Режим восстановления.** Пока существует `.rollback/RECOVERY_MODE`, обновления не запускаются.
* **Снимки.** Перед каждым обновлением: архив файлов без `.env` и дамп базы. Хранятся последние 5.
* **Без простоя.** Новая версия backend сначала стартует рядом со старой — см. [zero_downtime.md](zero_downtime.md).
  Откат (`update.sh`, `rollback.sh`) удаляет и standby-контейнер (`docker compose --profile standby down`).
* **Один запуск за раз** — блокировка `/run/vpn-shop-update.lock`.

## Проверки в тестах

* `tests/test_auto_update_agent.py` — агент: установка таймеров, запрос из панели, неудачный выпуск, режим восстановления.
* `tests/test_auto_update_api.py` — панель: запись запроса, повторный запрос, права.
* `tests/test_e2e_journeys.py::test_panel_agent_update_rollback_and_retry` — полный цикл: панель → агент →
  неудачный выпуск откатывается → повтор из панели → новая версия.
