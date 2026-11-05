# Выпуск v28.79.0 — этап 18, часть 3: третье Android-приложение «Корги Люси: клиент»

Дистрибутив: `v28.79.0`. Runtime/API: `21.5.1`. Head магазина: `0093_ssh_key_rotation` (миграций нет). Support Pro: `0008` / 3.8.

## Что сделано

**«Корги Люси: клиент»** ([описание](new/ANDROID_CLIENT_APP.md)) — отдельный VPN-клиент для любых подписок, не только магазина. Задача владельца: приложение по образцу INCY. У INCY нет открытого кода и лицензии, поэтому приложение написано с нуля на нашем движке Xray-core.

- Отдельное: свой `applicationId` `shop.corgi.client`, свой проект `mobile/android-client`, своя сборка в CI. Клиент магазина и админка не изменились.
- Скачать: [corgi-lusi-client.apk](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-client.apk) — подписан тем же ключом `corgi`, отпечаток сверяется при сборке.
- Подписки по ссылке, QR и «Поделиться», с автообновлением; несколько подписок.
- Протоколы VLESS (REALITY, TLS, Vision), VMess, Trojan, Shadowsocks, SOCKS5, WireGuard; транспорты tcp, ws, grpc, xhttp, httpupgrade. Hysteria2 и TUIC отмечаются как пропущенные — их нет в Xray-core.
- Полный JSON Xray: балансировщики, observatory, свои маршруты.
- Автовыбор самого быстрого сервера, проверка задержки.
- Маршруты: всё через VPN, кроме локальной сети, российские сайты напрямую, свои правила (домен, IP, `geosite:`, `geoip:`); свои geo-файлы по ссылке.
- Фрагментация TLS ClientHello, свои DNS, приложения через VPN (все, только выбранные, кроме выбранных).
- Kill switch через системные настройки Android, плитка быстрых настроек, Android TV, QR для переноса подписки на ТВ.
- Русский, английский, украинский; темы.

## Проверка

| Что | Где | Статус |
| --- | --- | --- |
| Разбор ссылок, подписок, правил, сборка конфигурации, JSON | JUnit в `mobile/android-client/app/src/test` | PASS (CI) |
| Сборки debug и release | `android-client.yml` | PASS (CI) |
| Импорт подписки, подключение, страница доступна только через туннель, отключение | `scripts/mobile/client-vpn-e2e.sh` на эмуляторе | PASS (CI) |
| Подпись выпускного APK ключом `corgi` | `mobile-release.yml` | Проверяется при выпуске |
| Настоящий телефон и ТВ | — | BLOCKED_EXTERNAL |

## Обновление

```bash
cd /opt/vpn-shop && bash scripts/backup.sh
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.79.0 bash /opt/vpn-shop/scripts/update-from-github.sh
```

На сервере магазина ничего не меняется: выпуск добавляет приложение.
