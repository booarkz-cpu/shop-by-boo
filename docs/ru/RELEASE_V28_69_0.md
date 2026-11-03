# Выпуск v28.69.0 — менеджер расширений Remnawave (этап 12, часть А)

Дистрибутив: `v28.69.0`. Runtime/API: `21.5.1`. Head магазина: `0091_remnawave_domains` (миграций нет). Support Pro: `0008` / 3.8. Дата и commit фиксируются тегом выпуска.

## Что сделано

«Серверы → Расширения Remnawave» ([менеджер расширений](new/REMNAWAVE_EXTENSIONS.md)). Всё работает через API панели Remnawave, без SSH:
- **Профили конфигурации:** список с inbound и нодами, правка JSON, создание, удаление, назначение нодам, хост для inbound.
- **Конструктор VLESS + REALITY:** ключи x25519 выдаёт панель; shortIds, serverNames, минимальная версия клиента; маскировка SelfSteal (сайт-шаблон самой ноды на сокете) или чужим сайтом; блокировка частных адресов и BitTorrent; DoH.
- **Плагины нод** ([плагины](new/NODE_PLUGINS.md)): TorrentBlocker, фильтры входящих и исходящих адресов, сброс соединений; привязка к нодам.
- **Правила подписки панели** ([правила](new/SUBSCRIPTION_RULES.md)): правила ответов (SRR) с проверкой тестером панели, лимит устройств, свои заголовки.
- **Страница и шаблоны подписки:** конфиги официальной страницы подписки, шаблоны Xray JSON / Mihomo / sing-box и другие, клиентский балансировщик ([балансировщик](new/CLIENT_BALANCER.md)).

Все 30 модулей Админ-центра теперь управляются из панели.

## Проверка

| Что | Где | Статус |
| --- | --- | --- |
| Тела запросов, конструктор REALITY, проверка ввода, ошибки панели | `tests/test_rw_extensions.py` | PASS |
| Настоящая панель последней версии: профиль REALITY, нода, хост; плагин TorrentBlocker на ноде; SRR и тестер; страница; шаблон с балансировщиком | `tests/live/test_remnawave_live.py` (11 тестов) | PASS (CI) |
| Раздел админки | `admin/e2e/rw-extensions.spec.ts` | PASS |
| REALITY и плагины на настоящей ноде с клиентом | нужен VPS | BLOCKED_EXTERNAL |

## Дальше

Этап 12, часть Б: SelfSteal (Caddy и сайт-шаблон на ноде), IPv6, ядро Xray, WARP, NetBird, Xray Checker, серверный роутинг — шагами мастера установки по SSH.

## Обновление

Миграций нет.

```bash
cd /opt/vpn-shop && bash scripts/backup.sh
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.69.0 bash /opt/vpn-shop/scripts/update-from-github.sh
```
