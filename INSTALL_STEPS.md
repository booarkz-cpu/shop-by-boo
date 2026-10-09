# Установка и проверка по шагам

## 1. Выберите контур

v27 выпускает текущее проверенное ядро; runtime/API сообщает версию `21.5.1`. Перед эксплуатацией нужен отдельный стенд; production-платежи пока закрыты. Локальная песочница не требует касс и Remnawave. Отдельный HTTPS стенд нужен для внешних callbacks, SMTP и настоящего тестового VPN. [Все требования](INSTALL.md).

## 2. Подключитесь к VDS

В Termius создайте SSH host с IP, пользователем и своим ключом, подключитесь к серверу. В командной строке:

```bash
ssh root@SERVER_IP
```

Замените `SERVER_IP`. Пароль вводится интерактивно; не передавайте секрет в командной строке.

## 3. Поднимите тестовый магазин одной последовательностью

```bash
git clone --branch v27 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
bash scripts/test-up.sh
```

Сохраните показанные адреса и данные тестового администратора. Проверьте контейнеры:

```bash
docker compose --env-file .env.test -f docker-compose.test.yml ps
docker compose --env-file .env.test -f docker-compose.test.yml logs --tail=80 backend worker
```

## 4. Откройте интерфейсы через туннель

Termius: Local Port Forwarding, локальный 18082 → серверный `127.0.0.1:18082`, локальный 18081 → `127.0.0.1:18081`. Для компьютера с SSH:

```bash
ssh -L 18080:127.0.0.1:18080 -L 18081:127.0.0.1:18081 -L 18082:127.0.0.1:18082 -L 18083:127.0.0.1:18083 root@SERVER_IP
```

Откройте `http://127.0.0.1:18082` и `http://127.0.0.1:18081`. Оставьте SSH подключение открытым.

## 5. Проверьте функции

Регистрация → фиксированный тариф/конструктор → sandbox-заказ → подписка и профиль → кошелёк → смена тарифа/трафик → поддержка. Email-восстановление и участие в наградных акциях требуют SMTP и подтверждения email. Не делайте отметку подтверждения в БД вместо внешней проверки письма. [Кабинет](docs/ru/WORKSPACE_USER_GUIDE.md), [админка](docs/ru/WORKSPACE_ADMIN_GUIDE.md), [конкурсы](docs/ru/WORKSPACE_GIVEAWAYS.md).

## 6. Остановите тест

```bash
docker compose --env-file .env.test -f docker-compose.test.yml down
```

Volumes сохраняются. Параметр `-v` удаляет тестовые данные, применяйте его только при намеренном сбросе.

## 7. HTTPS стенд и обновление

[INSTALL.md](INSTALL.md), [готовность stable](docs/ru/FINAL_RELEASE_READINESS.md), [миграции и backup](docs/ru/WORKSPACE_UPGRADE.md). В этом выпуске подтверждённого внешнего платёжного E2E нет; обход gate не является этапом установки.

## Что изменилось в v27

Команды закреплены за точным тегом, а migration head и release identity синхронизированы. [Полная инструкция production](docs/ru/PRODUCTION_CURRENT.md) охватывает SSH/Termius, DNS/TLS, настройку, приёмку, backup/restore, обновления и инциденты. Матрица документации завершена; фактически открытые функции и внешний E2E перечислены в [реестре критериев](docs/ru/MATRIX_COMPLETION_21_5_1.md). Production gate закрыт.
