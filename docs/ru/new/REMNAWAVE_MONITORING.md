# Мониторинг магазина и Remnawave

## Что есть

| Где | Что показывает |
| --- | --- |
| «Состояние системы» | backend, интерфейсы, база и миграции, Redis, Remnawave, ноды, Caddy и сертификаты, платежи, бот, фоновые задачи, копии, обновления |
| [Automation Center](AUTOMATION_CENTER.md) | автообновления магазина и Remnawave, релизы, версия панели, копии, worker, оповещения |
| «Ноды → Здоровье нод» | доступность нод через API панели, автоперезапуск, агенты на нодах, Xray |
| «Мониторинг → Журналы контейнеров» | хвост журнала любой службы магазина, секреты скрыты (v28.75.0) |
| «Сессии → История безопасности» | входы, неудачные попытки, подтверждения опасных действий (v28.75.0) |
| Prometheus и Grafana | `deploy/prometheus/`, `deploy/grafana/` — метрики `/metrics` (включаются в «Настройках без перезапуска», нужен `METRICS_TOKEN`) |

## Метрики `/metrics`

Метрики содержат только счётчики, без персональных данных.

| Метрика | Что |
| --- | --- |
| `vpnshop_requests_total`, `vpnshop_errors_total` | запросы и ошибки API |
| `vpnshop_jobs`, `vpnshop_payments`, `vpnshop_refunds`, `vpnshop_support_tickets` | записи по статусам |
| `vpnshop_oldest_queued_job_seconds`, `vpnshop_workers_online` | очередь и worker |
| `vpnshop_subscriptions_active` | активные подписки |
| `vpnshop_admin_login_failures_15m` | неудачные входы в админку за 15 минут (v28.75.0) |
| `vpnshop_admin_stepup_failures_1h` | неверные подтверждения опасных действий за час (v28.75.0) |
| `vpnshop_backup_last_success_age_seconds` | сколько секунд прошло с последней успешной копии, `-1` — копий нет (v28.75.0) |
| `vpnshop_nodes_down` | ноды, которые монитор видит недоступными (v28.75.0) |
| `vpnshop_rw_installations_failed_24h` | неудачные установки, обновления и модули мастера за сутки (v28.75.0) |
| `vpnshop_rw_ssh_key_rotation_due` | серверы с ключом владельца или ключом магазина старше 180 дней (v28.75.0) |

## Правила оповещений (`deploy/prometheus/vpnshop-alerts.yml`)

| Правило | Уровень | Когда |
| --- | --- | --- |
| `VpnShopUnavailable` | critical | метрики не отвечают 2 минуты |
| `VpnShopNoWorker` | critical | нет worker 3 минуты |
| `VpnShopQueueStalled` | warning | задача в очереди дольше 15 минут |
| `VpnShopApiErrors` | warning | ошибок больше 5 % |
| `VpnShopAdminBruteForce` | critical | 10 и больше неудачных входов за 15 минут |
| `VpnShopStepUpFailures` | warning | 5 и больше неверных подтверждений за час |
| `VpnShopBackupStale` | warning | нет успешной копии 36 часов |
| `VpnShopNodesDown` | critical | нода недоступна 5 минут |
| `VpnShopRemnawaveRunFailed` | warning | действие мастера не удалось и откатилось |
| `VpnShopSshKeyRotationDue` | info | пора сменить SSH-ключ сервера |

Правила проверяются в CI: задание «Docker Compose • configuration», `promtool check rules` и `promtool test rules` с файлом `vpnshop-alerts.test.yml`.

## Подключение

1. В «Настройках без перезапуска» включите «Prometheus-метрики» и задайте `METRICS_TOKEN` в `.env`.
2. Скопируйте `deploy/prometheus/prometheus.example.yml`, укажите домен API и токен в заголовке `X-Metrics-Token`.
3. Подключите `vpnshop-alerts.yml` и импортируйте дашборды из `deploy/grafana/`.

Мониторинг самих нод (CPU, RAM, трафик) — в панели Remnawave и в «Ноды → Здоровье нод». Отдельный сбор метрик с нод магазин не ставит.
