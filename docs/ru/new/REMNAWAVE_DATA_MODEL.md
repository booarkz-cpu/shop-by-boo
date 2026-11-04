# Модель данных Remnawave Manager

Часть этапа 9. Общая схема — в [REMNAWAVE_ARCHITECTURE](REMNAWAVE_ARCHITECTURE.md), API — в [REMNAWAVE_API_DESIGN](REMNAWAVE_API_DESIGN.md). Таблицы магазина целиком описаны в [DATABASE_SCHEMA](DATABASE_SCHEMA.md); он генерируется из моделей.

## 1. Где хранятся данные

Правило одно: магазин не копирует то, чем владеет Remnawave. В своей базе магазин хранит только ссылки и то, чего в панели нет.

| Данные | Владелец | Что хранит магазин |
| --- | --- | --- |
| Пользователи VPN, срок, трафик, лимит устройств | Remnawave | `subscriptions.remnawave_uuid` (синоним `remnawave_user_id`) — числовой id пользователя панели 3.x, снимки лимитов на момент оплаты |
| Ноды, хосты, профили конфигурации, сквады | Remnawave | UUID в настройках тарифа (`plans.remnawave_profile_id`) и автомасштабирования; копий списков нет |
| Устройства HWID | Remnawave | Ничего. Кабинет читает их у панели (`/api/me/hwid-devices`), наружу отдаётся только отпечаток |
| Плагины нод | Remnawave (`node-plugins`) | С этапа 12 — какие расширения магазин включил и в каком состоянии задача |
| Серверы (VPS) и доступ к ним | Магазин | С этапа 10 — реестр серверов |
| Установки, их шаги и журналы | Магазин | С этапа 10 — установки и шаги |
| Домены и сертификаты серверов Remnawave | Магазин | С этапа 11 — домены |
| Копии магазина | Магазин | `backup_jobs`, `backup_verifications` |
| Журнал действий, очередь задач | Магазин | `audit_logs`, `jobs` |

## 2. Что уже есть

| Таблица или ключ | Компонент | Содержимое |
| --- | --- | --- |
| `runtime_setting_state`, `runtime_setting_changes`: `remnawave_url`, `remnawave_token` («Настройки без перезапуска») | Remnawave Manager | Адрес и токен панели с версиями и журналом изменений; токен — секрет, в API маскируется |
| `node_agents` | Node Manager, Server Registry | Агент на узле: имя, хэш токена, CPU, память, диск, состояние Xray, версия, готовность терминала, последняя связь |
| `agent_actions` | Node Manager | Действия для агента: `kind`, `payload`, `status` (`queued` → `delivered`/`rejected`) |
| `jobs` | Job Manager | Очередь worker: `job_key` (уникален — нет повторного запуска), `kind`, `status`, попытки, ошибка, `payload` |
| `audit_logs` | Audit Manager | Кто, что, над чем и когда; `request_id` связывает запись с запросом |
| `backup_jobs`, `backup_verifications` | Backup Manager | Копии магазина и проверки восстановления |
| `release_records`, `deployments` | Update Manager | Выпуски магазина и постепенный перевод трафика на новую версию |
| `monitoring_checks`, `status_components` | Health Manager | Внешние проверки и публичный статус |
| Конфигурация `sub_proxy` в `app_settings` | Subscription Manager | Свой домен подписки, правила приложений, заблокированные устройства |

## 3. Таблицы мастера установки (этап 10, v28.66.0), доменов (этап 11, v28.67.0) и будущие (этап 12)

Таблицы этапа 10 созданы миграцией `0090_remnawave_installer`, этапа 11 — `0093_ssh_key_rotation`. Таблиц этапа 12 ещё нет: они появятся вместе с работающими функциями.

### `remnawave_servers` — реестр серверов

| Поле | Тип | Примечание |
| --- | --- | --- |
| `id` | integer, PK | |
| `name` | varchar(80), уникально | Имя в панели магазина |
| `host` | varchar(255) | IP или имя хоста; адреса loopback, link-local и multicast отклоняются |
| `ssh_port` | integer | 1–65535 |
| `ssh_user` | varchar(64) | root или пользователь с `sudo` без пароля |
| `auth_method` | varchar(16) | `key` или `password` |
| `ssh_secret` | text | Ключ или пароль, зашифрован `security.encrypt_secret`; в API не отдаётся. Хранится после установки: обновление и удаление идут по SSH |
| `host_key_fingerprint` | varchar(64) | `SHA256:…`, обязателен: без него подключения нет |
| `roles` | JSON-массив | Установленные компоненты: `panel`, `node`, `subscription_page` |
| `status` | varchar(24) | `new`, `ready`, `check_failed`, `unreachable`, `installed`, `removed` |
| `os`, `arch`, `cpu_cores`, `ram_mb`, `disk_gb` | | Из preflight, не из ввода |
| `preflight` | JSON | Последний отчёт проверки и назначение сервера (`purpose`) |
| `last_checked_at`, `created_at`, `updated_at` | timestamp | |

