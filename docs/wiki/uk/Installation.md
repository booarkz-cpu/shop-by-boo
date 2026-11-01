# Встановлення

Від сервера до першого клієнта. Кожен крок пояснює, що робити, навіщо і як перевірити результат.

## 1. Підготуйте сервер

Потрібен VDS на Ubuntu 22.04+ (перевірено на 24.04): 2 ядра, 4 ГБ RAM, 20 ГБ SSD.

```bash
ssh root@ВАШ_IP
apt update && apt upgrade -y
```

**Навіщо:** інсталятор ставить Docker і пакети через `apt`; на застарілій системі репозиторії можуть не відповісти.

## 2. Спрямуйте домен на сервер

У панелі вашого DNS-провайдера створіть записи:

| Тип | Ім'я | Значення |
| --- | --- | --- |
| A | `admin` | IP сервера |
| A | `lk` | IP сервера |
| A | `app` | IP сервера |

**Навіщо:** Caddy випускає TLS-сертифікат лише тоді, коли домен уже вказує на сервер.

Перевірка (має повернутися ваша IP):

```bash
dig +short admin.ваш-домен.com
```

## 3. Встановіть магазин

Однією командою:

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v28.57.0/install.sh -o /root/shop-install.sh
BRANCH=v28.57.0 bash /root/shop-install.sh
```

Інсталятор запитає домени, ціни й пароль адміністратора, поставить Docker, збере образи, застосує міграції та
запустить сервіси. Він **не** повідомляє про успіх, якщо хоч один сервіс не піднявся.

**Навіщо саме так:** інсталятор відкриває лише 22, 80 і 443 — база, Redis та API залишаються закритими.

## 4. Заповніть `.env`

Файл створює інсталятор. Обов'язкові поля:

| Змінна | Призначення | Де взяти |
| --- | --- | --- |
| `APP_SECRET` | підпис сесій і токенів | `openssl rand -hex 32` |
| `DB_PASSWORD` | пароль PostgreSQL | придумайте довгий |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | вхід в адмін-панель | придумайте |
| `REMNAWAVE_URL`, `REMNAWAVE_TOKEN` | видача доступу | панель Remnawave → API |
| `BOT_TOKEN` | Telegram-бот | [@BotFather](https://t.me/BotFather) |
| `PUBLIC_BASE_URL` | адреса магазину | ваш домен |

Застосувати зміни:

```bash
docker compose up -d
```

## 5. Перевірте, що все живе

```bash
bash scripts/doctor.sh
```

Команда перевіряє конфігурацію Compose, стан контейнерів і чи відповідає `/health`. Очікувано: `API health: OK`.

```bash
curl -s localhost:8000/health
# {"ok":true,"version":"21.5.1","redis":true,"database":true,...}
```

## 6. Перший вхід

1. Відкрийте `https://admin.ваш-домен.com`.
2. Увійдіть з `ADMIN_EMAIL` і `ADMIN_PASSWORD` з `.env`.
3. Змініть пароль і увімкніть 2FA у розділі «Безпека».
4. Створіть тарифи в розділі «Тарифи» і вкажіть Internal Squad з Remnawave.
5. Підключіть касу в «Платежі» — див. [Платежі](Payments.md).

## Якщо щось не так

| Симптом | Що перевірити |
| --- | --- |
| `doctor.sh` пише API health: FAILED | `docker compose logs backend` |
| Контейнер перезапускається | `docker compose logs <сервіс>`, `free -h` |
| Немає сертифіката | DNS-запис, порти 80 і 443, `docker compose logs caddy` |
| Панель відкривається, але порожня | `curl -s localhost:8000/health`, далі консоль браузера |

Повна таблиця: [Діагностика](Troubleshooting.md).

## Оновлення встановленого магазину

```bash
bash scripts/backup.sh
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.57.0 bash /opt/vpn-shop/scripts/update-from-github.sh
```

Докладно: [Оновлення](Updates.md).

[← На головну](Home.md)
