> **Историческая инструкция.** Текущая версия v21.0.1: [установка](DEPLOYMENT_CURRENT.md), [обновление](WORKSPACE_UPGRADE.md). Команды ниже относятся только к указанной прежней версии.

# VPN Shop 20.0.29: установка с нуля на VDS

Актуальный production-маршрут для v20.0.29.

## Требования

- Ubuntu 24.04 или Debian 12
- SSH с sudo
- домены API, админки, Mini App, кабинета и Support Pro
- TCP 80/443
- Git
- доступ к Remnawave и необходимые секреты

## Установка

```bash
cd /opt
sudo git clone --branch v20.0.29 --depth 1 https://github.com/booarkz-cpu/shop-by-boo.git vpn-shop-src
cd /opt/vpn-shop-src
sudo bash infrastructure/deployment/install-vps.sh
```

После установки:

```bash
cd /opt/vpn-shop
sudo docker compose ps
sudo docker compose exec -T backend python - <<'PY'
from app.main import APP_VERSION
print(APP_VERSION)
PY
```

Ожидается `20.0.29`.

## Важные правила

- Храните секреты только на сервере и не публикуйте их в GitHub/issues/чатах.
- Для первой настройки кассы используйте staging/sandbox до прохождения полного E2E.
- Не выполняйте `docker compose down -v`.
- Для дальнейших обновлений используйте [инструкцию обновления](UPDATE_TO_CURRENT_20_0_29.md).
- После установки проверьте HTTPS, `/health/ready`, админку, кабинет, Mini App и Support Pro.
