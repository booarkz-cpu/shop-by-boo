# Лицензия проекта и сторонние компоненты

Авторский код магазина распространяется по **Corgi Lusi VPN Shop Source License 2.9** из [LICENSE](LICENSE). Собственный коммерческий VPN-магазин разрешён без отдельного согласия. Условия распространения исходников, самостоятельного продукта и контейнерных образов остаются в пункте 3 лицензии. Этот проект не объявляется MIT/AGPL и не объявляется полностью перенесённым.

Лицензия проекта не заменяет лицензии зависимостей. При распространении собранных приложений/образов сохраните корневой LICENSE, уведомления об авторских правах и тексты лицензий реально включённых библиотек. При внутренней сборке используйте зафиксированные версии и включайте notices в доступный получателю раздел приложения/пакета. Публичная поставка конкретного бинарника требует сверки его фактического состава; эта таблица не сертификат всех транзитивных зависимостей.

## Где зафиксирован состав

| Контур | Источник состава |
| --- | --- |
| Backend и бот | `backend/requirements.txt`; тестовые зависимости отдельно в `backend/requirements-test.txt` |
| Кабинет / общий Mini App | `cabinet/package-lock.json`; тестовые пакеты в devDependencies |
| Админка | `admin/package-lock.json` |
| Отдельная оболочка Mini App | `miniapp/package-lock.json` |
| Support Pro | `support-pro/requirements.txt`, `requirements-dev.txt` |
| Android | Gradle-конфигурация каждого приложения и разрешённый граф runtime-зависимостей сборки |
| iOS | Swift Package Manager / package resolution конкретного приложения |
| Docker | Закреплённые базовые образы, их пакеты ОС и зависимости приложения |
| Баннеры бота и Mini App | Шрифт Roboto Condensed (SIL OFL 1.1, `scripts/bot-banners/fonts/OFL-RobotoCondensed.txt`) в генераторе `scripts/bot-banners/render.py`; стикеры корги Люси — авторские иллюстрации проекта (`scripts/bot-banners/source/stickers/`) |

Поле `license` в lock-файле помогает составить список, но не заменяет полный LICENSE/COPYING установленного пакета. Проверяйте пакет из закреплённой версии, сохраняйте полный текст и copyright, а не только короткое имя лицензии. Установленные в тестовой среде версии не обязательно совпадают с production lock-файлом.

## Проекты для функционального сравнения

Четыре указанных проекта исследованы как функциональные ориентиры. Их реализация не включена в новую переработку: новые возможности написаны внутри текущего ядра. Проверенные снимки и указанные авторами лицензии перечислены в [матрице покрытия](docs/ru/WORKSPACE_COVERAGE.md). Рекламные ссылки и внешнее брендирование в пользовательский интерфейс не добавляются. Если в будущем добавляется код, изображение или другой материал извне, сначала зафиксируйте происхождение, точную редакцию лицензии и требуемые уведомления; не назначайте ему лицензию магазина автоматически.

## Порядок выпуска

1. Соберите релиз из проверенного тега, без серверных `.env` и ключей подписи.
2. Зафиксируйте dependency graph и тексты лицензий именно включённых пакетов.
3. Поместите LICENSE и notices рядом с архивом/образом или в разделе приложения, доступном получателю.
4. Проверьте права на собственные логотипы, домены и изображения; разрешение на код не передаёт чужие товарные знаки.
5. Для APK/IPA отдельно сохраните сведения о native/VPN библиотеках и подписи. В alpha.4 новые подписанные APK/IPA не опубликованы.

Запуск магазина и лицензия не подтверждают полноту переноса, работоспособность внешней кассы или готовность production. Эти проверки описаны отдельно в руководстве по выпуску.

## Alpha.7

Сервер WebAuthn использует `webauthn==3.0.1` (py_webauthn, BSD-3-Clause); браузерные тесты — `@playwright/test==1.63.0` (Apache-2.0). Сохраните их полные license/copyright notices при распространении зависимостей. Эти библиотеки не перелицензируются лицензией магазина. Нативный WebAuthn API браузера используется без копирования стороннего JS verifier. Новые модули интеграции и мониторинга написаны в этом репозитории.

## UI дистрибутива v28.113.0

shadcn-совместимые компоненты используют Radix Tooltip, DropdownMenu, Select и Slot, Tailwind CSS, `class-variance-authority`, `clsx` и `tailwind-merge` (MIT). Иконки `lucide-react` сохраняют ISC-лицензию. Версии закреплены в `admin/package-lock.json`; тексты лицензий новых прямых зависимостей сохранены в [admin/THIRD_PARTY_LICENSES.txt](admin/THIRD_PARTY_LICENSES.txt). Это дополняет требования сохранения уведомлений всех реально включённых транзитивных зависимостей.

