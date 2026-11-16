# Наблюдаемость магазина

Сверено 16 ноября 2026 года по коду main `4a7cb78d` и изменениям этого PR.
Документ закрывает описание REQ-DOC-0028: какие сигналы существуют, откуда они
получаются и где заканчиваются их доказательства. Рабочий VPS, доставка оповещений
реальным получателям и подключение физических телефонов здесь не проверялись.
Порог оповещения не является измеренным SLA/SLO.

## Источники и границы

| Сигнал | Реализация | Что показывает |
|---|---|---|
| Жизнеспособность и готовность | [main.py](../services/backend/app/main.py) | Процесс API; отдельно соединение с PostgreSQL и Redis |
| HTTP-счётчики и `/metrics` | [main.py](../services/backend/app/main.py) | Запросы и ошибки текущего процесса, снимок состояния БД |
| Операционные показатели | [observability.py](../services/backend/app/observability.py) | Очередь, оплаты, возвраты, обращения, heartbeat воркеров, подписки |
| Ресурсы и задержки | [host_metrics.py](../services/backend/app/host_metrics.py) | Последние 5000 HTTP-запросов; видимые процессу диск, память, нагрузка и пул БД |
| Дополнительные метрики платформы | [platform_api.py](../services/backend/app/platform_api.py) | Агенты, нарушения и ошибки исходящих webhook при включённом плагине metrics |
| Оповещения оператора | [ops_alerts.py](../services/backend/app/ops_alerts.py) | Проблемы выдачи, касс, процессов, резервирования, сертификатов и часов |
| Журнал ошибок | [error_log.py](../services/backend/app/error_log.py) | Сгруппированные ERROR/CRITICAL в БД с количеством повторов |
| JSON-журналы | [log_format.py](../services/backend/app/log_format.py) | Время UTC, уровень, logger, сообщение, request_id и исключение |

Эта схема описывает магазин. `/metrics` магазина не доказывает, что VPN-туннель
покупателя работает, и не заменяет диагностику ноды, MASQUE или физического клиента.
Здоровье Support Pro не входит в `/health` магазина: это отдельные службы
`support_pro`, `support_worker`, `support_db`, `support_redis` в
[docker-compose.yml](../docker-compose.yml).

## Проверки живости и готовности

| Маршрут | Поведение | Ограничение |
|---|---|---|
| `GET /health/live` | Возвращает `ok=true` и версию процесса | Не обращается к БД, Redis, кассам и Remnawave |
| `GET /health` | Проверяет Redis ping и PostgreSQL `SELECT 1`, возвращает поля `ok`, `redis`, `database`, `worker_role`, `version` | При отказе зависимостей нужно читать `ok`; маршрут сам не превращает такой результат в HTTP 503 |
| `GET /health/ready` | Использует ту же проверку; при `ok=false` отвечает HTTP 503 | Готовность касс, выдачи и VPN этим не доказана |
| `GET /api/admin/ops/readiness` | Проверяет настройку компонентов запуска, тарифов, резервирования, получателей | Требует административного права `ops.diagnostics`; это отдельная проверка, а не замена healthcheck |

В основном Compose healthcheck backend обращается к `/health` и проверяет только
успех HTTP-запроса. Поэтому статус Docker «healthy» сам по себе не доказывает
`ok=true`. Активная проверка reverse proxy использует `/health/live`
([Caddyfile](../infrastructure/reverse-proxy/Caddyfile)). Для внешней проверки
зависимостей следует использовать `/health/ready` и разбирать сигналы `/metrics`.
Проверка готовности запуска использует собственные условия, в том числе давность
копии за сутки; её зелёный результат отдельно не доказывает соблюдение RPO 1 час.

## Получение метрик

Настройки находятся в [.env.example](../.env.example) и
[config.py](../services/backend/app/config.py):

| Настройка | Значение по умолчанию | Поведение |
|---|---|---|
| `METRICS_ENABLED` | `true` | При выключении `/metrics` отвечает HTTP 404 |
| `METRICS_TOKEN` | Пусто | Без настроенного токена HTTP 503; при неверном/отсутствующем `X-Metrics-Token` HTTP 401 |
| `LOG_LEVEL` | `INFO` | Уровень журналирования приложения |
| `LOG_FORMAT` | `text` | `json` включает JSON-формат для настроенных обработчиков Python logging |

