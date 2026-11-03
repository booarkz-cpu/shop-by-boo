# Режимы установки Remnawave

Режим — это набор ролей на серверах реестра: `panel`, `node`, `subscription_page`. По ролям `backend/app/rw_plan.py` (`build_plan`) строит план из шагов закрытого списка ([DEPLOYMENT_AGENT](DEPLOYMENT_AGENT.md)). Как пользоваться — в [REMNAWAVE_INSTALLATION_WIZARD](REMNAWAVE_INSTALLATION_WIZARD.md).

## 1. Семь режимов

| Режим | Ключ | Серверы | Домены | Панель для нод |
| --- | --- | --- | --- | --- |
| Панель и нода на одном сервере | `panel_node` | 1 | панель | новая |
| Только панель | `panel` | 1 | панель | новая |
| Только нода | `node` | 1 | — | подключённая к магазину |
| Панель и страница подписки | `panel_subpage` | 1 | панель, подписка | новая |
| Только страница подписки | `subpage` | 1 | подписка | подключённая к магазину |
| Распределённая установка | `distributed` | панель + ноды на других серверах + страница подписки (по желанию) | панель, подписка | новая |
| Добавить ноду к панели | `add_node` | 1–20 | — | подключённая к магазину |

Проверки ввода (`PlanIn`, лишние поля — 422):
- режимы с новой панелью требуют сервер и домен панели;
- режимы без панели требуют, чтобы магазин уже был подключён к панели (`REMNAWAVE_URL` и `REMNAWAVE_TOKEN`);
- в распределённой установке нода ставится не на сервер панели;
- для Let's Encrypt нужен email;
- домены проверяются по шаблону имени хоста, значения в файлах не могут содержать управляющих символов.

## 2. Что ставится

| Роль | Каталог | Контейнеры | Порты |
| --- | --- | --- | --- |
| Панель | `/opt/remnawave` | `remnawave`, `remnawave-db` (PostgreSQL 18.4), `remnawave-redis` (Valkey 9, unix-сокет) | 3000, 3001, 6767 — только `127.0.0.1` |
| Страница подписки | `/opt/remnawave-subpage` | `remnawave-subscription-page` в сети `remnawave-network` | 3010 — только `127.0.0.1` |
| HTTPS | `/opt/remnawave-caddy` | `remnawave-caddy`, сеть хоста | 80, 443 |
| Нода | `/opt/remnanode` | `remnanode`, сеть хоста | `NODE_PORT` (2222 по умолчанию) |

Файлы строятся по официальным `docker-compose-prod.yml` и `.env.sample` проектов remnawave/backend, remnawave/node и remnawave/subscription-page. Образы закреплены по SHA-256 (`rw_plan.IMAGES`): панель 3.4.8, нода 3.4.4, страница подписки 8.0.1, PostgreSQL 18.4, Valkey 9.1.3, Caddy 2.11. Digest читает CI (`.github/workflows/resolve-image-digests.yml`), живой тест запускает именно эти образы.

Caddy ставится только на сервер Remnawave и только если порты 80 и 443 свободны или заняты прежней установкой мастера. Общий Caddy магазина (`deploy/Caddyfile`) и `sub_proxy` не меняются; второго прокси рядом с ними мастер не ставит.

## 3. Порядок шагов

1. Для каждого сервера: `preflight`, `install_docker`.
2. Панель: `write_files` → `compose_up` → `wait_panel` → `panel_bootstrap` (первый администратор и токен API).
3. Страница подписки: `write_files` → `compose_up`. На сервере панели она обращается к панели внутри `remnawave-network`, на другом сервере — по HTTPS домена панели.
4. Caddy на серверах панели и страницы подписки: `write_files` → `compose_up`.
5. Каждая нода: `write_files` (ключ ноды — `GET /api/keygen` панели) → `compose_up` → `firewall_node_port` (если выбрано) → `register_node`.
6. `verify`: панель отвечает через HTTPS (Caddy), при Let's Encrypt — ещё и с сервера магазина с проверкой сертификата; каждая нода подключилась к панели; страница подписки отвечает.

Нода на сервере панели регистрируется по адресу шлюза сети `remnawave-network`: панель в своей сети, нода — в сети хоста. Правило ufw для неё не нужно.

## 4. Проверено

| Режим | Mock-тест | На сервере |
| --- | --- | --- |
| Панель и нода | `test_panel_and_node_install_end_to_end` | CI: `tests/live/test_install_live.py` (внутренний сертификат) |
| Остальные шесть | `test_all_seven_modes_build_plans_of_the_closed_list`, `test_failed_step_rolls_back` (нода к панели магазина) | BLOCKED_EXTERNAL — нужны тестовые VPS и домены |
