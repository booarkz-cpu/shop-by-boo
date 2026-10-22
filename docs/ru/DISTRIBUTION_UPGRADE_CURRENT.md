# Обновление дистрибутива до v28.8.0

Актуальный дистрибутив — `v28.8.0`, runtime/API — `21.5.1`. Миграции: магазин `0067_plugin_runtime`, Support Pro `0007`. В этом выпуске магазин получает миграцию `0067_plugin_runtime` (среда плагинов), с v28.4.0 и раньше — также `0066_push_notifications`; при обновлении с v28.6.0 и раньше Support Pro получает `0007` (email-канал). До обновления обязателен согласованный backup обеих баз.

## Новая установка

```bash
git clone --branch v28.8.0 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
sudo bash deploy/install-vps.sh
```

Настройка DNS, Docker и секретов: [DEPLOYMENT_CURRENT.md](DEPLOYMENT_CURRENT.md).

## Первое обновление существующего сервера

Старый загрузчик сравнивает только API-версию, поэтому не распознаёт дистрибутив с прежним API. Сначала сделайте проверенную резервную копию обеих БД, конфигураций и загруженных файлов: [WORKSPACE_UPGRADE.md](WORKSPACE_UPGRADE.md). `scripts/update.sh` также создаёт предобновляющий снимок и выполняет rollback при ошибке; внешний backup нужен для независимого восстановления.

В root-сессии SSH/Termius выполните команды ниже. Если каталог отличается от `/opt/vpn-shop`, измените `shop_dir`. Скрипт скачивается по фиксированному HTTPS-тегу; затем проверяет SHA-256 архива, манифест, API-версию и коммит тега до запуска обновления.

```bash
set -euo pipefail
shop_dir=/opt/vpn-shop
upgrade_stage=$(mktemp -d)
upgrade_checker=$(mktemp)
trap 'rm -rf -- "$upgrade_stage"; rm -f -- "$upgrade_checker"' EXIT
curl --fail --show-error --silent --proto '=https' --max-time 60 \
  https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v28.8.0/scripts/github_release_fetch.py \
  -o "$upgrade_checker"
RELEASE_TAG=v28.8.0 python3 "$upgrade_checker" "$shop_dir" "$upgrade_stage"
if [ -f "$upgrade_stage/backend/app/main.py" ]; then
  APP_DIR="$shop_dir" UPDATE_STAGE="$upgrade_stage" bash "$shop_dir/scripts/update.sh"
fi
APP_DIR="$shop_dir" bash "$shop_dir/scripts/doctor.sh"
```

Загрузчик отказывается применять draft/prerelease, более старую версию, архив с небезопасными путями, неправильной суммой или несовпадающим коммитом. При уже установленном `v28.8.0` он завершится без применения файлов. Не удаляйте `.env`, `support-pro/.env`, volumes и backups.

## Последующие обновления

После первого обновления установленный загрузчик знает тег дистрибутива:

```bash
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.8.0 \
  bash /opt/vpn-shop/scripts/update-from-github.sh
```

Без `RELEASE_TAG` выбирается последний стабильный GitHub Release. Обновление отдельного сервиса поддержки описано в [support-pro/UPGRADE.md](../../support-pro/UPGRADE.md).

## Проверка после обновления

```bash
cd /opt/vpn-shop
docker compose ps
bash scripts/doctor.sh
docker compose exec -T backend alembic current
docker compose logs --tail=100 backend bot worker
```

Проверьте вход, светлую/тёмную тему, язык, подсказки с телефона, сохранение тарифа и страницы. Откройте [настройки без перезапуска](RUNTIME_SETTINGS_CURRENT.md), сверьте счётчики 96/55/2 и выполните на стенде apply/rollback безопасного значения. На тестовых профилях выполните [проверку account merge](ACCOUNT_MERGE_CURRENT.md), затем [инфраструктурные проверки](INFRASTRUCTURE_CHECKS_CURRENT.md). Ответ health/API `21.5.1` и head `0067_plugin_runtime` ожидаемы для этого дистрибутива. Проверка UI и CI не подтверждает реальные платежи или доступность VPN-узлов на вашем сервере.

После первой runtime-ревизии downgrade `0064_runtime_settings` блокируется, чтобы не потерять audit и снимки отката. После первого успешного объединения также блокируется downgrade `0063_account_merge`. Используйте исправление вперёд либо согласованное восстановление backup.