Токен сравнивается через `hmac.compare_digest`. Его не надо включать в URL,
Git, публичный dashboard или скриншот. Пример Prometheus уже читает значение
заголовка из файла: [prometheus.example.yml](../infrastructure/monitoring/prometheus/prometheus.example.yml).
Нужно заменить `api.example.com:443` своим API-доменом и создать доступный только
Prometheus файл `/etc/prometheus/secrets/vpnshop-metrics-token` с фактическим
значением токена. Это пример внешнего Prometheus, а не автоматически запущенный
компонент основного Compose.

В примере scrape и evaluation выполняются каждые 30 секунд, scrape timeout —
10 секунд. Сервер ограничивает получение дополнительных метрик платформы и
снимка БД отдельными тайм-аутами по 3 секунды. При сбое БД отдаётся
`vpnshop_database_metrics_available 0`, а не выдуманные нулевые значения всех
таблиц. Сбой дополнительного плагина платформы приводит к отсутствию его строк;
он не получает отдельного индикатора доступности.

### Каталог и смысл показателей

| Имена | Источник и трактовка |
|---|---|
| `vpnshop_requests_total`, `vpnshop_errors_total` | Счётчики текущего процесса; ошибки — HTTP 5xx или исключение middleware |
| `vpnshop_payment_fulfillment_total`, `vpnshop_payment_fulfillment_failures`, `vpnshop_backup_total`, `vpnshop_backup_failures` | Счётчики `_METRICS` процесса; не являются долговечным финансовым реестром |
| `vpnshop_jobs`, `vpnshop_payments`, `vpnshop_refunds`, `vpnshop_support_tickets` | Снимки количества записей БД по фиксированному набору status; неизвестные статусы суммируются в `other` |
| `vpnshop_oldest_queued_job_seconds` | Возраст самой старой queued-задачи с учётом времени ожидания retry/backoff |
| `vpnshop_workers_online` | Количество online-записей WorkerState с heartbeat не старше 90 секунд |
| `vpnshop_subscriptions_active` | Локальные active/cancel_scheduled/grace с неистёкшим или отсутствующим expires_at; не проверка туннеля |
| `vpnshop_database_metrics_available` | Удалось ли прочитать операционные метрики БД в этом scrape |
| `vpnshop_http_request_seconds{quantile="0.5\|0.95\|0.99"}` | Выборочные квантили последних 5000 запросов текущего процесса; это gauge, не histogram |
| `vpnshop_http_requests_sampled` | Размер текущего окна задержек; до первого запроса квантили могут отсутствовать |
| `vpnshop_disk_free_bytes`, `vpnshop_disk_total_bytes` | Файловые системы `/` и media, метки mount=root/media; при общем разделе значения могут совпадать |
| `vpnshop_memory_available_bytes`, `vpnshop_memory_total_bytes`, `vpnshop_load1`, `vpnshop_cpu_count`, `vpnshop_process_resident_bytes` | Видимые процессу Linux /proc, os.getloadavg, os.cpu_count и RSS; не гарантируют учёт лимита контейнера как отдельного VPS |
| `vpnshop_db_pool_size`, `vpnshop_db_pool_checked_out` | SQLAlchemy pool; при отсутствии такого API вместо значений выдаётся комментарий |
| `vpnshop_admin_login_failures_15m`, `vpnshop_admin_stepup_failures_1h` | Количество соответствующих действий AuditLog за окно времени |
| `vpnshop_backup_last_success_age_seconds` | Возраст created_at последней копии со статусом completed; `-1`, если такой копии нет |
| `vpnshop_rw_ssh_key_rotation_due`, `vpnshop_rw_installations_failed_24h`, `vpnshop_nodes_down` | Серверы с требующей внимания SSH-ротацией, неуспешные установки за сутки, down-состояния монитора нод |
| `vpnshop_abuse_open`, `vpnshop_agents_online`, `vpnshop_webhook_failures` | Дополнительный плагин metrics; онлайн-агенты имеют last_seen_at за последние 5 минут |

HTTP-счётчики обнуляются после рестарта. При нескольких API-репликах опрашивать
их следует как отдельные targets: scrape балансируемого адреса может чередовать
несвязанные счётчики. БД-gauges читают общую БД, поэтому их нельзя бездумно
суммировать по API-репликам. Квантили разных процессов нельзя складывать или
усреднять как общую p95. Встроенные операционные метрики не используют email,
ключи подписок, тексты обращений или идентификаторы клиентов как labels;
журналы и сообщения оператору имеют другую модель данных и доступа.

## Dashboards и Prometheus-оповещения

