# API Remnawave Manager

Часть этапа 9. Общая схема — в [REMNAWAVE_ARCHITECTURE](REMNAWAVE_ARCHITECTURE.md), данные — в [REMNAWAVE_DATA_MODEL](REMNAWAVE_DATA_MODEL.md), полный список маршрутов магазина — в [API](API.md).

Здесь описаны две стороны:
1. Как магазин вызывает API панели Remnawave.
2. Какие маршруты админ-панели магазина есть и какие появятся.

## 1. API панели, которым пользуется магазин

Клиент — `backend/app/remnawave.py`, контракт — `@remnawave/backend-contract` 3.4.15 (панель 3.4.8). Магазин вызывает только маршруты, которые есть в контракте. В столбце «Проверено на панели» указан тест из `tests/live/test_remnawave_live.py`.

| Маршрут панели | Метод клиента | Где используется | Проверено на панели |
| --- | --- | --- | --- |
| `GET /api/keygen` | `node_secret_key` | Ключ новой ноды: установка, автомасштабирование | `test_nodes_and_node_key`, `test_mode_panel_plus_node` |
| `POST /api/nodes`, `DELETE /api/nodes/{uuid}` | `create_node`, `delete_node` | Node Manager, автомасштабирование | `test_nodes_and_node_key`, `test_mode_panel_plus_node` |
| `GET /api/nodes` | `list_nodes` | Состояние системы, мониторинг нод | `test_nodes_and_node_key`, `test_mode_panel_plus_node` |
| `POST /api/nodes/{uuid}/actions/restart`, `POST /api/nodes/actions/restart-all` | `restart_node`, `restart_all_nodes` | Node Manager | `test_nodes_and_node_key` |
| `GET /api/config-profiles` | `_request` | Профиль новой ноды | `test_nodes_and_node_key` |
| `GET /api/internal-squads`, bulk add/remove | `list_internal_squads`, `squad_add_all_users`, `squad_remove_all_users` | Резервный сквад, тарифы | `test_users_and_reserve_squad` |
| `POST /api/users`, `PATCH /api/users`, `GET /api/users/{id}` | `create_user`, `patch_user`, `get_user`, `update_entitlements` | Выдача и изменение подписки | `test_users_and_reserve_squad`, `test_lucy_limits_and_customer_devices` |
| `GET /api/hwid/devices/{userId}`, `POST /api/hwid/devices/delete`, `POST /api/hwid/devices/delete-all` | `hwid_devices`, `delete_hwid_device`, `reset_hwid_devices` | Устройства в кабинете, антишаринг | `test_lucy_limits_and_customer_devices` |
| `GET /api/subscriptions/by-short-uuid/{shortUuid}`, `GET /api/sub/{shortUuid}` | `_request`, `sub_proxy` | Прослойка подписки | `test_connections_bandwidth_keys_and_subscription_proxy` |
| Страница подписки `GET /{shortUuid}` (отдельный сервис) | — | Режимы 4 и 5 | `test_mode_panel_plus_subscription_page` |

Ошибки:
- Если панель не настроена, магазин отвечает 503 (`RemnawaveNotConfigured`).
- Если панель вернула ошибку или не ответила — 502, ответ панели клиенту не передаётся (`backend/app/errors.py`).
- После серии сбоев включается обрыв цепи. Счётчик хранится в Redis, порог задаётся `REMNAWAVE_CB_FAILURES`.

Маршруты контракта, которые магазин пока не вызывает и которые нужны на следующих этапах:
- `node-plugins` (плагины нод, общие списки, отчёты TorrentBlocker) — этап 12, менеджер расширений;
- `system` (`GET /api/system/health`, `/metadata`, `/nodes/metrics`) — этап 10, проверка панели после установки;
- `subscription-page-configs` — этап 11, страница подписки на своём домене.

Каждый новый вызов добавляется вместе с живым тестом в `tests/live/test_remnawave_live.py`.

## 2. Маршруты магазина: что есть

