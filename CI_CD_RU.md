> Актуальный дистрибутив: `v28.30.0`; runtime/API: `21.5.1`. Точные границы готовности указаны в текущей матрице покрытия.

# CI/CD — v21.5.1

GitHub CI проверяет Python/backend с PostgreSQL и миграциями, Support Pro, аудит зависимостей, три web-сборки, настоящий Chromium WebAuthn, Compose/контейнеры с Redis AUTH, Android и iOS. Локальные SQLite-тесты не заменяют PostgreSQL-проверки конкуренции.

После полного успешного push CI точного `main` workflow `publish-release.yml` упаковывает исходники, создаёт SHA256 и detached manifest, проверяет загрузку и публикует релиз. Публикация уже существующего релиза не заменяет его вложения. Каждый новый выпуск получает собственный тег.

Docker workflow публикует пять образов: backend, bot, admin, cabinet, miniapp. Stable использует `latest`, alpha — `preview`. Для воспроизводимости сохраняйте digest нужного образа.

Mobile workflow запускается при изменении mobile/build scripts/манифеста. Production APK/IPA требуют Android/Apple signing secrets; без них публикуется только правдивый `mobile-production-status.json`. Успешная компиляция не доказывает подпись или VPN-туннель.

Production Deploy запускается вручную с точным опубликованным `release_tag`. Нужны environment `production` и secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH`, при необходимости `DEPLOY_PORT`. Он вызывает проверенный updater и не разворачивает магазин при самой публикации релиза. [Обновление](docs/ru/WORKSPACE_UPGRADE.md), [backup](docs/ru/BACKUP_CURRENT.md).

Перегенерация API-каталога: `PYTHONPATH=backend python scripts/generate-api-docs.py`. Проверка актуальности: добавьте `--check`. Регистр текущих руководств: [docs/current-guides.json](docs/current-guides.json). [Основная документация](DOCUMENTATION.md).
