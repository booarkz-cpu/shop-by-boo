# Deployment Agent: исполнитель установок

С v28.66.0 (этап 10). Выполняет планы мастера установки Remnawave ([REMNAWAVE_INSTALLATION_WIZARD](REMNAWAVE_INSTALLATION_WIZARD.md)). Замысел — в [DEPLOYMENT_AGENT_ARCHITECTURE](DEPLOYMENT_AGENT_ARCHITECTURE.md); здесь — как устроено в коде.

## 1. Где работает

| Часть | Файл |
| --- | --- |
| Маршруты админки `/api/admin/rw/...` | `backend/app/rw_api.py` |
| План по режиму, файлы compose, `.env`, Caddyfile | `backend/app/rw_plan.py` |
| Шаги — закрытый список, их скрипты и откаты | `backend/app/rw_steps.py` |
| SSH с закреплённым ключом сервера | `backend/app/rw_remote.py` |
| Исполнитель: очередь, шаги, откат, «пульс» | `backend/app/rw_jobs.py`, цикл `installer_worker` в `backend/worker.py` |
| Таблицы `remnawave_servers`, `remnawave_installations`, `remnawave_deployment_steps` | `backend/app/models.py`, миграция `0090_remnawave_installer` |
| Раздел админки | `admin/src/rw-installer.tsx` |

Исполнитель — отдельный цикл worker, не общая очередь `jobs`: установка длится до получаса и не должна задерживать платежи и выдачу подписок.

## 2. Задача

Задача — строка `remnawave_installations` со своими шагами.

| Поле | Что |
| --- | --- |
| `id` | Номер задачи |
| `action` | `install`, `update`, `diagnose`, `restore`, `reinstall`, `remove` |
| `server_ids` | Серверы |
| `status` | `planned` → `queued` → `running` → `succeeded`, `failed` или `cancelled` |
| `plan`, `plan_sha256` | Ровно то, что видел администратор; запуск — только с этим SHA-256 |
| шаги | `position`, `kind`, `title`, `status` (`pending`, `running`, `done`, `failed`, `rolled_back`, `skipped`), хвост журнала до 4000 символов, время |
| `error` | Причина остановки для администратора, без секретов |
| `created_by`, `approved_by` | Кто составил и кто запустил |
| `created_at`, `started_at`, `finished_at`, `heartbeat_at` | Время |

Прогресс в разделе — доля завершённых шагов.

## 3. Закрытый список шагов

`rw_steps.STEP_KINDS`. Шаг другого типа исполнитель не выполняет. Каждый шаг — фиксированный скрипт bash модуля `rw_steps`; значения передаются позиционными аргументами (`bash -c <скрипт> rw <аргументы>`, каждый через `shlex.quote`) или через stdin. Текст команды из браузера не приходит ни в каком виде.

| Шаг | Что делает | Откат при установке |
| --- | --- | --- |
| `preflight` | Только читает ([REMNAWAVE_PREFLIGHT](REMNAWAVE_PREFLIGHT.md)) | — |
| `install_docker` | Docker из подписанного репозитория, отпечаток ключа apt сверяется (`provisioner.DOCKER_INSTALL`) | Docker не удаляется |
| `write_files` | Файл через stdin в один из каталогов (`/opt/remnawave`, `/opt/remnanode`, `/opt/remnawave-subpage`, `/opt/remnawave-caddy`, `/opt/remnawave-selfsteal`, `/opt/remnawave-xray-checker`), имена — только `docker-compose.yml`, `.env`, `Caddyfile`, `index.html`; SHA-256 сверяется на сервере; прежний файл сохраняется как `.rw-prev` | Прежний файл возвращается, новый удаляется |
| `compose_up` | `docker compose pull` и `up -d` закреплённых образов | `docker compose down`, volumes остаются |
| `wait_panel` | Панель отвечает на `127.0.0.1:3001/health` (до 3 минут) | — |
| `panel_bootstrap` | Первый администратор (`POST /api/auth/register`, при повторе — вход) и токен API `corgi-shop` (`POST /api/tokens`) | — |
| `firewall_node_port` | Если ufw включён — порт ноды только с адреса панели | Правило удаляется |
| `register_node` | `POST /api/nodes` с профилем конфигурации панели | `DELETE /api/nodes/{uuid}` |
| `verify` | HTTPS панели через Caddy, при Let's Encrypt — с сервера магазина; связь нод; страница подписки | — |
| `backup_panel` | `pg_dump` базы панели на её сервере; хранятся 5 последних копий | — |
| `restore_panel` | Восстановление базы панели из последней копии | — |
| `compose_down` | Остановка контейнеров компонента | — |
| `selfsteal_profile` | v28.70.0: профиль VLESS + REALITY с `dest` на сокете SelfSteal и хост домена ноды в панели ([REMNAWAVE_EXTENSIONS](REMNAWAVE_EXTENSIONS.md)) | Хост и профиль удаляются |
| `node_module` | v28.70.0: модуль сервера — IPv6, ядро Xray (SHA-256 из GitHub), WARP Native, NetBird (ключ через stdin), проверка Xray Checker ([WARP_NETBIRD](WARP_NETBIRD.md), [XRAY_CHECKER](XRAY_CHECKER.md)) | Прежняя настройка или файл возвращается |

