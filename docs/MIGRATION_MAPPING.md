# Сверка старых репозиториев с shop-by-boo (REQ-MIG-0020…0022, 0027)

Решение владельца № 12 (2026-11-14): «сверить и перенести недостающее»; № 13: из чужих источников — только идеи, свой код.
Целевой репозиторий один — `booarkz-cpu/shop-by-boo` (REQ-MIG-0019). Исходные репозитории не удаляются и не меняются (REQ-MIG-0012).

## 1. Источники (REQ-MIG-0020)

| Источник | Состояние на 2026-11-14 | Итог |
|---|---|---|
| `booarkz-cpu/shop-by-boo` | целевой; ветка `main`, перед этой сверкой — `fbe430c` (v28.147.0) | — |
| `booarkz-cpu/VPN-Shop-by-CorgiLusi` | при подключении указывает на тот же репозиторий, что и shop-by-boo (тот же `HEAD fbe430c`) — это прежнее имя | переносить нечего |
| `booarkz-cpu/remnawave-manager` | публичный, MIT, © Корги Люси (автор — владелец); ветка `main`, `5b83423d5be35b67340a94c97eab0e627944777b` от 2026-09-24; версия скрипта `1.5.6`; тегов 0, других веток нет; 6466 строк `remnawave-manager.sh`, меню 1–33 в `docs/MENU.en.md` | сверено по пунктам ниже |
| `booarkz-cpu/lucy-vpn-android` | из этой среды недоступен (клонирование и API отказали: нет доступа или репозитория нет) | ждёт владельца: доступ или статус |
| Чужие источники (REQ-MIG-0004…0008) | AGPL / Commons Clause / без лицензии | только идеи (решение № 13); учёт — `docs/REFERENCE_REPOSITORIES.md`, `docs/CODE_REUSE_REGISTER.md` |

## 2. remnawave-manager → shop-by-boo (REQ-MIG-0021, 0022, 0027)

Каноническая реализация — в магазине: установка и обслуживание идут из админки по SSH с планом, подтверждением,
журналом и откатом, а не из меню на сервере. Колонка «Статус»: **есть** — функция в магазине уже есть (своя реализация);
**перенесено** — добавлено этой сверкой; **не переносим** — сознательно, с причиной.