Импортируемые JSON: [операции](../infrastructure/monitoring/grafana/vpnshop-operations.json)
и [платформа](../infrastructure/monitoring/grafana/vpnshop-platform.json).
Datasource выбирается при импорте; фильтр job должен совпадать с job_name scrape.
Доставка из Prometheus в Alertmanager/почту/Telegram требует отдельной настройки:
в основном Compose нет автоматически развёрнутого Prometheus/Grafana/Alertmanager.

[vpnshop-alerts.yml](../infrastructure/monitoring/prometheus/vpnshop-alerts.yml)
содержит следующие технические пороги:

| Правило | Условие | `for` |
|---|---|---|
| VpnShopUnavailable | `up == 0` | 2 минуты |
| VpnShopDatabaseMetricsUnavailable | database_metrics_available=0 | 2 минуты |
| VpnShopNoWorker | workers_online=0 | 3 минуты |
| VpnShopQueueStalled | oldest_queued_job_seconds>900 | 5 минут |
| VpnShopApiErrors | Отношение rate ошибок к rate запросов >5%, с защитой знаменателя | 5 минут |
| VpnShopAdminBruteForce | ≥10 ошибок входа за 15 минут | 1 минута |
| VpnShopStepUpFailures | ≥5 ошибок подтверждения за час | 1 минута |
| VpnShopBackupStale | Нет completed-копии или возраст >4800 секунд | 5 минут |
| VpnShopNodesDown | nodes_down>0 | 5 минут |
| VpnShopRemnawaveRunFailed | Есть неуспешная установка за сутки | 1 минута |
| VpnShopSshKeyRotationDue | Есть сервер с требующей внимания ротацией | 1 час |

Порог резервирования согласован в этом PR с решением владельца №8: RPO 1 час
плюс существующий `ops_alerts.RPO_GRACE` 20 минут. Раньше Prometheus ждал
36 часов. Дополнительные 5 минут `for` и частота scrape/evaluation влияют на
момент появления тревоги; порог не обещает восстановление за это время.
Если метрики вообще недоступны, действует правило up, а не сравнение возраста
несуществующего ряда. RTO 4 часа — цель владельца, а не результат замера VPS.

## Встроенные сообщения оператору

`ops_alert_scheduler` ждёт 60 секунд при старте и затем проверяет проблемы раз
в 300 секунд, если есть получатель. Он подключается через
`main.start_backup_scheduler` при `WORKER_ROLE != api`. Выделенный
`services/backend/worker.py` сам этот цикл не запускает: при изменении роли API
нужно отдельно убедиться, что планировщик действительно работает. По умолчанию
config/.env.example задают роль worker; наличие отдельного контейнера worker
само по себе не доказывает работу именно этого планировщика.

Получатель Telegram — `ALERT_TELEGRAM_CHAT_ID`, иначе `ADMIN_TELEGRAM_ID`;
нужен `BOT_TOKEN`. Для почты нужны `ALERT_EMAIL` и SMTP-настройки.
Состояние отправленных проблем хранится в AppSetting с префиксом `ops_alert:`;
повтор действующей проблемы — не чаще раза в 6 часов. Неудачная первичная
отправка повторяется на следующем tick. Если хотя бы один канал принял сообщение,
проблема считается отправленной для общего состояния; независимого retry
второго канала нет. При исчезновении проблемы отправляется «Решено» и запись
удаляется даже при отказе отправки этого сообщения. Это best-effort доставка,
а не гарантия уведомления или механизм блокировки опасной операции.

Проверяются в том числе оплаченные за последние сутки заказы без доступа,
выдача, зависшая больше 15 минут, открытый circuit breaker кассы, heartbeat
процесса старше 3 минут (для записей последнего дня, не stopped), три неудачных
мониторинговых проверки подряд, последняя неуспешная копия/проверка восстановления,
недоступность Remnawave, RPO, отрицательные балансы и сигналы модулей сети/резерва.
Конкретные лимиты и перечень определяет collect(), а не Prometheus-таблица выше.

В production сертификаты доменов проверяются не чаще раза в 6 часов:
менее 14 дней — medium, менее 3 — critical. Невозможность прочитать сертификат
возвращает неизвестное состояние и не создаёт cert-проблему. Часы сравниваются
с HTTPS Date api.github.com: отклонение от 60 секунд вызывает проблему; сбой
получения даты не доказывает, что часы точны. Еженедельная сводка — в понедельник
с 09:00 МСК, один раз за ISO-неделю после успешной отправки.

