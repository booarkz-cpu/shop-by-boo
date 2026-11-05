# Выпуск v28.77.0 — этап 18, часть 1: подпись Android, ссылки на APK, адрес магазина в приложениях, управление Remnawave, тест встроенного VPN

Дистрибутив: `v28.77.0`. Runtime/API: `21.5.1`. Head магазина: `0093_ssh_key_rotation` (миграций нет). Support Pro: `0008` / 3.8.

## Что сделано

**Android: подпись и ссылки**
- Выпускные APK (apksigner) и AAB (jarsigner, keytool) сверяются с отпечатком сертификата ключа `corgi` из `mobile/android-signing-cert.sha256`. Чужой ключ или его отсутствие — ошибка сборки.
- В каждом выпуске есть подписанные `corgi-lusi-android.apk` и `corgi-lusi-android-admin.apk` с `.sha256`. Ссылки `https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/…` всегда ведут на последний выпуск. Они стоят в README, Wiki «Приложения» и инструкции установки в кабинете — раньше там была мёртвая ссылка на сборки 2.10.0 старого репозитория.

**Адрес API не вводится** ([MOBILE_API](new/MOBILE_API.md#адрес-магазина-вшит-в-сборку-с-v28770))
- Адрес берётся из переменной репозитория `CORGI_SHOP_URL` или из `mobile/shop-url.txt` и вшивается в сборку всех четырёх приложений.
- В клиенте нет поля адреса; в админке новый профиль уже заполнен.
- Если адрес не задан, поле остаётся, а адрес по-прежнему приходит из ссылки входа от бота или кабинета.

**Remnawave из админки** (идеи eGamesAPI/remnawave-reverse-proxy, MIT)
- «Журналы контейнеров» — последние 200 строк каждого контейнера установки, пароли и токены заменены на `***`.
- «Перезапустить», «Запустить», «Остановить» — файлы и данные не меняются. Ноды останавливаются раньше панели.
- Записи A у Bunny DNS и Gcore DNS, как у Cloudflare ([SUBSCRIPTION_DOMAIN](new/SUBSCRIPTION_DOMAIN.md#5-записи-dns-через-cloudflare)). Ключ Gcore уходит только на `api.gcore.com`.
- Страница подписки Orion (legiz-ru/Orion, MIT): выбор при установке или кнопкой. Файл закреплён по коммиту и SHA-256 и монтируется только для чтения.

**Тесты**
- Встроенный VPN Android на эмуляторе (`android-vpn-e2e.yml`, [CI_CD](new/CI_CD.md#встроенный-vpn-android-на-эмуляторе-с-v28770)). Без VPN проверочная страница недоступна; с VPN открывается только через туннель Xray; после отключения снова недоступна.
- Основной сценарий: подписка истекла — новая оплата возвращает доступ с сегодняшнего дня; возврат денег блокирует — следующая покупка разблокирует. Каждая оплата продлевает ровно один раз. Проверено на поддельной панели, которая следует контракту Remnawave, и теми же вызовами на живой панели.

**Исправлено**
- «Документы»: загрузка баннера сразу после «Сохранить» молча терялась, открытый документ мог переключиться обратно. Это и было причиной нестабильного e2e-теста.
- Счётчики «Чеки в налоговую», «Рост», «Приложения: аналитика»: подпись теперь над числом, карточки собраны в сетку. Все скриншоты пересняты, README показывает актуальные.

## Проверка

| Что | Где | Статус |
| --- | --- | --- |
| Подпись Android ключом `corgi` | выпуск v28.76.0 (`*.apk.certificate.txt`), проверка в `scripts/build-android-apk.sh` | PASS |
| Встроенный VPN Android | `android-vpn-e2e.yml` на эмуляторе | PASS (CI) |
| Продление, блокировка, разблокировка | `tests/test_integration_billing_vpn.py`, `tests/live/test_remnawave_live.py` | PASS (CI, живая панель) |
| Журналы и управление контейнерами | `tests/test_rw_installer.py` | PASS (CI) |
| DNS Bunny и Gcore | `tests/test_subscription_portal.py` | PASS (CI); с настоящими ключами — BLOCKED_SECRETS |
| Orion | `tests/test_rw_node_modules.py` | PASS (CI) |
| Ссылки на APK, адрес в сборке | `tests/test_download_links.py`, `tests/test_baked_shop_url.py` | PASS (CI) |
| Push Android, iOS, VPN на настоящей ноде | — | BLOCKED_EXTERNAL |

## Обновление

```bash
cd /opt/vpn-shop && bash scripts/backup.sh
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.77.0 bash /opt/vpn-shop/scripts/update-from-github.sh
```

Чтобы приложения собирались с вашим адресом API, задайте переменную репозитория `CORGI_SHOP_URL` (Settings → Secrets and variables → Actions → Variables).
