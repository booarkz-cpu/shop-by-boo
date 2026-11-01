# Установка

От сервера до первого клиента. Каждый шаг объясняет, что делать, зачем и как проверить, что получилось.

## 1. Подготовьте сервер

Нужен VDS на Ubuntu 22.04+ (проверено на 24.04): 2 ядра, 4 ГБ RAM, 20 ГБ SSD.

```bash
ssh root@ВАШ_IP
apt update && apt upgrade -y
```

**Зачем:** установщик ставит Docker и пакеты через `apt`; на устаревшей системе репозитории могут не ответить.

## 2. Направьте домен на сервер

В панели вашего DNS-провайдера создайте записи:

| Тип | Имя | Значение |
| --- | --- | --- |
| A | `admin` | IP сервера |
| A | `lk` | IP сервера |
| A | `app` | IP сервера |

**Зачем:** Caddy выпускает TLS-сертификат только если домен уже указывает на сервер.

Проверка (должен вернуться ваш IP):

```bash
dig +short admin.ваш-домен.ru
```

## 3. Установите магазин

Одной командой:

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v28.57.0/install.sh -o /root/shop-install.sh
BRANCH=v28.57.0 bash /root/shop-install.sh
```

Установщик спросит домены, цены и пароль администратора, поставит Docker, соберёт образы, применит миграции
и запустит сервисы. Он **не** сообщает об успехе, если хоть один сервис не поднялся.

**Зачем именно так:** установщик сам открывает только 22, 80, 443 — база, Redis и API остаются закрытыми.

## 4. Заполните `.env`

Файл создаётся установщиком. Обязательные поля:

| Переменная | Назначение | Где взять |
| --- | --- | --- |
| `APP_SECRET` | подпись сессий и токенов | `openssl rand -hex 32` |
| `DB_PASSWORD` | пароль PostgreSQL | придумайте длинный |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | вход в админ-панель | придумайте |
| `REMNAWAVE_URL`, `REMNAWAVE_TOKEN` | выдача доступа | панель Remnawave → API |
| `BOT_TOKEN` | Telegram-бот | [@BotFather](https://t.me/BotFather) |
| `PUBLIC_BASE_URL` | адрес магазина | ваш домен |

Применить изменения:

```bash
docker compose up -d
```

## 5. Проверьте, что всё живо

```bash
bash scripts/doctor.sh
```

Команда проверяет конфигурацию Compose, состояние контейнеров и отвечает ли `/health`. Ожидаемо:
`API health: OK`.

```bash
curl -s localhost:8000/health
# {"ok":true,"version":"21.5.1","redis":true,"database":true,...}
```

## 6. Первый вход

1. Откройте `https://admin.ваш-домен.ru`.
2. Войдите с `ADMIN_EMAIL` и `ADMIN_PASSWORD` из `.env`.
3. Смените пароль и включите 2FA в разделе «Безопасность».
4. Создайте тарифы в разделе «Тарифы» и укажите Internal Squad из Remnawave.
5. Подключите кассу в «Платежи» — см. [Платежи](Payments.md).

## Если что-то не так

| Симптом | Что проверить |
| --- | --- |
| `doctor.sh` пишет API health: FAILED | `docker compose logs backend` |
| Контейнер перезапускается | `docker compose logs <сервис>`, `free -h` |
| Нет сертификата | DNS-запись, порты 80 и 443, `docker compose logs caddy` |
| Панель открывается, но пустая | `curl -s localhost:8000/health`, затем консоль браузера |

Полная таблица: [Диагностика](Troubleshooting.md).

## Обновление установленного магазина

```bash
bash scripts/backup.sh
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.57.0 bash /opt/vpn-shop/scripts/update-from-github.sh
```

Подробно: [Обновления](Updates.md).

[← На главную](Home.md)