Пока панель только ставится, её API вызывается по SSH на `127.0.0.1:3000` с заголовками прокси; токен передаётся через stdin и временный файл с правами 600, не в аргументах. Для панели, подключённой к магазину, — обычный клиент магазина.

Действие «Модуль» (v28.70.0) — план над успешной установкой, как «Обновить»: при ошибке откатываются его шаги `node_module`, прежние файлы возвращаются, контейнеры запускаются с ними (не останавливаются). Выбранное ядро Xray и Xray Checker сохраняются в установке и переживают «Обновить».

При ошибке шага у «Обновить» и «Переустановить» откат возвращает прежние файлы и запускает контейнеры с ними. У «Диагностики», «Восстановления» и «Удаления» отката нет: ошибка показывается как есть.

## 4. Очередь и надёжность

- **Один запуск.** Задачу берёт один worker: `SELECT … FOR UPDATE SKIP LOCKED`, затем `running`.
- **Один сервер — одна задача.** Запуск отклоняется, если на том же сервере есть задача `queued` или `running`.
- **Устаревший план.** При запуске план строится заново из текущих серверов и подключения магазина; если SHA-256 другой — 409.
- **Пульс.** Во время работы `heartbeat_at` обновляется каждые 20 секунд. Задача `running` без пульса 5 минут (worker остановился) становится `failed` с причиной «Прервано» — её не перезапускают молча: состояние сервера неизвестно, нужна «Диагностика».
- **Отмена.** До запуска — сразу; во время — после текущего шага, затем откат выполненного.
- **Повтор шага.** Шаги можно повторить: запись файлов и `compose up` дают тот же результат, `panel_bootstrap` при уже созданном администраторе входит, `register_node` не создаёт вторую ноду.

## 5. Безопасность

| Требование | Как выполнено |
| --- | --- |
| Минимальные привилегии | Root или `sudo -n` нужен для Docker и `/opt`; шаги пишут только в четыре каталога и только три имени файлов |
| Allowlist | Закрытый список шагов и скриптов; каталоги и имена файлов проверяются и в Python, и в скрипте на сервере |
| Изоляция | Компоненты в своих контейнерах; порты панели и страницы подписки — только на `127.0.0.1`, наружу — Caddy |
| Взаимная проверка (эквивалент mTLS) | Сервер подтверждает себя ключом, закреплённым по отпечатку; магазин — ключом или паролем SSH |
| Секреты | Ключ или пароль SSH, пароли базы и администратора панели, токен API — зашифрованы (`security.encrypt_secret`), в ответы API не попадают; в журналах шагов заменяются на `***` |
| Аудит | `rw.server.created`, `rw.server.updated`, `rw.server.deleted`, `rw.installation.planned`, `rw.installation.approved`, `rw.installation.cancelled`, `rw.installation.credentials_viewed`; подключение магазина — `runtime_settings.staged` и `runtime_settings.applied` |

## 6. Чего пока нет

- **Агент на сервере установки** (`install_agent` из замысла) не ставится. Обновление и удаление идут по SSH из worker, поэтому ключ SSH хранится в реестре зашифрованным. Агент и автообновление панели и нод — этап 15.
- **Копия базы панели** остаётся на её сервере (5 последних) и в хранилище магазина (S3, Telegram) не передаётся — этап 15.
- **Проверка на настоящем VPS** с Let's Encrypt и сеть между разными серверами — BLOCKED_EXTERNAL, нужен тестовый VPS владельца.
