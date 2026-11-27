# PostgreSQL и Redis

PostgreSQL 19 хранит платежи, подписки, задания и настройки. Redis 8.10 хранит блокировки, кеши, лимиты, состояния диалогов и одноразовые билеты. Очистка Redis сбрасывает ещё действующие блокировки и пользовательские состояния. Точные версии и SHA-256 образов приведены в [реестре зависимостей](../EXTERNAL_DEPENDENCIES.md).

## PostgreSQL

| Что | Как |
| --- | --- |
| Доступ | SQLAlchemy 2 async + asyncpg (`services/backend/app/db.py`, `pool_pre_ping`) |
| Схема | Alembic, текущая голова — в `scripts/build-release.sh` и `release-manifest.template.json`; миграции совместимы назад (см. [zero_downtime.md](zero_downtime.md)) |
| Очередь заданий | Таблица `jobs`: выдача подписок, пробный период, бонусные дни, рассылки. Worker берёт задание `SELECT … FOR UPDATE SKIP LOCKED`, поэтому несколько worker-процессов делят очередь без двойного выполнения; у каждого свой `worker_identity()` (роль:хост:pid) |
| Идемпотентность | Уникальные `order_id`, `idempotency_key`, `jobs.job_key`, события провайдеров (`register_provider_event`) |
| Настройки из админки | Таблица `app_settings` (JSON): мониторинг нод, анти-шеринг, бонусные дни, копии в Telegram, ИИ-поддержка, резервные адреса |
| Секреты в базе | Шифруются AES-GCM (`security.encrypt_secret`): токены автоплатежей, ключ подписи списка зеркал, токен GitHub Gist |

## Redis

| Ключ | Назначение | Время жизни |
| --- | --- | --- |
| `corgi_fsm:*` | Состояние диалогов Telegram-бота (aiogram `RedisStorage`): переживает перезапуск бота | 24 ч |
| `nodes:status:v1` | Кеш состояния нод Remnawave для кабинета, приложений и мониторинга | 30 с |
| `lock:payment-create:*`, `lock:checkout-intent:*`, `lock:fulfill:*`, `lock:auto-renew:*` | Распределённые блокировки денежных операций (токен + продление аренды) | 60–900 с |
| `lock:node-monitor`, `lock:anti-sharing`, `lock:telegram-backup`, `lock:mobile-mirrors`, `lock:backup`, `lock:maintenance` | Один экземпляр фоновой задачи на весь кластер | до цикла задачи |
| `rl:<ip>:<путь>` | Ограничение частоты запросов (`RATE_LIMITS` в `main.py`, окно 60 с) | 60 с |
| `sync:user:<id>` (pub/sub) | Изменение аккаунта клиента: будит ожидающие `/api/me/sync` во всех процессах | — |
| `admin-web-ticket:<sha256>` | Одноразовый билет «Вся панель» из мобильной админки (хранится только хеш) | 60 с |

Без Redis магазин не принимает платежи (блокировки обязательны) — это сделано намеренно: лучше отказать в
оплате, чем рискнуть двойным списанием. Бот без Redis работает с памятью процесса.

## Копия Redis перед сменой образа

В стандартной установке `redis` обслуживает магазин, а `support_redis` обслуживает Support Pro. У них отдельные пароли и тома `redis_data` и `support_redis_data`. Оба сервиса запускаются с AOF. В полном архиве магазина `.vpb` находятся базы PostgreSQL, окружение и файлы. Для отката состояния Redis сохраните оба тома отдельно. [Состав полной копии](../ru/BACKUP_CURRENT.md) · [Закреплённые образы](../EXTERNAL_DEPENDENCIES.md).

1. Запланируйте окно обслуживания. Сохраните предыдущие файлы Compose, окружение и закрепления образов. В каталоге установки зафиксируйте работавшие сервисы командой `docker compose ps --services --filter status=running`. Приостановите приём новых запросов и штатно остановите сервисы через `docker compose stop`. Дождитесь завершения записи.
2. Создайте копии в защищённом каталоге на зашифрованном диске. Следующий пример предназначен для стандартного проекта с обоими сервисами. В автономной установке Support Pro выполните его из собственного каталога Compose с переменной `export REDIS_STANDALONE_SUPPORT=1`. Она выбирает единственный сервис `redis` при создании копии и восстановлении. Укажите каталог с достаточным свободным местом.

