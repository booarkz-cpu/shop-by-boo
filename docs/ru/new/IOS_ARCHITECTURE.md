# iOS: архитектура

Подробное описание — [ios_architecture](../../modules/ios_architecture.md), инструкция владельцу — [модуль 16](../modules/16-mobile-apps.md).

| Цель | Что |
| --- | --- |
| `VpnShopUser` | клиент (SwiftUI, iOS 16+) |
| `CorgiTunnel` | Network Extension: Xray-core + hev-socks5-tunnel ([VPN_ENGINE](VPN_ENGINE.md)) |
| `CorgiNotificationService` | push с картинками |
| `VpnShopAdmin` | приложение администратора |

**Функции:** те же, что на Android ([ANDROID_ARCHITECTURE](ANDROID_ARCHITECTURE.md)). Сессия хранится в Keychain, SPKI-пины, DeviceCheck при входе.

**Swift 6** (с v28.77.1). Оба приложения, расширения и UI-тесты собираются в режиме Swift 6; строгая проверка многопоточности замечаний не находит. Правила кода:
- состояние интерфейса (`PushCenter`, `BannerLoader`, `CorgiTunnelManager`) живёт на главном потоке (`@MainActor`); обратные вызовы системы переходят на него через `Task { @MainActor in … }`;
- сетевые вызовы блокирующие и выполняются в фоне; ответ из обратного вызова передаётся через `Handoff` — значение под замком;
- `ShopClient` неизменяем (`Sendable`): правила сессии (без перенаправлений, закрепление сертификата) — отдельный объект, сессия закрывается вместе с клиентом;
- общие статические данные — под `NSLock` (`nonisolated(unsafe)` только рядом с этим замком и с комментарием).

**Сборка — только в CI** (macOS):
- «iOS • PKCE build», «tunnel and rich push extensions», «UI tests»;
- подписанный IPA — с сертификатами владельца и разрешением Network Extension от Apple.
