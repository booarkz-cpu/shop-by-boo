# WARP Native и NetBird

С v28.70.0 (этап 12). Модули серверов мастера установки: «Серверы → Установка Remnawave → задача установки → Журнал → Модули серверов». Идея — модули WARP и NetBird из `eGamesAPI/remnawave-reverse-proxy` (MIT, Copyright (c) 2025 eGames). Код скрипта не переносился: шаги свои, из закрытого списка мастера ([DEPLOYMENT_AGENT](DEPLOYMENT_AGENT.md)).

## 1. WARP Native

Выход трафика ноды через Cloudflare WARP — для сайтов, которые не открываются с адреса сервера.

**На сервере** (модуль «WARP Native», шаг `node_module`, скрипт `rw_steps.WARP`):

1. Ставит `wireguard-tools` из репозитория дистрибутива.
2. Скачивает `wgcf` (ViRb3/wgcf, MIT). Версию и SHA-256 файла магазин берёт из GitHub при составлении плана; на сервере файл с другой суммой не ставится.
3. `wgcf register --accept-tos`, затем `wgcf generate`. Регистрация создаёт учётную запись WARP, поэтому план составляется только после галочки «Я принимаю условия Cloudflare WARP».
4. Пишет `/etc/wireguard/warp.conf`: `Table = off` (маршруты сервера не меняются), без DNS. Если IPv6 на сервере выключен, адреса IPv6 убираются.
5. Включает `wg-quick@warp` и проверяет выход: `curl --interface warp https://www.cloudflare.com/cdn-cgi/trace` должен вернуть `warp=on` или `warp=plus`.

Выключение останавливает интерфейс и удаляет конфигурацию. Учётная запись wgcf остаётся в `/opt/remnawave-warp`, чтобы повторное включение не регистрировало новую.

**В профиле** («Расширения Remnawave → WARP в профиле», `POST /api/admin/rw/extensions/profiles/{uuid}/warp`):

- исходящий `warp-out` (`freedom`, `sockopt.interface = warp`);
- правило: выбранные домены (или `geosite:…`) идут в `warp-out`.

Повторный запуск заменяет свои исходящий и правило, «Убрать WARP» удаляет их. Остальная конфигурация профиля не меняется.

В отличие от скрипта eGames, мастер не запускает чужой установочный скрипт (`distillium/warp-native`) от root: шаги WARP — свой закрытый скрипт с проверкой SHA-256.

## 2. NetBird

Частная сеть WireGuard между серверами (NetBird Cloud или свой сервер управления).

1. В консоли NetBird создайте ключ установки (Setup key).
2. «Модули серверов → NetBird → Включить»: выберите серверы, введите ключ и, если сервер управления свой, его адрес `https://…`.
3. План ставит пакет `netbird` из подписанного репозитория `pkgs.netbird.io`, как в официальной документации: ключ репозитория загружается по HTTPS в `/usr/share/keyrings/netbird-archive-keyring.gpg`, apt проверяет подписи пакетов. Затем выполняется `netbird up`, и шаг проверяет `Management: Connected`.

**Ключ установки** хранится в зашифрованных секретах задачи до запуска. На сервер он передаётся через stdin (переменная `NB_SETUP_KEY`), в аргументы команды и в файлы не попадает. После шага ключ удаляется. В плане, журнале и ответах API ключа нет.

«Выключить» выполняет `netbird down`: пакет остаётся, сервер выходит из сети.

## 3. Права и журнал

Модули запускает право `provision_nodes`: план, затем подтверждение по SHA-256 плана. Журнал — `rw.installation.planned` и `rw.installation.approved`; изменения профиля — `rw.profile.warp`.

## 4. Проверено

| Что | Тест | Статус |
| --- | --- | --- |
| План, SHA-256 wgcf, галочка условий WARP, ключ NetBird только в stdin | `tests/test_rw_node_modules.py` | PASS |
| `warp-out` и правило в профиле, замена, удаление | `tests/test_rw_extensions.py::test_warp_outbound_in_a_profile` | PASS |
| WARP на настоящем сервере | нужно согласие владельца с условиями Cloudflare WARP | BLOCKED_EXTERNAL |
| NetBird на настоящем сервере | нужен ключ установки NetBird | BLOCKED_SECRETS |
