> Актуальный дистрибутив: `v28.37.0`; runtime/API: `21.5.1`. Точные границы готовности указаны в текущей матрице покрытия.

# Операционный мониторинг магазина

В текущем ядре доступны агрегаты состояния БД, готовый dashboard и правила alerting. Метрики не содержат имён клиентов, email, IP, ID платежей, ключей, ошибок провайдеров или payload задач.

## Подключение Prometheus

1. Задайте `METRICS_ENABLED=true` и случайный `METRICS_TOKEN` в серверном `.env`, перезапустите backend. `/metrics` возвращает `404` при отключении, `503` без токена, `401` при неверном `X-Metrics-Token`.
2. Скопируйте [пример конфигурации](../../deploy/prometheus/prometheus.example.yml), замените `api.example.com:443` своим HTTPS API. Сохраните токен в отдельный приватный файл `/etc/prometheus/secrets/vpnshop-metrics-token`, доступный только процессу Prometheus. Значение должно совпадать с backend; не добавляйте его в Git и не передавайте как аргумент командной строки.
3. Поместите рядом [правила](../../deploy/prometheus/vpnshop-alerts.yml), проверьте `promtool check config /etc/prometheus/prometheus.yml` и `promtool check rules /etc/prometheus/vpnshop-alerts.yml`. Используйте Prometheus с поддержкой `http_headers.files`; TLS verification остаётся включённой.
4. Настройте собственный Alertmanager и получателей. Сам файл правил не отправляет уведомления без интеграции Alertmanager. В примере scrape каждые 30 секунд, timeout 10 секунд.
5. Убедитесь, что `up{job="vpnshop"}=1`, `vpnshop_database_metrics_available=1`, worker heartbeat присутствует. Поочерёдно остановите тестовый worker и тестовый API на отдельном стенде, проверьте переход alerts из pending в firing и восстановление.

Формат custom headers описан в [документации Prometheus](https://prometheus.io/docs/prometheus/latest/configuration/configuration/). Prometheus/Grafana не добавляются автоматически в основной Compose: оператор подключает существующий стек мониторинга либо устанавливает свой отдельно.

## Grafana

Импортируйте [vpnshop-operations.json](../../deploy/grafana/vpnshop-operations.json), выберите Prometheus datasource и scrape job `vpnshop`. Dashboard содержит 14 панелей: доступность API/БД, worker, RPS, доля 5xx, возраст очереди, статусы задач/платежей/возвратов/обращений, локальные подписки, нарушения, агенты и исходящие webhook. Старый [platform dashboard](../../deploy/grafana/vpnshop-platform.json) сохранён.

Распределённые API реплики читают общую БД: gauges нужно агрегировать `max`, а не суммировать. Dashboard делает это явно; процессные counters запросов/ошибок агрегируются через `sum(rate(...))`. Последние три панели требуют включённого существующего plugin `metrics`; отсутствие этих рядов означает отсутствие данных, а не нулевые нарушения. Для внешней PostgreSQL/Redis/Remnawave инфраструктуры подключите соответствующие exporters: эти показатели не выдумываются из локального состояния магазина.

## Метрики и границы

| Метрика | Значение |
| --- | --- |
| `vpnshop_jobs{status}` | Текущие строки очереди, включая завершённые и failed |
| `vpnshop_payments{status}` | Текущие статусы платежей; это gauge, не оборот и не счётчик операций |
| `vpnshop_refunds{status}` | Текущие состояния возвратов |
| `vpnshop_support_tickets{status}` | Текущие состояния обращений |
| `vpnshop_oldest_queued_job_seconds` | Возраст старейшей queued задачи, включая retry backoff |
| `vpnshop_workers_online` | Worker со статусом online и heartbeat не старше 90 секунд |
| `vpnshop_subscriptions_active` | Локальные неистёкшие active/cancel_scheduled/grace подписки; это не VPN probe |
| `vpnshop_database_metrics_available` | `1` после успешного снимка БД, `0` после ошибки/timeout |

Статусы ограничены фиксированным списком и `other`; произвольный текст из БД не становится label. Отсутствующие статусы дают `0`. При отказе БД её gauges отсутствуют и отдельный availability gauge равен `0`: сбой не маскируется нулём платежей/задач. Снимок БД ограничен тремя секундами. Counts отражают отдельные запросы снимка, не транзакционно одновременный бизнес-отчёт.

Alerts: недоступность scrape 2 минуты, отказ метрик БД 2 минуты, отсутствие worker 3 минуты, queued задача старше 15 минут в течение 5 минут, доля 5xx выше 5% в течение 5 минут. Подстройте пороги под нагрузку и retry policy. Исторические failed задачи сохраняются, поэтому на их ненулевое число по умолчанию alert не создан.

Правила имеют [тесты срабатывания](../../deploy/prometheus/vpnshop-alerts.test.yml): `promtool test rules deploy/prometheus/vpnshop-alerts.test.yml`. Конфигурация, правила и все запросы dashboard проверены promtool 3.15.0.
