# iOS: клиентское приложение и расширения

Каталог `mobile/ios-user` (SwiftUI, iOS 16+). Bundle ID `shop.remnawave.user`. Инструкция владельцу — [модуль 16](../ru/modules/16-mobile-apps.md). Админ-приложение — `mobile/ios-admin`.

## Цели проекта

| Цель | Тип | Bundle ID | Встроена по умолчанию |
| --- | --- | --- | --- |
| `VpnShopUser` | приложение | `shop.remnawave.user` | — |
| `VpnShopUserUITests` | UI-тесты (XCUITest) | `shop.remnawave.user.uitests` | — |
| `CorgiTunnel` | Network Extension (packet tunnel) | `shop.remnawave.user.tunnel` | нет |
| `CorgiNotificationService` | Notification Service Extension | `shop.remnawave.user.push` | нет |

Расширения лежат в проекте, но не встроены в приложение: каждое — отдельный App ID с собственным профилем, а packet tunnel требует разрешения Network Extension, которое Apple выдаёт команде по запросу. Обычная сборка и её подпись не меняются. `scripts/ios/enable-extensions.py` встраивает их, когда у владельца есть профили.

```mermaid
flowchart LR
    APP["VpnShopUser.app"] -->|"NETunnelProviderManager"| TUN["PlugIns/CorgiTunnel.appex"]
    APP -.->|"App Group group.shop.remnawave.user<br/>сервер, обход РФ, ошибка, список серверов"| TUN
    APNS["APNs: mutable-content, image"] --> NSE["PlugIns/CorgiNotificationService.appex"]
    NSE -->|"картинка во вложении"| UN["Центр уведомлений"]
```

## Приложение

- **Макет из админки** (`LayoutUI.swift`, `GET /api/mobile/layout`), встроенный стандартный макет и баннеры; тексты ru/en/uk.
- **ShopClient** (`VpnShopUserApp.swift`): `X-Shop-Client: ios-user`, проверка пинов SPKI (`CorgiPins` / `CORGI_PINS`) в делегате сессии, DeviceCheck при обмене кода на сессию. Сессия — в Keychain.
- **Ссылки** `corgi://login` и `corgi://payment` (`onOpenURL`): вход по одноразовому коду и возврат после оплаты с проверкой статуса заказа.
- **Push**: `PushCenter` регистрирует категории (кнопки) по стилю push из `GET /api/mobile/push-style`; нажатие открывает раздел.
- **«Подключить»**: если сборка встраивает туннель (`CorgiTunnelEnabled = YES` в Info.plist из настройки `CORGI_TUNNEL`), запускается `CorgiTunnelManager`; иначе подписка передаётся в Happ, v2RayTun или Streisand (`VpnClients`).

## Встроенный VPN: CorgiTunnel

```mermaid
sequenceDiagram
    participant App as Приложение
    participant M as NETunnelProviderManager
    participant T as CorgiTunnel (PacketTunnelProvider)
    participant SUB as Подписка (Remnawave)
    participant X as Xray-core (LibXray)
    participant H as hev-socks5-tunnel
    App->>M: сохранить конфигурацию {subscription}, загрузить снова, startVPNTunnel
    M->>T: startTunnel
    T->>SUB: GET ссылка подписки
    SUB-->>T: share-ссылки
    T->>T: CorgiXray.parseAll, CorgiXray.config (SOCKS 127.0.0.1:10808)
    T->>T: setTunnelNetworkSettings (198.18.0.1/24, IPv6, DNS 1.1.1.1, маршрут по умолчанию)
    T->>X: Invoke {method: runXray, payload: {xrayJson}}
    T->>H: hev_socks5_tunnel_main_from_str(yaml, fd utun) в отдельном потоке
    T-->>M: туннель поднят
    App->>T: sendProviderMessage("reload") — после смены сервера или обхода
```

- `Shared/CorgiXray.swift` компилируется в приложение и расширение: share-ссылки vless, vmess, trojan, shadowsocks (Reality, TLS; tcp, ws, grpc, xhttp, httpupgrade) → outbounds; «Авто» — observatory и балансировщик leastPing, или выбранный сервер; локальные сети и по желанию российские сайты идут напрямую. Правила те же, что на Android.
- Дескриптор utun берётся из `packetFlow` (старые iOS) или поиском управляющего сокета `com.apple.net.utun_control`.
- Без `LibXray.xcframework` и `HevSocks5Tunnel.xcframework` расширение компилируется (`#if canImport`) и отказывается запускаться с понятным сообщением.
- Ошибка запуска записывается в App Group (`vpn_error`), приложение показывает её клиенту.
- Память расширения ограничена iOS (до 50 МБ): Xray запускается с одним SOCKS-входом, без геобаз.

Лицензии: libXray — MIT, Xray-core — MPL-2.0, hev-socks5-tunnel — MIT ([THIRD_PARTY_NOTICES](../../THIRD_PARTY_NOTICES.md)).

## Push с картинками: CorgiNotificationService

APNs-сообщение стилизованного push (`push.py send_apns`) несёт `mutable-content: 1`, категорию с кнопками, `thread-id` и адрес картинки `image`. Расширение скачивает картинку (только https, jpeg/png/gif/webp, до 10 МБ) и прикладывает её. При любой ошибке или по окончании времени iOS уведомление показывается как пришло.

## Подпись и встраивание

```mermaid
flowchart TB
    S1["Секреты: IOS_CERTIFICATE_*, IOS_TEAM_ID, IOS_USER_PROFILE_BASE64"] --> SIGN["scripts/build-ios-signed.sh"]
    S2["IOS_USER_PUSH_PROFILE_BASE64 (по желанию)"] --> SIGN
    S3["IOS_USER_TUNNEL_PROFILE_BASE64 (по желанию,<br/>профиль с packet-tunnel-provider)"] --> SIGN
    F["scripts/ios/build-tunnel-frameworks.sh<br/>LibXray + HevSocks5Tunnel из закреплённых ревизий"] --> EN
    SIGN --> EN["scripts/ios/enable-extensions.py --push / --tunnel<br/>--profile app=… push=… tunnel=…"]
    EN --> ARCH["xcodebuild archive (профиль на каждую цель)"]
    ARCH --> IPA["corgi_lusi_ios_user_…_signed.ipa"]
```

`enable-extensions.py`:

- добавляет фазу «Embed App Extensions» и зависимости целей;
- для туннеля — `CORGI_TUNNEL = YES`, права Network Extension и App Group в `VpnShopUser.entitlements`, линковку фреймворков из `mobile/ios-user/Frameworks`;
- для ручной подписи — `PROVISIONING_PROFILE_SPECIFIER` в каждой цели (профиль в командной строке применился бы ко всем целям);
- повторный запуск ничего не меняет.

Профиль туннеля проверяется: в нём должно быть `packet-tunnel-provider`.

## Проверки

| Что | Где |
| --- | --- |
| Сборка приложения | CI «iOS • ios-user PKCE build» |
| UI-тесты | `VpnShopUserUITests`, CI «iOS • UI tests» (демо-режим `-CorgiDemo -CorgiTab …`) |
| Расширения и движок | CI «iOS • tunnel and rich push extensions»: собирает фреймворки (кэш по скрипту), встраивает оба расширения, проверяет, что они в `PlugIns` и движок слинкован |
| Скриншоты | workflow «Mobile screenshots» |

Работу туннеля нужно проверить на реальном iPhone с подписанной сборкой: симулятор не поднимает Network Extension.
