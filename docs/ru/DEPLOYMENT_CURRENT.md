# Установка v26 на VDS через SSH и Termius

Для новой установки используйте отдельный Ubuntu 24.04 / Debian 12 сервер. Стабильный канал содержит проверенное ядро; приём настоящих платежей пока закрыт. [Границы готовности](FINAL_RELEASE_READINESS.md).

## Подготовка

Нужны SSH с root/sudo, свободные TCP 80/443, пять доменов API/админки/кабинета/Mini App/Support Pro, токен бота и доступ к собственной Remnawave. Создайте DNS A-записи на адрес VDS; AAAA оставляйте только при работающем IPv6. Внешний firewall хостера должен пропускать HTTP/HTTPS. Базы и Redis наружу не открывайте.

В Termius создайте Host с адресом VDS, пользователем и своим SSH-ключом, затем откройте терминал. Через обычную командную строку, в том числе Windows с OpenSSH:

```bash
ssh -t root@SERVER_IP
```

## Одна команда установки

На новом сервере от root:

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v26/install.sh -o /root/shop-install.sh && BRANCH=v26 bash /root/shop-install.sh
```

Загрузка файла и клонирование тега выполняются автоматически; вручную распаковывать архив не нужно. Установщик ставит необходимые пакеты/Docker, запрашивает домены, email сертификата, параметры администратора и подключений, создаёт окружение и собирает сервисы. Пароли вводите в терминале и храните отдельно от GitHub/чатов. Лицензия: [LICENSE](../../LICENSE).

Из уже полученного исходного тега:

```bash
git clone --branch v26 --depth 1 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
sudo bash deploy/install-vps.sh
```

Wrapper по умолчанию закреплён за `v26` и не заменяет другой существующий source checkout. Для нового source-каталога задайте `SOURCE_DIR`; для действующего магазина используйте обновление, а не повторную установку.

## Контроль после запуска

```bash
cd /opt/vpn-shop
sudo docker compose ps
sudo docker compose logs --tail=100 backend worker support_pro support_worker
sudo docker compose exec -T backend python -c 'from app.main import APP_VERSION; print(APP_VERSION)'
sudo docker compose exec -T backend alembic current
sudo docker compose exec -T support_db psql -U support -d support -Atc 'SELECT version_num FROM alembic_version'
```

Ожидаемая версия API `21.5.1` (это не номер тега), head магазина `0062_support_delivery_identity`, Support Pro `0006`.

Проверьте HTTPS всех доменов, `/health/ready`, вход, worker, кабинет и Support Pro. Health не подтверждает внешние платежи, SMTP или VPN. Реальные платежи не включайте вручную в AppSetting; [порядок E2E](STAGING_E2E_V2_IMPLEMENTATION.md).

## Тест без внешних сервисов

```bash
bash scripts/test-up.sh
```

| Поверхность | Loopback-порт |
| --- | --- |
| API | 18080 |
| Админка | 18081 |
| Кабинет | 18082 |
| Mini App | 18083 |

Для удалённого теста в Termius настройте Local Port Forwarding на `127.0.0.1:18081` и `127.0.0.1:18082` сервера. Через командную строку:

```bash
ssh -L 18081:127.0.0.1:18081 -L 18082:127.0.0.1:18082 root@SERVER_IP
```

Откройте локальные адреса в браузере. `sandbox://local/...` проверяет записи магазина и не даёт VPN-туннель. [Все тестовые сценарии](TESTING.md).

## Дальше

[Администратор](WORKSPACE_ADMIN_GUIDE.md), [клиент](WORKSPACE_USER_GUIDE.md), [рефералы](REFERRALS_CURRENT.md), [backup](BACKUP_CURRENT.md), [обновление](WORKSPACE_UPGRADE.md), [эксплуатация](../../OPERATIONS_RUNBOOK_RU.md).

## Состав v26

[Полный регламент production](PRODUCTION_CURRENT.md) · [партнёры](PARTNERS_CURRENT.md) · [клиентские ключи доступа](CUSTOMER_PASSKEYS_CURRENT.md) · [merge/split обращений](SUPPORT_TOPOLOGY_CURRENT.md).
