# Docker: доказательная приёмка REQ-QA-0007

Дата сверки: 27 ноября 2026 года. Карточка: `REQ-QA-0007`.

Этот документ связывает каждый пункт Docker-аудита владельца с исполняемым контролем. Он не заменяет CI и не подтверждает внешний VPS: статус PASS относится к репозиторному Docker/Compose-контуру, который запускается на чистых GitHub-hosted amd64 и arm64 исполнителях.

| Критерий | Реализация | Исполняемое доказательство |
| --- | --- | --- |
| Dockerfile | Backend, bot, Support Pro и три web-образа имеют самостоятельные Dockerfile; runtime работает UID 10001 и с read-only rootfs | `.github/workflows/ci.yml`: native amd64/arm64 build и запуск с `--network none --read-only`; `.github/workflows/docker.yml`: сборка пяти публикуемых образов |
| Compose | Shop, integration, test и Support Pro описаны отдельными Compose-моделями | `scripts/ci/check-compose-profiles.py` рендерит каждую модель и все комбинации профилей |
| Volumes | PostgreSQL, Redis, media, app packages и Support Pro uploads хранятся в именованных томах | `scripts/ci/restore-drill.sh` удаляет контейнеры и все тома, затем восстанавливает обе БД и файлы только из резервной копии |
| Networks | Сервисы связаны внутренними Compose-сетями; publish/ingress отделён от service-to-service | Нормализованный `docker compose config` для каждого профиля и интеграционный запуск в `.github/workflows/ci.yml` |
| Ports | Публичные привязки заданы Compose-конфигурацией, внутренние БД и Redis не становятся внешним API | Проверка нормализованной конфигурации и фактический health/API smoke в контейнерном job CI |
| Health checks | PostgreSQL, Redis и приложения имеют healthcheck; запуск зависит от `service_healthy` там, где это требуется | `docker compose up -d --wait`, контейнерный smoke и `scripts/ci/check-compose-profiles.py` |
| Restart policies | Долгоживущие сервисы получают явную политику перезапуска; одноразовые init/migration задачи не маскируются вечным restart | Нормализованный Compose и фактический запуск всех профилей в CI |
| Dependencies | `depends_on` и условия готовности согласованы с БД, Redis, миграциями и worker-процессами | Container/restore jobs в `.github/workflows/ci.yml`, включая чистую и восстановленную БД |
| Environment | Обязательные значения проходят через env-файлы и Compose interpolation; профили проверяются с чистыми тестовыми env | `scripts/ci/check-compose-profiles.py`; installer pin check сохраняет пользовательские строки и права 0600 |
| Secrets | Обязательные пароли отмечены `:?set ...`; значения не входят в образы и не печатаются в журнал | secret scan CI и `tests/test_container_logs.py`, проверяющий маскирование значений из `.env` |
| Database | PostgreSQL 19, Redis auth, обе БД и non-root/read-only runtime проверяются в контейнерах | Native amd64/arm64 jobs и container job `.github/workflows/ci.yml` |
| Migrations | Alembic применяется на чистой БД и проверяется после восстановления; downgrade/rollback сохраняет данные и старые тома | Backend migration suites и `scripts/ci/restore-drill.sh` |
| Logs | Разрешён только закрытый список сервисов, число строк ограничено, секреты маскируются до возврата панели | `tests/test_container_logs.py` |
| Доступность сервисов | Compose ждёт готовность, выполняет HTTP/API smoke и после восстановления повторно проверяет вход администратора | Container job и шаги 6–7 `scripts/ci/restore-drill.sh` |

## Границы доказательства

- Проверка не выполняет миграции на живом VPS и не удаляет пользовательские production volumes.
- Внешняя панель владельца, публичный домен и настоящая нода остаются ограничениями O1/O2/O13.
- Успех моков не используется вместо контейнерных проверок: Compose, PostgreSQL, Redis, ClamAV, образы и restore drill запускаются реально на CI-исполнителях.