## Карта стран (с v28.42.0)

`admin/src/worldMap.json` — контуры стран из Natural Earth 1:110m Admin 0 Countries (https://www.naturalearthdata.com, общественное достояние). Магазин хранит упрощённые пути SVG в равнопромежуточной проекции без Антарктиды. Пути получены скриптом `scripts/geo/natural-earth-to-svg.py`.

## Встроенный VPN-движок Android (с v28.32.0, приложение 3.1.0)

Сборки клиентского приложения Android с встроенным VPN включают `libv2ray.aar`. Библиотеку собирает `scripts/mobile/build-xray-aar.sh` из закреплённой ревизии исходников:

- [Xray-core](https://github.com/XTLS/Xray-core) — MPL-2.0;
- [AndroidLibXrayLite](https://github.com/2dust/AndroidLibXrayLite) — LGPL-3.0, обвязка gomobile, ревизия `76a6e2172210613fcb4aa32b6de55bcd9452ce43`;
- [golang.org/x/mobile](https://pkg.go.dev/golang.org/x/mobile) — BSD-3-Clause.

Библиотека лежит в APK отдельным файлом (`libgojni.so`) и подключается к приложению без статической линковки, поэтому её можно заменить, как требует LGPL. При распространении APK приложите тексты MPL-2.0 и LGPL-3.0 и ссылку на исходники закреплённой ревизии. Код sing-box (GPL-3.0) в приложение не включается: GPL несовместима с коммерческой лицензией приложения. Сборка без `libv2ray.aar` подключается через Happ, v2rayNG или Hiddify и сторонних VPN-библиотек не содержит.

## Встроенный VPN-движок iOS (v28.34.0)

Сборки клиентского приложения iOS со встроенным VPN (расширение `CorgiTunnel`, включается `scripts/ios/enable-extensions.py`) связывают две библиотеки, собранные `scripts/ios/build-tunnel-frameworks.sh` из закреплённых ревизий:

- [libXray](https://github.com/XTLS/libXray) — MIT, ревизия `756ef80f41903eaf7bbeeb38a0a1f802ec204464`, обвязка gomobile над [Xray-core](https://github.com/XTLS/Xray-core) — MPL-2.0;
- [hev-socks5-tunnel](https://github.com/heiher/hev-socks5-tunnel) — MIT, ревизия `55cc2efc280f3a72ffc60ce856772b57f5122e9c` (вместе с lwIP — BSD-3-Clause, libyaml — MIT, hev-task-system — MIT).

Файлы MPL-2.0 Xray-core остаются под MPL-2.0: при распространении приложения приложите текст MPL-2.0 и ссылку на исходники ревизии. Сборка без расширения передаёт подписку в Happ или v2RayTun и этих библиотек не содержит.


## Remnawave: идеи модулей и шаблон страницы подписки (с v28.69.0)

- [eGamesAPI/remnawave-reverse-proxy](https://github.com/eGamesAPI/remnawave-reverse-proxy) — MIT, Copyright (c) 2025 eGames. Использованы идеи модулей: расширения ноды, правила подписки, WARP, IPv6, NetBird, Xray Checker, DNS-записи (Cloudflare, Bunny, Gcore), управление панелью, защита панели cookie. Код написан заново в мастере установки магазина.
- [legiz-ru/Orion](https://github.com/legiz-ru/Orion) — MIT, Copyright (c) 2025 legiz-ru. Шаблон страницы подписки Remnawave (v28.77.0). Не входит в дистрибутив: мастер скачивает `index.html` закреплённого коммита `d232def6a6c11e37aeeb76ebfb1ee8eb5eb8b5bd`, сверяет SHA-256 и записывает на сервер страницы подписки только по выбору администратора.
- [tinyauthapp/tinyauth](https://github.com/tinyauthapp/tinyauth) — GPL-3.0. Портал входа перед страницами панели Remnawave (v28.86.0). Не входит в дистрибутив и не связывается с кодом магазина: мастер установки запускает отдельный контейнер `ghcr.io/tinyauthapp/tinyauth:v5.2.0`, закреплённый по SHA-256, только по выбору администратора («Доступ к панели → Вход через TinyAuth»). Идея — модуль `tinyauth.sh` из eGamesAPI/remnawave-reverse-proxy (MIT, Copyright (c) 2025 eGames); конфигурация Caddy (`forward_auth`) написана для магазина.
- [zxing/zxing](https://github.com/zxing/zxing) core 3.5.3 — Apache-2.0. Рисование QR-кода подписки в приложении «Корги Люси: клиент» (v28.86.0).
- Google code scanner (`play-services-code-scanner`) — условия Google Play services. Сканирование QR без разрешения камеры в приложении «Корги Люси: клиент»; код в дистрибутив не входит, подключается из Google Maven при сборке.

## Сводная таблица: что взято извне и на каких условиях (редакция лицензии 2.9, 2026-11-07)

`tests/test_license_notices.py` проверяет, что каждый проект, на который ссылается код магазина как на источник («after …», «MIT, (c) …»), есть в этой таблице, а `LICENSE` и `mobile/LICENSE` совпадают.

| Проект | Лицензия | Что взято | Как входит |
| --- | --- | --- | --- |
| [booarkz-cpu/remnawave-manager](https://github.com/booarkz-cpu/remnawave-manager) | MIT, © Корги Люси | Транспорты ноды, защита сервера, самовосстановление, сертификат Hysteria2, правила фаервола (v28.81–v28.84) | Код переписан шагами мастера установки (`backend/app/rw_steps.py`) |
| [eGamesAPI/remnawave-reverse-proxy](https://github.com/eGamesAPI/remnawave-reverse-proxy) | MIT, © 2025 eGames | Идеи модулей ноды, SelfSteal, защита панели, TinyAuth | Код написан заново |
| [legiz-ru/Orion](https://github.com/legiz-ru/Orion) | MIT, © 2025 legiz-ru | Шаблон страницы подписки | Скачивается мастером по выбору администратора, SHA-256 закреплён |
| [kutovoys/xray-checker](https://github.com/kutovoys/xray-checker) | MIT | Проверка серверов подписки | Отдельный контейнер, образ закреплён по digest |
| [9seconds/mtg](https://github.com/9seconds/mtg) | MIT | MTProto-прокси для Telegram на ноде (v28.94.0) | Отдельный контейнер, образ `nineseconds/mtg` v2.3.0 закреплён по digest |
| [Psiphon-Labs/psiphon-tunnel-core](https://github.com/Psiphon-Labs/psiphon-tunnel-core) | GPL-3.0 | Свой сервер Psiphon (psiphond) на ноде (v28.99.0) | Собирается на сервере владельца из закреплённого коммита в закреплённом образе Go; исходники и бинарник в репозитории магазина не хранятся |
| [runetfreedom/russia-v2ray-rules-dat](https://github.com/runetfreedom/russia-v2ray-rules-dat) | GPL-3.0 (данные) | Российские списки блокировок на нодах (v28.95.0) | Файлы скачиваются на сервер владельца из выпуска GitHub с проверкой SHA-256; в репозитории магазина их нет |
| [ViRb3/wgcf](https://github.com/ViRb3/wgcf) | MIT | Регистрация WARP на сервере | Бинарный файл выпуска скачивается на сервер, SHA-256 сверяется |
| [XTLS/Xray-core](https://github.com/XTLS/Xray-core) | MPL-2.0 | VPN-ядро приложений и нод | Библиотека в APK/IPA; на нодах — в образе Remnawave или выбранный выпуск |
| [XTLS/libXray](https://github.com/XTLS/libXray), [hev-socks5-tunnel](https://github.com/heiher/hev-socks5-tunnel) | MIT | VPN-расширение iOS | Связываются при сборке (см. выше) |
| [2dust/AndroidLibXrayLite](https://github.com/2dust/AndroidLibXrayLite) | LGPL-3.0 | Обвязка Xray для Android | Отдельная заменяемая библиотека (см. выше) |
| [remnawave/panel, node, subscription-page](https://github.com/remnawave) | AGPL-3.0 | Панель и ноды VPN | Не входят в дистрибутив: мастер запускает их официальные образы, закреплённые по digest, отдельными контейнерами на серверах владельца |
| [tinyauthapp/tinyauth](https://github.com/tinyauthapp/tinyauth) | GPL-3.0 | Вход перед панелью | Отдельный контейнер по выбору администратора |
| [runetfreedom/russia-v2ray-rules-dat](https://github.com/runetfreedom/russia-v2ray-rules-dat) | GPL-3.0 (данные) | geoip.dat / geosite.dat, в том числе список рекламы для «Блокировки рекламы» клиента | Не входят в приложение: скачиваются пользователем по кнопке |
| [pinterest/ktlint](https://github.com/pinterest/ktlint) | MIT | Проверка стиля кода клиента в CI | Только инструмент CI, в приложения не входит |
| remnawave-admin, bedolaga-cabinet | AGPL-3.0 | Только идеи интерфейса и функций | Кода нет |
| bedolaga-bot | Commons Clause | Только идеи функций | Кода нет |