### `remnawave_installations` — задачи мастера

| Поле | Тип | Примечание |
| --- | --- | --- |
| `id` | integer, PK | Номер задачи |
| `action` | varchar(16) | `install`, `update`, `diagnose`, `restore`, `reinstall`, `remove` |
| `mode` | varchar(32) | `panel_node`, `panel`, `node`, `panel_subpage`, `subpage`, `distributed`, `add_node` |
| `server_ids` | JSON-массив | Серверы задачи |
| `params` | JSON | Проверенный ввод мастера (`PlanIn`) |
| `plan` | JSON | Шаги, последствия, закреплённые образы — то, что показано до подтверждения |
| `plan_sha256` | varchar(64) | Запуск только с этим хэшем; при запуске план строится заново и сверяется |
| `status` | varchar(24), индекс | `planned`, `queued`, `running`, `succeeded`, `failed`, `cancelled` |
| `secrets` | text | Зашифрованный JSON: пароли базы и администратора панели, токен API, ключи. Наружу — только вход администратора по отдельной кнопке с записью в журнал |
| `result` | JSON | Адрес панели и страницы подписки, ноды в панели, служебное состояние шагов |
| `error` | text | Причина остановки без секретов |
| `created_by`, `approved_by` | varchar(320) | Email администраторов |
| `cancel_requested` | boolean | Остановить после текущего шага |
| `source_installation_id` | integer | Для действий — установка, над которой они выполняются |
| `worker_id`, `heartbeat_at` | | Кто выполняет и последний «пульс» (без пульса 5 минут — `failed`) |
| `created_at`, `started_at`, `finished_at` | timestamp | |

Отдельной таблицы связи с серверами нет: серверы задачи — в `server_ids`, их роли — в `plan.servers`. Общая очередь `jobs` не используется: у мастера свой исполнитель ([DEPLOYMENT_AGENT](DEPLOYMENT_AGENT.md)).

### `remnawave_deployment_steps` — шаги задачи

| Поле | Тип | Примечание |
| --- | --- | --- |
| `id` | integer, PK | |
| `installation_id` | integer, FK, индекс | Удаление задачи удаляет шаги |
| `server_id` | integer | Пусто у шага `verify` |
| `position` | integer | Порядок выполнения |
| `kind` | varchar(48) | Тип шага из закрытого списка `rw_steps.STEP_KINDS` |
| `title` | varchar(200) | Как шаг показан в плане |
| `params` | JSON | Только значения схемы шага, без секретов |
| `status` | varchar(16) | `pending`, `running`, `done`, `failed`, `skipped`, `rolled_back` |
| `log_tail` | text | Последние 4000 символов вывода, секреты заменены на `***` |
| `started_at`, `finished_at` | timestamp | |

### `remnawave_domains` — домены (этап 11, v28.67.0, миграция `0091_remnawave_domains`)

| Поле | Тип | Примечание |
| --- | --- | --- |
| `id` | integer, PK | |
| `domain` | varchar(253), уникально | Проверяется по шаблону имени хоста, хранится в нижнем регистре |
| `purpose` | varchar(24) | `subscription`, `panel`, `subscription_page`, `node`, `other` |
| `served_by` | varchar(16) | `shop` (Caddy магазина, сертификат on demand), `remnawave` (Caddy сервера мастера), `external` |
| `server_id` | integer | Сервер реестра для `remnawave` |
| `expected_ip` | varchar(64) | Куда должен указывать домен; только публичный адрес |
| `enabled` | boolean | Выключенный домен не получает сертификат |
| `dns_status`, `dns_records`, `dns_checked_at` | | Результат проверки DNS: `ok`, `missing`, `mismatch`, `caa`, `error`; записи A, AAAA, CNAME, TXT, CAA и ожидаемые адреса |
| `cert_status`, `cert_issuer`, `cert_expires_at`, `cert_checked_at` | | `valid`, `expiring`, `expired`, `invalid`, `missing` |
| `http_status`, `last_error` | | Ответ HTTPS и причина проблем |
| `created_by`, `created_at`, `updated_at` | | |

Сами сертификаты хранит Caddy, таблица — только результаты проверок ([SUBSCRIPTION_DOMAIN](SUBSCRIPTION_DOMAIN.md)).

### `remnawave_node_modules` — расширения нод (этап 12)

`id`, `node_uuid`, `module`, `plugin_uuid` (UUID плагина в панели, если расширение — плагин панели), `version`, `status`, `job_id`. Список модулей закрыт и описан на этапе 12.

## 4. Правила

- **Время — UTC.** Это требование и самой панели: её база должна быть в UTC.
- **Ссылки на панель** — UUID и числовые id из ответов API. Имена могут меняться.
- **Секреты** не хранятся в `params`, `plan` и журналах. Ссылки на них ведут к зашифрованным полям.
- **Удаление сервера** — это перевод в `retired`. Реальное удаление строки — только если на сервере нет установок.
