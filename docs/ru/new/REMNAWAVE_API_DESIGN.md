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
| `POST /api/users/{id}/actions/revoke` | `revoke_subscription` | Смена ссылки подписки: кабинет и «Портал подписки» (v28.67.0) | `test_revoke_subscription_link` |
| `GET /api/system/tools/x25519/generate`, `POST`, `PATCH`, `DELETE /api/config-profiles`, `GET /api/config-profiles/{uuid}`, `PATCH /api/nodes` (профиль), `POST /api/hosts` | `_request` | Менеджер расширений: профили, REALITY, назначение нодам (v28.69.0) | `test_extensions_profiles_reality_and_nodes` |
| `/api/node-plugins`, `PATCH /api/nodes` (`activePluginUuid`), `/api/subscription-settings`, `POST /api/system/testers/srr-matcher`, `/api/subscription-page-configs`, `/api/subscription-templates` | `_request` | Плагины нод, правила подписки, страница и шаблоны подписки (v28.69.0) | `test_extensions_plugins_srr_pages_and_templates` |
| Страница подписки `GET /{shortUuid}` (отдельный сервис) | — | Режимы 4 и 5 | `test_mode_panel_plus_subscription_page` |

Ошибки:
- Если панель не настроена, магазин отвечает 503 (`RemnawaveNotConfigured`).
- Если панель вернула ошибку или не ответила — 502, ответ панели клиенту не передаётся (`backend/app/errors.py`).
- После серии сбоев включается обрыв цепи. Счётчик хранится в Redis, порог задаётся `REMNAWAVE_CB_FAILURES`.

Маршруты контракта, которые магазин пока не вызывает и которые нужны на следующих этапах:
- общие списки плагинов и отчёты TorrentBlocker (`/api/node-plugins/shared-lists`, `/torrent-blocker`) — этап 16, мониторинг;
- `system` (`GET /api/system/health`, `/metadata`, `/nodes/metrics`) — этап 10, проверка панели после установки;
- `subscription-page-configs` — не нужен: портал подписки магазина (v28.67.0) строит страницу сам, по каталогу клиентов владельца.

Каждый новый вызов добавляется вместе с живым тестом в `tests/live/test_remnawave_live.py`.

## 2. Маршруты магазина: что есть

