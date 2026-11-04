# Docker

Магазин работает одним `docker-compose.yml`. Образы баз, Redis и Caddy закреплены по digest (`.env.images`, `scripts/pin-images.sh`). Свои образы собираются из исходников выпуска (`deploy/build-production.sh`).

## Службы

| Служба | Назначение | Health check | Порты наружу |
| --- | --- | --- | --- |
| `caddy` | обратный прокси, TLS (Let's Encrypt), HTTP/3 | да | 80, 443, 443/udp |
| `backend` | API (FastAPI), миграции при старте | `/health/ready` | — |
| `worker` | фоновые задачи и расписания: копии, сверка, автопродление, мастер Remnawave, автообновление Remnawave | heartbeat | — |
| `bot` | Telegram-бот | да | — |
| `admin`, `cabinet`, `miniapp` | статические интерфейсы | HTTP 200 | — |
| `db` | PostgreSQL 18 | `pg_isready` | — |
| `redis` | Redis 8 | `redis-cli ping` | — |
| `support_pro`, `support_worker`, `support_db`, `support_redis` | служба поддержки | да | — |
| `mail_receiver` | приём почты (по желанию) | да | 25 |
| `volume_init`, `support_migrate` | однократная подготовка томов и миграции поддержки | — (завершаются) | — |
| `backend_standby` | профиль `standby`, обновление без простоя | — | — |

Все долгоживущие службы — `restart: unless-stopped`. Сеть `ingress` внутренняя: базы, Redis и API наружу не видны.

## Данные

| Том | Что хранит |
| --- | --- |
| `postgres18_data`, `support_postgres18_data` | базы магазина и поддержки |
| `redis_data`, `support_redis_data` | кэш и очереди |
| `backup_data` | резервные копии магазина и зашифрованные копии базы панели Remnawave (`remnawave/`) |
| `media_data`, `app_packages` | загруженные файлы, сборки приложений |
| `caddy_data`, `caddy_config` | сертификаты и настройки Caddy |
| `./.control` (каталог на хосте) | запросы и состояние агента автообновления |

`docker compose down` тома не удаляет. **Никогда не запускайте `down -v` на рабочем сервере:** эта команда удаляет тома вместе с базами.

## Переменные окружения

Значения, которые читаются при запуске контейнеров, хранятся в `.env`: домены магазина, подключение к базе и Redis, `APP_SECRET`. Остальное — ключи касс, Remnawave, почта, Cloudflare, `BOT_TOKEN` — меняется в «Настройках без перезапуска». Образец — `.env.example`.

## Обновление и откат

`scripts/update.sh` выполняет такие шаги:
1. снимок файлов в `.rollback/` (без `.env` и `.control`);
2. дамп базы;
3. замена файлов проверенным выпуском;
4. `scripts/upgrade-postgres.sh` (однократный переход с PostgreSQL 16 на 18);
5. сборка и запуск;
6. `scripts/doctor.sh`.

При ошибке на любом шаге сработает `trap`: вернутся файлы и база, сервер пометится «режимом восстановления». Обычно обновление запускает [автообновление](AUTO_UPDATE.md).

## Проверено (этап 15)

`tests/test_stage15_install.py` и `tests/test_docker_installer.py` проверяют:
- у долгоживущих служб есть health check и `restart`;
- порты публикуют только Caddy и приём почты;
- данные лежат в именованных томах;
- worker видит том копий;
- обновление и откат сохраняют `.env` и `.control`;
- установщик включает агент автообновления.

Исправлено в v28.74.0: ручной `scripts/rollback.sh` удалял каталог `.control`, после этого админка теряла связь с агентом автообновления.
