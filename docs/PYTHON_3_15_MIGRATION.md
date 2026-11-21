# Миграция backend на Python 3.15

Статус: **этап совместимости; production runtime пока остаётся Python 3.14**.

## Проверенные исходные данные

| Поверхность | Текущее состояние | Целевое состояние | Источник |
| --- | --- | --- | --- |
| Backend и Telegram-бот | Python 3.14 slim, immutable digest | Python 3.15 slim после полного CI и закрепления digest | `services/backend/Dockerfile*` |
| Support Pro | Python 3.15 slim, immutable digest | без изменения | `services/support-pro/app/Dockerfile` |
| Backend CI | Python 3.14, два shards | Python 3.14 и 3.15, два shards для каждой версии | `.github/workflows/ci.yml` |
| Resolver | только Python 3.14 image | Python 3.14 и 3.15 official images | `.github/workflows/resolve-image-digests.yml` |

Upstream: CPython 3.15.2, официальный stable-релиз 25 октября 2026 года. Лицензия: PSF License Agreement. Контейнерный источник: Docker Official Image `python`. Номер версии сам по себе не считается доказательством: resolver обязан вывести фактический runtime и immutable manifest digest.

## Что проверяет временная матрица

Обе версии Python устанавливают один и тот же закреплённый runtime/test graph и выполняют полный backend suite в двух shards. Это охватывает Alembic, asyncpg/PostgreSQL, Redis, FastAPI, worker, Telegram-бот, mail receiver, backup/restore контракты и packaging. C-extension зависимости (`cryptography`, `Pillow`, `PyYAML`, `reportlab`, `uvloop`, `httptools`, `greenlet`, `pydantic-core`) реально устанавливаются pip на runner; отсутствие совместимого wheel или ошибка сборки останавливает job.

## Gate переключения production

1. Все четыре backend matrix jobs (3.14/3.15 × shard 1/2) и общий CI gate успешны на точном head PR.
2. Resolver подтверждает официальный Python 3.15 slim и его digest.
3. Отдельным непустым PR заменяются оба backend Dockerfile, Compose build args, deployment scripts и документация; 3.14 не удаляется до этого доказательства.
4. Контейнерные сборки, health checks, migrations и security scan успешны на точном head.
5. После squash merge обязателен успешный post-merge CI точного main.

Физическое устройство, production VPS и реальные данные для этого этапа не требуются и не заявляются.