```bash
set -eu
umask 077
backup=$(mktemp -d "${REDIS_BACKUP_DIR:-/var/backups}/redis-rollback.XXXXXXXX")
services="redis support_redis"
if [ "${REDIS_STANDALONE_SUPPORT:-0}" = 1 ]; then services=redis; fi
for service in $services; do
  cid=$(docker compose ps -aq "$service")
  test -n "$cid" && test "$(docker inspect -f '{{.State.Status}}' "$cid")" = exited || exit 1
  volume=$(docker inspect -f '{{range .Mounts}}{{if and (eq .Type "volume") (eq .Destination "/data")}}{{.Name}}{{end}}{{end}}' "$cid")
  test -n "$volume"
  image=$(docker inspect -f '{{.Image}}' "$cid")
  printf '%s\n' "$image" > "$backup/$service.image"
  docker image inspect -f '{{json .RepoDigests}}' "$image" > "$backup/$service.digests.json"
  docker run --rm --pull=never --network none --mount "type=volume,src=$volume,dst=/source,readonly" \
    --entrypoint tar "$image" -C /source -cf - . > "$backup/$service.tar.part"
  tar -tf "$backup/$service.tar.part" > /dev/null
  mv "$backup/$service.tar.part" "$backup/$service.tar"
done
(
  cd "$backup"
  for service in $services; do
    sha256sum -- "$service.tar" "$service.image" "$service.digests.json"
  done > SHA256SUMS
)
printf 'Каталог копии: %s\n' "$backup"
```

Сохраните каталог с контрольными суммами вне исходного хоста. Неполный каталог без `SHA256SUMS` требует повторного снятия копии. При отмене обновления запустите прежний состав сервисов исходного проекта.

## Проверка отката Redis

На изолированном хосте той же архитектуры подготовьте прежнюю версию Compose, образы и пароли. Загрузите образы по сохранённым RepoDigests. ID локального образа должен совпасть с записью `.image`. Перейдите в каталог сохранённой копии и восстановите каждый архив в новый пустой том.

```bash
set -eu
umask 077
services="redis support_redis"
if [ "${REDIS_STANDALONE_SUPPORT:-0}" = 1 ]; then services=redis; fi
for service in $services; do
  test -s "$service.tar" && test -s "$service.image" && test -s "$service.digests.json" || exit 1
done
for service in $services; do
  sha256sum -- "$service.tar" "$service.image" "$service.digests.json"
done | cmp - SHA256SUMS
for service in $services; do
  image=$(cat "$service.image")
  docker image inspect "$image" > /dev/null
  volume=$(docker volume create --label "corgi.redis.rollback=${REDIS_RESTORE_ID:-manual}")
  docker run --rm --pull=never --network none -i --mount "type=volume,src=$volume,dst=/target" \
    --entrypoint tar "$image" -C /target -xpf - < "$service.tar"
  printf '%s %s\n' "$service" "$volume"
done
```

В отдельном проекте Compose задайте выведенные имена томов через `volumes.redis_data.name` и `volumes.support_redis_data.name`, для обоих укажите `external: true`. Оставьте прежние закрепления образов сервисов. В этом проекте выполните `docker compose up -d --no-deps --wait redis support_redis`. Проверьте оба healthcheck, ожидаемые очереди и ключи контрольной операции. При сверке TTL учитывайте время, прошедшее с момента копии. До окончания проверки держите workers, бота и внешние вебхуки остановленными. Исходные тома и архивы сохраняются для повторного восстановления. [Сценарий CI](../../scripts/ci/redis-volume-rollback.py) выполняет команды этого руководства на отдельных тестовых томах магазина и Support Pro.

## Синхронизация клиентов

`GET /api/me/sync` строит состояние аккаунта из PostgreSQL (подписки, баланс, ожидающие платежи) и из
`nodes:status:v1` (серверы) и отдаёт его с версией — хешем данных. Подробно — [account_sync.md](account_sync.md).