| Компонент | Маршруты | Право |
| --- | --- | --- |
| Remnawave Manager | `GET /api/admin/panel/overview`; хосты: `POST`, `PUT`, `PATCH`, `DELETE /api/admin/panel/hosts…`; сквады: `POST`, `PATCH`, `DELETE /api/admin/panel/squads…`; `GET`, `PUT /api/admin/panel-guard` | `read`, `provision_nodes`, `settings.runtime.write` |
| Deployment Manager | `POST /api/admin/provision-node` — установка ноды по SSH. С v28.65.0 тело — `NodeProvisionIn`: `host`, `ssh_port`, `ssh_username`, `ssh_password` или `ssh_private_key`, `ssh_host_key`, `panel_ip`, `node_port`; лишние поля — 422 | `provision_nodes` |
| Node Manager | `GET /api/admin/nodes/health`, `PUT /api/admin/nodes/health/config`, `POST /api/admin/nodes/{node_uuid}/restart`, `POST /api/admin/nodes/update`, `GET`/`PUT /api/admin/nodes/autoscale`, терминал `/api/admin/terminal…` | `ops.diagnostics`, `provision_nodes`, `nodes.terminal` |
| Subscription Manager | `GET`/`PUT /api/admin/sub-proxy`, `POST`/`DELETE /api/admin/sub-proxy/blocked…`, `GET /api/admin/sub-proxy/log`, `GET /api/admin/sub-proxy/apps`; публично `GET /sub/{path}` | `ops.diagnostics`, `settings.runtime.write`, `users.write` |
| Backup Manager | `/api/admin/backups…` (создание, проверка, восстановление в два шага) | `backups.*` |
| Update Manager | `GET /api/admin/github-update`, `/api/admin/auto-update…`, `/api/admin/releases`, `/api/admin/deployments` | `ops.releases`, `settings.runtime.write` |
| Health Manager | `GET /api/admin/health/summary`, `GET /api/admin/system/health`, `GET /api/admin/ops/readiness` | `ops.diagnostics`, `read` |
| Job Manager | `GET /api/admin/jobs`, `POST /api/admin/jobs/{job_id}/retry`, `GET /api/admin/workers` | `read`, `payments.retry` |
| Audit Manager | `GET /api/admin/audit` (фильтры `actor`, `action`, `target`, `since`, `until`) | `read` |
| Агент узла | `POST /api/agent/heartbeat`, `POST /api/agent/observations`, терминал `/api/agent/terminal…` | токен агента в заголовке |

## 3. Маршруты магазина: что появится

Все новые маршруты устроены одинаково:
- тело — модель Pydantic с `extra="forbid"`;
- долгая операция отвечает `202` с номером задачи;
- состояние задачи — отдельным `GET`;
- изменения пишутся в журнал действий;
- права — существующие, новых ролей нет.

### Server Registry и preflight (этап 10)

| Метод и путь | Тело или ответ | Право |
| --- | --- | --- |
| `GET /api/admin/rw/servers` | Список серверов без секретов; фильтры `role`, `status` | `read` |
| `POST /api/admin/rw/servers` | `ServerIn`: `name`, `host`, `ssh_port`, `ssh_user`, `auth_method`, `ssh_secret`, `host_key_fingerprint`, `roles` | `provision_nodes` |
| `PATCH`/`DELETE /api/admin/rw/servers/{id}` | Изменение без секрета или с новым секретом; удаление — перевод в `retired` | `provision_nodes` |
| `POST /api/admin/rw/servers/{id}/fingerprint` | Получить отпечаток ключа хоста для сверки администратором; без входа | `provision_nodes` |
| `POST /api/admin/rw/servers/{id}/preflight` | `202 {job_id}`. Результат — отчёт: ОС, архитектура, CPU, RAM, диск, Docker, порты, DNS, найденные службы | `provision_nodes` |

### Установки (этап 10)

| Метод и путь | Тело или ответ | Право |
| --- | --- | --- |
| `POST /api/admin/rw/installations/plan` | `PlanIn`: `mode`, серверы и роли, домены, параметры Remnawave. Ответ — план: шаги, файлы, порты, последствия, `plan_sha256` | `provision_nodes` |
| `POST /api/admin/rw/installations/{id}/approve` | `{plan_sha256}` — подтверждение именно показанного плана; затем `202 {job_id}` | `provision_nodes` |
| `GET /api/admin/rw/installations/{id}` | Состояние и шаги с хвостами журналов | `read` |
| `POST /api/admin/rw/installations/{id}/cancel` | Остановить после текущего шага и выполнить откат выполненных | `provision_nodes` |

### Домены и сертификаты (этап 11)

`GET`/`POST`/`DELETE /api/admin/rw/domains`, `POST /api/admin/rw/domains/{id}/check`. Проверка DNS выполняется с сервера магазина. Маршруты на сервере магазина добавляются в общий Caddy (`deploy/Caddyfile`), второго прокси нет.

### Расширения нод (этап 12)

`GET /api/admin/rw/modules` — закрытый список расширений с совместимостью. `POST /api/admin/rw/nodes/{uuid}/modules/{module}` — `202 {job_id}`. Где возможно, расширение — это плагин панели (`node-plugins`).

## 4. Повторы и параллельность

- **Повторный запрос.** Задача установки получает `job_key` = `rw-install:{installation_id}`. Уникальный ключ в `jobs` не даёт запустить её дважды.
- **Один сервер — одна установка.** Перед запуском backend берёт блокировку сервера в Redis.
- **Повтор шага.** Шаги идемпотентны: агент проверяет, выполнен ли шаг, прежде чем выполнять его (например, контейнер уже запущен с нужным образом).
- **Устаревший план.** Подтверждение с другим `plan_sha256` отклоняется: план изменился после показа администратору.
