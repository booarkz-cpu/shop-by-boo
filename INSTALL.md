# Установка v28.36.0

Это стабильный дистрибутив v28.36.0 с runtime/API `21.5.1`. Реальные платежи открыты сразу после установки и настройки ключей провайдера; администратор может остановить их аварийной кнопкой. Для знакомства используйте отдельный локальный контур либо отдельный VDS. Не заменяйте действующий магазин без проверенной копии базы, файлов и сохранённых серверных настроек.

## Локально

Нужны Git, Python 3, Docker Engine и Compose. На Windows используйте WSL2/Docker Desktop.

```bash
git clone --branch v28.36.0 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
bash scripts/test-up.sh
```

Скрипт создаёт уникальные тестовые секреты в `.env.test`, запускает изолированный Compose и проверяет sandbox. Loopback-порты: API 18080, админка 18081, кабинет 18082, Mini App 18083. Адреса и вход выводятся скриптом. Подписка `sandbox://local/...` проверяет магазин и не даёт настоящего VPN.

## VDS и Termius

Подключитесь к отдельному Ubuntu-серверу через SSH/Termius и выполните:

```bash
git clone --branch v28.36.0 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
sudo bash deploy/install-vps.sh
```

Нужны домены с корректными DNS A/AAAA, открытые 80/443, доступ к Docker, Telegram и Remnawave. Установщик запрашивает параметры. Проверяйте назначение доменов API, админки и кабинета. Подробные требования и поля: [VDS](docs/ru/DEPLOYMENT_CURRENT.md); это актуальное руководство v28.36.0, обновление описано в [обновлении](docs/ru/WORKSPACE_UPGRADE.md).

Для loopback-теста на VDS вместо публичной установки запустите `scripts/test-up.sh` и настройте туннель по [INSTALL_STEPS.md](INSTALL_STEPS.md). Для HTTPS стенда прочитайте [условия готовности](docs/ru/FINAL_RELEASE_READINESS.md). Настройка доменов не открывает реальные платежи.

## Существующий магазин

Используйте [регламент обновления](docs/ru/WORKSPACE_UPGRADE.md). Новый head магазина — `0079_acquisition`, Support Pro — `0008`. Не откатывайте 0052 после появления участия в акциях. Новая установка backend применяет Alembic через entrypoint; после обновления отдельно проверьте `alembic current`, health и фоновые задачи.

## Состав v28.36.0

Админ-панель, кабинет и Mini App собраны на Next.js (static export в прежние nginx-образы) в тёмной теме Remna с выдвижным меню на телефонах и контекстными подсказками. Раздел [переноса истории](docs/ru/HISTORY_IMPORT_CURRENT.md) переносит подписки и платежи прежнего магазина со сверкой и откатом; [настройки без перезапуска](docs/ru/RUNTIME_SETTINGS_CURRENT.md) сохраняются. Схема обновляется до `0079_acquisition`, runtime/API остаётся `21.5.1`. [Полная инструкция production](docs/ru/PRODUCTION_CURRENT.md) охватывает SSH/Termius, DNS/TLS, настройку, приёмку, backup/restore, обновления и инциденты. Вся матрица ещё не завершена; production gate закрыт. С v28.36.0 установщик включает автообновление с GitHub (ночью, с откатом при ошибке), им управляют из админ-панели: «Выпуски → Автообновление» ([INSTALLATION.md §9](docs/INSTALLATION.md#9-обновления-автодеплой-и-откат)).