| № | Пункт меню (источник `docs/MENU.en.md`, `5b83423`) | Магазин: модуль | Тесты | Статус |
|---|---|---|---|---|
| 1–3 | Полная установка / только панель / только нода | `backend/app/rw_plan.py`, `rw_steps.py`, `rw_api.py` (`/installations/plan`, `approve`) | `tests/test_rw_*` | есть |
| 4 | Автопривязка протоколов (профиль, хосты, сквад) | `rw_plan.py`, `rw_protocol_switch.py`, `node_autoscale.py` | `tests/test_rw_protocol_switch.py` | есть |
| 5–6 | Статус, Doctor | `rw_api.py` действие `diagnose`, `ops_alerts.py`, `block_monitor.py` | `tests/test_ops_alerts.py` | есть |
| 7 | Repair (502) | `rw_api.py` действие `reinstall`/`restore_files`, `rw_domains.py` | `tests/test_rw_*` | есть |
| 8–9 | Логи; up / down / restart | `rw_api.py` действия `logs`, `start`, `stop`, `restart` | `tests/test_rw_*` | есть |
| 10–11 | Резервная копия (age) и восстановление | `rw_snapshots.py`, `rw_autoupdate.py` (`panel-copies`), `backups_api.py` (шифрование `BACKUP_PASSWORD`, ежечасно — решение № 15) | `tests/test_backup_retention_verified.py` | есть |
| 12 | Обновление образов с копией и откатом | `rw_autoupdate.py` (выкл. по умолчанию), `masque_panel.py` | `tests/test_rw_autoupdate.py` | есть |
| 13 | Удаление | `rw_api.py` действия `remove`, `remove_component` | `tests/test_rw_*` | есть |
| 14 | Ядро Xray | `rw_plan.py` модуль `xray_core`, `rw_releases.py` | `tests/test_rw_*` | есть |
| 15 | Дополнения (WARP, NetBird, xray-checker) | `rw_plan.py` модули `warp`, `netbird`, `xray_checker` | `tests/test_rw_*` | есть |
| 16 | Скрытый вход в панель | `panel_gate.py` | `tests/test_panel_gate.py` | есть |
| 17 | Установка CLI на сервер | — | — | не переносим: управление идёт из админки |
| 18 | Конвертер подписок | `sub_proxy.py` (форматы под клиента по User-Agent) | `tests/test_subscription_middleware.py` | есть (как часть прокси подписок) |
| 19–20 | Благодарности; язык меню | `docs/REFERENCE_REPOSITORIES.md`; интерфейс магазина на русском | — | не переносим: другой интерфейс |
| 21 | Адреса и вход в панель | `rw_api.py` (`/credentials`), `rw_netmods.py` | `tests/test_rw_*` | есть |
| 22, 26 | Обновления автора / самообновление скрипта | `scripts/update.sh`, `scripts/github_release_fetch.py` (проверка `min_upgrade_from`) | `tests/test_distribution_update.py` | есть |
| 23 | Новости / ссылки автора | — | — | не переносим |
| 25 | Транспорты ноды (gRPC, xHTTP, Hysteria2) | `rw_protocol_switch.py`, `rw_plan.py` модуль `transports` | `tests/test_rw_protocol_switch.py` | есть |
| 27 | Добавить ноду в работающую панель | `rw_api.py` (`/servers`, план «только нода»), `node_autoscale.py` | `tests/test_rw_*` | есть |
| 28 | Пользователи: срок, трафик, лимит устройств, ссылка | `remnawave.py` (`hwidDeviceLimit`, `trafficLimitBytes`), магазин и админка | `tests/test_remnawave_architecture.py` | есть |
| 29 | Управление нодой: перезапуск, вкл/выкл, смена адреса | `remnawave.py` (`/api/nodes/{uuid}/actions/disable`, `restart-all`), `rw_selfsteal.py` | `tests/test_remnawave_architecture.py` | есть |
| 30 | Оповещения в Telegram и копия вне сервера | `ops_alerts.py`, `telegram_backup.py`, `backups_api.py` (S3) | `tests/test_promo_generator_and_tg_backup.py` | есть (S3 вместо rclone) |
| 31 | Сертификаты: срок, продление | `ops_alerts.py` `certificate_check` (14/3 дня; Caddy продлевает сам) | `tests/test_ops_alerts.py` | есть |
| 32 | Firewall и SSH только с адреса владельца | `deploy/install-vps.sh` (`ADMIN_SSH_IP`), `scripts/open-ports.sh` (`SSH_ONLY_FROM`), `backend/app/rw_ports.py` | `tests/test_admin_ssh_ip.py`, `tests/test_rw_ports.py` | **перенесено** в v28.148.0 |
| 33 | Заглушка на домене подписки | `sub_proxy.py` `mask_page` | `tests/test_subscription_middleware.py` | есть |

### Отличия, которые остаются (REQ-MIG-0022)

* Порог предупреждения о сертификате: в старом скрипте 21 день, в магазине 14 и 3 дня — Caddy продлевает за 30 дней,
  поэтому 14 дней уже означают сбой продления.
* Копия вне сервера: старый скрипт — rclone в 02:00, магазин — S3 и Telegram по расписанию (по умолчанию каждый час).
* `ADMIN_SSH_IP` применяется, только если текущая SSH-сессия идёт с этого адреса (или сессии нет): установщик не может
  отрезать оператору доступ. Иначе — предупреждение, SSH остаётся открытым.

## 3. Что дальше

* lucy-vpn-android — нужен доступ или подтверждение, что репозитория больше нет (REQ-MIG-0009).
* REQ-MIG-0023, 0028 — проверка «ничего не потеряно» после переноса папок по `docs/MONOREPO_LAYOUT.md` (решение № 14),
  по одному этапу на выпуск.