Административные маршруты с правом `ops.diagnostics`:
`GET /api/admin/ops/alerts`, `POST /api/admin/ops/alerts/test`,
`GET /api/admin/ops/summary`, `POST /api/admin/ops/summary/send`.
POST test/send действительно отправляют сообщения; в этой сверке они не вызывались.

## Журналы, request_id и доступ

`LOG_FORMAT=json` меняет формат существующих обработчиков root/uvicorn:
time в UTC, level, logger, message, request_id, exception при наличии.
Значение X-Request-ID принимается только при соответствии
`[A-Za-z0-9._:-]{8,64}`, иначе создаётся UUID; идентификатор возвращается в
заголовке ответа. Вне HTTP-контекста formatter использует system. Это корреляция
журналов запроса, а не распределённые spans или автоматически установленный
OpenTelemetry collector.

DatabaseHandler получает ERROR и выше, складывает записи в очередь до 5000,
пишет пачками до 200 после ожидания 2 секунды и группирует по fingerprint.
Записи с last_seen старше 30 дней удаляются при обработке очередной пачки;
это не отдельный точный таймер удаления. При недоступной БД остаётся stderr-сигнал
об ошибке записи; очередь не является долговечным хранилищем и теряется при
рестарте. При переполнении/ошибке обработчика сохранение также не гарантировано.
SQLAlchemy и собственный logger записи ошибок исключены из этой очереди.

Маршруты `/api/admin/errors`, `/api/admin/errors/{error_id}/resolve` и
`/api/admin/errors/resolve-all` требуют `ops.diagnostics`. Разрешение ошибки —
пометка resolved, не удаление причины; новый повтор снова открывает её.
Отдельного request_id-поля в сохраняемой записи DatabaseHandler нет.

На базовом main этой сверки error_log применяет шаблонное redact к сообщениям
и traceback; это не доказательство, что любой секрет или персональные данные
никогда не попадут в журнал. PR #355 отдельно усиливает маскирование logging;
после его слияния этот раздел нужно пересверить. REQ-SEC-0012 остаётся PARTIAL.
Нельзя публиковать необработанные журналы с ключами, токенами и данными покупателей.
Docker-ротация stdout в основном Compose явно не задаётся: её хранение определяется
настройками Docker/системы оператора, а не 30-дневным сроком таблицы ошибок.

## Диагностика без изменения данных

Из корня установленного проекта доступны чтение статусов и ограниченного хвоста:

```bash
docker compose ps
docker compose logs --since 15m --tail 200 backend worker
docker compose logs --since 15m --tail 100 support_pro support_worker
```

Для HTTP-ошибки сохранить время UTC, метод/маршрут без секретных параметров,
HTTP-статус и X-Request-ID; сопоставить их с JSON-журналом backend и изменением
счётчиков. Для очереди проверить workers_online, oldest_queued_job_seconds и
журнал worker; для копий — возраст completed-копии и статус последней проверки
восстановления. Не повторять оплату/возврат ради диагностики и не считать
отсутствие сообщения подтверждением исправности.

## Доказательства и оставшаяся проверка

| Поверхность | Доказательство в репозитории |
|---|---|
| Ограниченные labels, ошибки БД, авторизация metrics | [test_observability.py](../tests/test_observability.py) |
| Квантили, ASGI middleware, ресурсы | [test_host_metrics.py](../tests/test_host_metrics.py) |
| Сбор проблем, повтор, неуспешная отправка, RPO, сертификаты, JSON request_id | [test_ops_alerts.py](../tests/test_ops_alerts.py) |
| Prometheus-условия, ожидание и сброс тревоги | [vpnshop-alerts.test.yml](../infrastructure/monitoring/prometheus/vpnshop-alerts.test.yml) |
| Исполнение promtool | Задание Compose в [ci.yml](../.github/workflows/ci.yml): check rules и test rules в prom/prometheus:v3.5.0 |

Документ сверяет исходники; наличие теста не означает, что он был запущен в этой
сверке. Для изменённых Prometheus-правил требуется новый успешный promtool в CI.
На VPS ещё нужны внешний scrape с токеном, доступ к нужным репликам, доставка
оповещений, реальные heartbeat/резервные копии и измерения задержек/ресурсов.
Из них затем строятся SLO_BASELINE и PERFORMANCE_BASELINE с фактическими числами.
Смежные инструкции: [мониторинг](ru/OPERATIONS_MONITORING.md),
[восстановление](ru/DISASTER_RECOVERY.md),
[реагирование на инциденты](ru/new/INCIDENT_RESPONSE.md).
