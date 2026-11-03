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

## 3. Новые таблицы (этапы 10–12)

Таблиц ниже ещё нет. Они появятся миграциями вместе с работающими функциями. Пустых таблиц заранее не будет.

### `remnawave_servers` — реестр серверов (этап 10)

| Поле | Тип | Примечание |
| --- | --- | --- |
| `id` | integer, PK | |
| `name` | varchar(80), уникально | Имя в панели магазина |
| `host` | varchar(255) | IP или имя хоста; проверка формата |
| `ssh_port` | integer | 1–65535 |
| `ssh_user` | varchar(64) | |
| `auth_method` | varchar(16) | `key` или `password` (пароль — только для первичной установки) |
| `ssh_secret` | text | Ключ или пароль, зашифрован `security.encrypt_secret`; в API не отдаётся |
| `host_key_fingerprint` | varchar(64) | `SHA256:…`, обязателен: без него подключения нет |
| `os`, `arch`, `cpu_cores`, `ram_mb`, `disk_gb` | | Из preflight, не из ввода |
| `roles` | JSON-массив | `panel`, `node`, `subscription_page` |
| `status` | varchar(24) | `new`, `checked`, `installing`, `ready`, `failed`, `retired` |
| `last_checked_at`, `created_at`, `updated_at` | timestamp | |

### `remnawave_installations` — установки (этап 10)

| Поле | Тип | Примечание |
| --- | --- | --- |
| `id` | integer, PK | |
| `mode` | varchar(32) | `panel_node`, `panel`, `node`, `panel_subpage`, `subpage`, `distributed`, `add_node` |
| `plan` | JSON | Шаги, файлы, порты, последствия — то, что показано администратору до подтверждения |
| `plan_sha256` | varchar(64) | Выполняется только подтверждённый план: хэш сверяется перед запуском |
| `versions` | JSON | Закреплённые образы (тег и digest), проверенные в CI |
| `status` | varchar(24) | `planned`, `approved`, `running`, `succeeded`, `failed`, `rolled_back` |
| `created_by`, `approved_by` | varchar(255) | Email администраторов |
| `job_id` | integer | Задача в `jobs` |
| `created_at`, `finished_at` | timestamp | |

Связь «многие ко многим» с серверами — через `remnawave_installation_servers` (`installation_id`, `server_id`, `roles`).

### `remnawave_deployment_steps` — шаги установки (этап 10)

| Поле | Тип | Примечание |
| --- | --- | --- |
| `id` | integer, PK | |
| `installation_id`, `server_id` | integer | |
| `position` | integer | Порядок выполнения |
| `kind` | varchar(48) | Тип шага из закрытого списка ([DEPLOYMENT_AGENT_ARCHITECTURE](DEPLOYMENT_AGENT_ARCHITECTURE.md)) |
| `params` | JSON | Только значения схемы шага, без секретов: секреты подставляются при выполнении |
| `status` | varchar(16) | `pending`, `running`, `done`, `failed`, `skipped`, `rolled_back` |
| `log_tail` | text | Последние строки вывода, секреты вырезаются |
| `started_at`, `finished_at` | timestamp | |

### `remnawave_domains` — домены (этап 11)

`id`, `domain` (уникально), `purpose` (`panel`, `subscription`, `node_sni`, `shop_sub_proxy`), `server_id`, `dns_status`, `dns_checked_at`, `cert_status`, `cert_expires_at`. Домены сервера магазина обслуживает общий Caddy; для них `server_id` пуст.

### `remnawave_node_modules` — расширения нод (этап 12)

`id`, `node_uuid`, `module`, `plugin_uuid` (UUID плагина в панели, если расширение — плагин панели), `version`, `status`, `job_id`. Список модулей закрыт и описан на этапе 12.

## 4. Правила

- **Время — UTC.** Это требование и самой панели: её база должна быть в UTC.
- **Ссылки на панель** — UUID и числовые id из ответов API. Имена могут меняться.
- **Секреты** не хранятся в `params`, `plan` и журналах. Ссылки на них ведут к зашифрованным полям.
- **Удаление сервера** — это перевод в `retired`. Реальное удаление строки — только если на сервере нет установок.
