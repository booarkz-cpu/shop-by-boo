# Выпуск v28.70.0 — модули серверов Remnawave (этап 12, часть Б)

Дистрибутив: `v28.70.0`. Runtime/API: `21.5.1`. Head магазина: `0091_remnawave_domains` (миграций нет). Support Pro: `0008` / 3.8. Дата и commit фиксируются тегом выпуска.

## Что сделано

Функции `eGamesAPI/remnawave-reverse-proxy` (MIT, (c) 2025 eGames) на серверах нод — шагами мастера установки по SSH из закрытого списка, с планом, подтверждением по SHA-256 и откатом ([менеджер расширений](new/REMNAWAVE_EXTENSIONS.md), [Deployment Agent](new/DEPLOYMENT_AGENT.md)):

- **SelfSteal (TLS + REALITY):** в мастере для одной ноды — домен и сайт-шаблон. Caddy на ноде получает сертификат домена и отдаёт сайт на `/dev/shm/selfsteal.sock`; мастер создаёт в панели профиль VLESS + REALITY (`dest` — сокет, `xver: 1`) и хост, привязывает к нему ноду и проверяет сайт на сокете. Без ключей REALITY на порту 443 виден обычный сайт.
- **Модули серверов** у успешной установки («Журнал → Модули серверов»):
  - **IPv6** — включить или выключить (sysctl), откат к прежней настройке;
  - **ядро Xray** — релиз XTLS/Xray-core, SHA-256 из GitHub фиксируется в плане и проверяется на сервере (и `.dgst`), возврат к ядру из образа; «Обновить» сохраняет выбранное ядро;
  - **WARP Native** — интерфейс `warp` через wgcf (SHA-256 из GitHub, после согласия с условиями Cloudflare); исходящий `warp-out` и домены — «Расширения Remnawave → WARP в профиле» ([WARP и NetBird](new/WARP_NETBIRD.md));
  - **NetBird** — пакет из подписанного репозитория, ключ установки только через stdin и не хранится;
  - **Xray Checker** — проверка подписки по расписанию, результаты в админке, уведомления о недоступных серверах раз в час ([Xray Checker](new/XRAY_CHECKER.md)).
- **Серверный роутинг** («Расширения Remnawave → Серверный роутинг», API панели): мост Shadowsocks с ноды входа на ноду выхода, служебный пользователь и сквад, правила для российских адресов в режимах «прямо» и «через мост» ([серверный роутинг](new/SERVER_ROUTING.md)).

Отличие от скрипта eGames: мастер не запускает чужой установочный скрипт WARP от root — шаги свои, с проверкой SHA-256.

Исправлено: исполнитель установки ждёт остановки пульса задачи (`heartbeat`), прежде чем завершить запуск.

## Проверка

| Что | Где | Статус |
| --- | --- | --- |
| SelfSteal: правила плана, файлы, профиль и хост, проверка сокета | `tests/test_rw_node_modules.py` | PASS |
| Модули: SHA-256 из GitHub, откат при ошибке ядра, ключ NetBird только в stdin, Xray Checker и уведомления | `tests/test_rw_node_modules.py` | PASS |
| WARP в профиле, серверный роутинг в обоих режимах, удаление моста | `tests/test_rw_extensions.py` | PASS |
| Разделы админки: SelfSteal в мастере, модули, результаты Xray Checker, WARP, роутинг | `admin/e2e/rw-installer.spec.ts`, `admin/e2e/rw-extensions.spec.ts` | PASS |
| Настоящая панель и нода на раннере CI: SelfSteal, сайт на 443 без ключей, IPv6, ядро Xray последнего релиза, образ Xray Checker | `tests/live/test_node_modules_live.py` (задание `node-modules`) | PASS (CI) |
| Клиент VLESS + REALITY с публичным сертификатом; мост между двумя нодами | нужны VPS и домен | BLOCKED_EXTERNAL |
| WARP на настоящем сервере | нужно согласие владельца с условиями Cloudflare WARP | BLOCKED_EXTERNAL |
| NetBird на настоящем сервере | нужен ключ установки NetBird | BLOCKED_SECRETS |

## Обновление

Миграций нет.

```bash
cd /opt/vpn-shop && bash scripts/backup.sh
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.70.0 bash /opt/vpn-shop/scripts/update-from-github.sh
```
