# Функции Remnawave

Заполнено на этапе 2 по исходникам `main` (`12834876`); проверка на живой панели — этап 9. Без живой панели статус не выше `IMPLEMENTED`. Версия Remnawave, под которую написан клиент, в репозитории не зафиксирована: ни `remnawave.py`, ни `remnawave-live.yml` её не задают. Это задача этапа 9. Подробности и источники — в [FEATURE_COMPARISON_MATRIX](FEATURE_COMPARISON_MATRIX.md).

| Функция | Версия Remnawave | Где в проекте | Статус | Проверка |
| --- | --- | --- | --- | --- |
| Panel + Node | не зафиксирована | Магазин подключается к готовой панели (`REMNAWAVE_URL`); установщика панели нет | NOT_STARTED | — |
| Panel Only | не зафиксирована | Как выше | NOT_STARTED | — |
| Node Only | не зафиксирована | `provisioner.py` + `POST /api/admin/provision-node`: Docker и `remnawave/node` по SSH | IMPLEMENTED | только проверка по тексту кода (`test_v312.py`) и прав доступа; поведенческого теста и живой проверки нет |
| Panel + Subscription Page | не зафиксирована | Своя страница не ставится; подписку отдаёт `sub_proxy.py` | NOT_STARTED | — |
| Subscription Page Only | не зафиксирована | `sub_proxy.py` (`/sub/{path}`) за общим блоком Caddy (`SUB_PROXY_DOMAINS`) | IMPLEMENTED | `test_subscription_middleware.py` (13) |
| Distributed Deployment | не зафиксирована | Ноды на разных серверах: `provisioner.py`, `node_autoscale.py` (Hetzner); резерв backend — `hot_standby.py` | IMPLEMENTED (частично) | `test_node_autoscale.py`; `hetzner-live.yml` требует токен |
| Add Node to Existing Panel | не зафиксирована | `provisioner.py`, `node_autoscale.py` (`api/keygen`, профиль конфигурации) | IMPLEMENTED (частично): без сертификатов, SelfSteal и DNS | как выше |
| SelfSteal | — | — | NOT_STARTED | — |
| Node Plugins | — | — (`plugins.py` — плагины магазина, не нод). Торренты считает `torrent_detection.py` по логу Xray | NOT_STARTED | — |
| Xray Core | не зафиксирована | Обновление образа ноды через агента: `POST /api/admin/nodes/update` (`node_health.py`); профили и инбаунды — `panel_admin.py` | IMPLEMENTED | `test_node_monitor.py`; живой проверки нет |
| WARP Native | — | — | NOT_STARTED | — |
| NetBird | — | — | NOT_STARTED | — |
| IPv6 | — | — (в `mobile_api.py` только `ipv6_protected: False`) | NOT_STARTED | — |
| Server Routing | — | — (`smart_routing` в `v3_api.py` — настройки клиента) | NOT_STARTED | — |
| Client Balancer | — | — | NOT_STARTED | — |
| Subscription Rules | — | — (`api/subscription-settings` встречается только в `panel_api_stats.py`) | NOT_STARTED | — |
| Xray Checker | — | Внешние пробы `block_monitor.py`; проверки хостов через Xray нет | IMPLEMENTED (частично) | `test_block_monitor.py` (4) |
| Хосты и Internal Squads | не зафиксирована | `panel_admin.py`, `remnawave.py`; UI `reconciliation.tsx` | IMPLEMENTED | `test_remnawave_squads.py` (2), `test_remnawave_contract.py` |
