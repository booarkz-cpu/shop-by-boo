# Установка v26

Это стабильный дистрибутив v26 с runtime/API `21.5.1`. Production-платежи закрыты до завершения application E2E v2. Для знакомства используйте отдельный локальный контур либо отдельный VDS. Не заменяйте действующий магазин без проверенной копии базы, файлов и сохранённых серверных настроек.

## Локально

Нужны Git, Python 3, Docker Engine и Compose. На Windows используйте WSL2/Docker Desktop.

```bash
git clone --branch v26 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
bash scripts/test-up.sh
```

Скрипт создаёт уникальные тестовые секреты в `.env.test`, запускает изолированный Compose и проверяет sandbox. Loopback-порты: API 18080, админка 18081, кабинет 18082, Mini App 18083. Адреса и вход выводятся скриптом. Подписка `sandbox://local/...` проверяет магазин и не даёт настоящего VPN.

## VDS и Termius

Подключитесь к отдельному Ubuntu-серверу через SSH/Termius и выполните:

```bash
git clone --branch v26 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
sudo bash deploy/install-vps.sh
```

Нужны домены с корректными DNS A/AAAA, открытые 80/443, доступ к Docker, Telegram и Remnawave. Установщик запрашивает параметры. Проверяйте назначение доменов API, админки и кабинета. Подробные требования и поля: [VDS](docs/ru/DEPLOYMENT_CURRENT.md); это актуальное руководство v26, обновление описано в [обновлении](docs/ru/WORKSPACE_UPGRADE.md).

Для loopback-теста на VDS вместо публичной установки запустите `scripts/test-up.sh` и настройте туннель по [INSTALL_STEPS.md](INSTALL_STEPS.md). Для HTTPS стенда прочитайте [условия готовности](docs/ru/FINAL_RELEASE_READINESS.md). Настройка доменов не открывает реальные платежи.

## Существующий магазин

Используйте [регламент обновления](docs/ru/WORKSPACE_UPGRADE.md). Новый head магазина — `0062_support_delivery_identity`, Support Pro — `0006`. Не откатывайте 0052 после появления участия в акциях. Новая установка backend применяет Alembic через entrypoint; после обновления отдельно проверьте `alembic current`, health и фоновые задачи.

## Состав v26

Добавлены [партнёрский кабинет и комиссии](docs/ru/PARTNERS_CURRENT.md), [клиентские ключи доступа](docs/ru/CUSTOMER_PASSKEYS_CURRENT.md) и [объединение/разделение обращений](docs/ru/SUPPORT_TOPOLOGY_CURRENT.md). [Полная инструкция production](docs/ru/PRODUCTION_CURRENT.md) охватывает SSH/Termius, DNS/TLS, настройку, приёмку, backup/restore, обновления и инциденты. Вся матрица ещё не завершена; production gate закрыт.
