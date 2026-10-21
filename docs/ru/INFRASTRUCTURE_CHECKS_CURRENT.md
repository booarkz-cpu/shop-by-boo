# Инфраструктурные проверки v28.5.0

Runtime/API — `21.5.1`; магазин — `0066_push_notifications`; Support Pro — `0006`. Выполняйте проверки в существующем compose-проекте `/opt/vpn-shop` и сначала на отдельном стенде. Сохраните результаты, время, коммит и обезличенные логи.

## Конфигурация и процессы

```bash
cd /opt/vpn-shop
docker compose config --quiet
docker compose ps
APP_DIR=/opt/vpn-shop bash scripts/doctor.sh
docker compose exec -T backend alembic current
docker compose logs --tail=100 backend worker bot support_pro support_worker
```

Ожидаются healthy/running-сервисы, успешные проверки API и HTTP админки, кабинета и Mini App; head магазина должен совпасть с указанным выше. Не публикуйте полный вывод `docker compose config`: он может содержать раскрытые секреты. В логах проверьте ошибки подключения БД, Redis, Remnawave и Telegram, циклические рестарты и failed-задания.

## Live-конфигурация

В панели откройте **Обслуживание → Настройки без перезапуска**. Ожидаются счётчики `96 live`, `53 deployment`, `2 workflow`, текущая версия и история. На стенде измените безопасный параметр, укажите причину, выполните stage/apply, затем убедитесь, что API, worker и bot приняли версию не позднее 5 секунд. Выполните rollback последней версии. Проверьте, что введённый тестовый секрет отсутствует в ответе каталога, audit и логах. Полный порядок: [RUNTIME_SETTINGS_CURRENT.md](RUNTIME_SETTINGS_CURRENT.md).

## БД, Redis, место и привилегии

```bash
docker compose exec -T db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose exec -T support_db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose exec -T redis sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli ping'
docker compose exec -T support_redis sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli ping'
docker compose exec -T backend id -u
df -h /opt/vpn-shop
docker stats --no-stream
```

Ожидаются `accepting connections`, `PONG`, ненулевой UID backend и достаточное место для backup плюс нового архива. Пароль Redis берётся из окружения контейнера и не печатается. Проверьте отсутствие открытых внешних портов БД/Redis по правилам firewall и конфигурации Compose; доступны должны быть только запланированные точки входа.

## HTTPS, вход и Remnawave

Проверьте собственные домены API, панели, кабинета и поддержки из внешней сети. Сертификаты должны быть действительны; защищённые страницы требуют вход. Через панель проверьте роли, 2FA/passkey, статус worker и страницу узлов Remnawave. API мониторинга `/api/admin/remnawave/monitoring` требует административную авторизацию: не передавайте cookie или bearer token в публичные команды/логи.

На тестовой подписке проверьте создание доступа, URL/QR, подключение реального VPN-клиента и трафик. Затем отдельно убедитесь, что истечение или блокировка прекращают доступ. Успешный HTTP health Remnawave не подтверждает VPN-подключение клиента.

## Alerts и восстановление

Настройте `BOT_TOKEN` и `ALERT_TELEGRAM_CHAT_ID` в приватном `.env`. Проверьте доступ бота к нужному чату. Отправку Prometheus alerts обеспечивает отдельно настроенный Alertmanager: [регламент мониторинга](OPERATIONS_MONITORING.md).

На изолированном стенде остановите тестовый worker, дождитесь порога alert, запишите уведомление и восстановите worker. Проверьте восстановление heartbeat и закрытие alert. Отключение узла Remnawave проверяйте только на тестовом узле; зафиксируйте обнаружение отказа и восстановление. Не выполняйте отключение рабочих узлов ради проверки.

Сделайте зашифрованный backup обеих БД, файлов и конфигураций и выполните restore drill в новом изолированном окружении: [BACKUP_CURRENT.md](BACKUP_CURRENT.md). Наличие файла backup без успешного восстановления не закрывает проверку.

## Критерии результата

| Область | Доказательство |
| --- | --- |
| Запуск | Healthy-сервисы, doctor и совпадающие миграции |
| Авторизация | Успешный вход, отказ роли без права, работа 2FA/passkey |
| VPN | Подключение тестового клиента, трафик, прекращение доступа |
| Мониторинг | Heartbeat, обнаруженный тестовый отказ, alert и восстановление |
| Backup | Восстановленные БД и файлы на отдельном стенде |
| Платежи | Отдельный разрешённый provider E2E: сверка суммы/валюты, повтор webhook, одна выдача доступа |

Зелёный CI подтверждает проверки репозитория. Проверки инфраструктуры подтверждают конкретный сервер; ни одна из них сама по себе не разрешает реальные платежи. Границы незавершённых функций: [WORKSPACE_COVERAGE.md](WORKSPACE_COVERAGE.md).