| Компонент | Маршруты | Право |
| --- | --- | --- |
| Remnawave Manager | `GET /api/admin/panel/overview`; хосты: `POST`, `PUT`, `PATCH`, `DELETE /api/admin/panel/hosts…`; сквады: `POST`, `PATCH`, `DELETE /api/admin/panel/squads…`; `GET`, `PUT /api/admin/panel-guard` | `read`, `provision_nodes`, `settings.runtime.write` |
| Deployment Manager | `POST /api/admin/provision-node` — установка ноды по SSH. С v28.65.0 тело — `NodeProvisionIn`: `host`, `ssh_port`, `ssh_username`, `ssh_password` или `ssh_private_key`, `ssh_host_key`, `panel_ip`, `node_port`; лишние поля — 422 | `provision_nodes` |
| Node Manager | `GET /api/admin/nodes/health`, `PUT /api/admin/nodes/health/config`, `POST /api/admin/nodes/{node_uuid}/restart`, `POST /api/admin/nodes/{node_uuid}/enable|disable`, `PATCH /api/admin/nodes/{node_uuid}` (v28.84.0), `POST /api/admin/nodes/update`, `GET`/`PUT /api/admin/nodes/autoscale`, терминал `/api/admin/terminal…` | `ops.diagnostics`, `provision_nodes`, `nodes.terminal` |
| Subscription Manager | `GET`/`PUT /api/admin/sub-proxy`, `POST`/`DELETE /api/admin/sub-proxy/blocked…`, `GET /api/admin/sub-proxy/log`, `GET /api/admin/sub-proxy/apps`; публично `GET /sub/{path}` | `ops.diagnostics`, `settings.runtime.write`, `users.write` |
| Backup Manager | `/api/admin/backups…` (создание, проверка, восстановление в два шага) | `backups.*` |
| Update Manager | `GET /api/admin/github-update`, `/api/admin/auto-update…`, `/api/admin/releases`, `/api/admin/deployments` | `ops.releases`, `settings.runtime.write` |
| Health Manager | `GET /api/admin/health/summary`, `GET /api/admin/system/health`, `GET /api/admin/ops/readiness` | `ops.diagnostics`, `read` |
| Job Manager | `GET /api/admin/jobs`, `POST /api/admin/jobs/{job_id}/retry`, `GET /api/admin/workers` | `read`, `payments.retry` |
| Audit Manager | `GET /api/admin/audit` (фильтры `actor`, `action`, `target`, `since`, `until`) | `read` |
| Мастер установки (v28.66.0) | `GET /api/admin/rw/meta`; реестр: `GET`, `POST /api/admin/rw/servers`, `POST /api/admin/rw/servers/scan`, `PATCH`, `DELETE /api/admin/rw/servers/{server_id}`, `POST /api/admin/rw/servers/{server_id}/check`; задачи: `GET /api/admin/rw/installations`, `GET /api/admin/rw/installations/{installation_id}`, `POST /api/admin/rw/installations/plan`, `POST /api/admin/rw/installations/{installation_id}/approve`, `/cancel`, `/actions`, `/credentials`, `/connect-shop` — подробно в [REMNAWAVE_INSTALLATION_WIZARD](REMNAWAVE_INSTALLATION_WIZARD.md) | `read`, `provision_nodes`, `settings.runtime.write` |
| Домены, сертификаты, маршруты (v28.67.0) | `GET`, `POST /api/admin/rw/domains`, `PATCH`, `DELETE /api/admin/rw/domains/{domain_id}`, `POST /api/admin/rw/domains/{domain_id}/check`, `/primary`, `/dns-record`; `GET /api/admin/rw/certificates`, `POST /api/admin/rw/certificates/check`; `GET /api/admin/rw/proxy-routes`; для Caddy — `GET /caddy/ask` ([SUBSCRIPTION_DOMAIN](SUBSCRIPTION_DOMAIN.md)) | `read`, `settings.runtime.write` |
| Портал подписки (v28.67.0) | `POST /api/admin/sub-proxy/reset-link/{subscription_id}`; клиент — `POST /api/me/subscription/reset-link`; страница — `GET /sub/{shortUuid}` в браузере ([SUBSCRIPTION_PORTAL](SUBSCRIPTION_PORTAL.md)) | `users.write` |
| Менеджер расширений (v28.69.0) | `GET /api/admin/rw/extensions`; профили: `GET`, `POST /api/admin/rw/extensions/profiles…`, `POST /api/admin/rw/extensions/profiles/reality`, `GET /api/admin/rw/extensions/x25519`, `POST /api/admin/rw/extensions/nodes/{node_uuid}/profile`; плагины: `/api/admin/rw/extensions/plugins…`, `POST /api/admin/rw/extensions/nodes/{node_uuid}/plugin`; `GET`, `PATCH /api/admin/rw/extensions/subscription-settings`, `POST /api/admin/rw/extensions/srr-test`; `/api/admin/rw/extensions/subpage-configs…`, `/api/admin/rw/extensions/templates…`, `GET /api/admin/rw/extensions/presets` ([REMNAWAVE_EXTENSIONS](REMNAWAVE_EXTENSIONS.md)) | `read`, `provision_nodes`, `settings.runtime.write` |
| Агент узла | `POST /api/agent/heartbeat`, `POST /api/agent/observations`, терминал `/api/agent/terminal…` | токен агента в заголовке |

## 3. Маршруты магазина: что появится

Все новые маршруты устроены одинаково:
- тело — модель Pydantic с `extra="forbid"`;
- долгая операция отвечает `202` с номером задачи;
- состояние задачи — отдельным `GET`;
- изменения пишутся в журнал действий;
- права — существующие, новых ролей нет.

Маршруты этапа 10 сделаны в v28.66.0 и перечислены в разделе 2. Отличия от замысла:
- отпечаток читается до сохранения сервера: `POST /api/admin/rw/servers/scan` с адресом и портом;
- проверка сервера (`/check`) выполняется в запросе (до 2 минут), а не задачей: она только читает;
- запуск плана (`/approve`) ставит задачу в очередь мастера и сразу возвращает её; состояние — `GET /api/admin/rw/installations/{installation_id}`;
- обновление, диагностика, восстановление, переустановка и удаление — `POST /api/admin/rw/installations/{installation_id}/actions`, это новый план над успешной установкой.

Домены и сертификаты (этап 11) сделаны в v28.67.0 и перечислены в разделе 2.

### Расширения нод (этап 12)

`GET /api/admin/rw/modules` — закрытый список расширений с совместимостью. `POST /api/admin/rw/nodes/{uuid}/modules/{module}` — `202 {job_id}`. Где возможно, расширение — это плагин панели (`node-plugins`).

## 4. Повторы и параллельность

- **Повторный запуск.** Задачу берёт один worker (`FOR UPDATE SKIP LOCKED`); запуск возможен только из состояния `planned`.
- **Один сервер — одна задача.** Запуск отклоняется (409), если у сервера есть задача `queued` или `running`.
- **Повтор шага.** Шаги идемпотентны: запись тех же файлов, `compose up`, вход вместо повторной регистрации администратора, повторная регистрация ноды не создаёт вторую.
- **Устаревший план.** Подтверждение с другим `plan_sha256` отклоняется; при запуске план строится заново и сверяется с показанным.
- **Остановленный worker.** Задача без «пульса» 5 минут становится `failed` («Прервано»), а не запускается снова.
