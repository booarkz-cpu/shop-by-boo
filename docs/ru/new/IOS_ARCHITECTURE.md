# iOS: архитектура

Подробное описание — [ios_architecture](../../modules/ios_architecture.md), инструкция владельцу — [модуль 16](../modules/16-mobile-apps.md).

| Цель | Что |
| --- | --- |
| `VpnShopUser` | клиент (SwiftUI, iOS 16+) |
| `CorgiTunnel` | Network Extension: Xray-core + hev-socks5-tunnel ([VPN_ENGINE](VPN_ENGINE.md)) |
| `CorgiNotificationService` | push с картинками |
| `VpnShopAdmin` | приложение администратора |

**Функции:** те же, что на Android ([ANDROID_ARCHITECTURE](ANDROID_ARCHITECTURE.md)). Сессия хранится в Keychain, SPKI-пины, DeviceCheck при входе.

**Swift 6.** Проект собирается в режиме Swift 5. Перевод на Swift 6 со строгой проверкой параллелизма — задача этапа 17. Состояние — в [IMPLEMENTATION_STATUS](IMPLEMENTATION_STATUS.md).

**Сборка — только в CI** (macOS):
- «iOS • PKCE build», «tunnel and rich push extensions», «UI tests»;
- подписанный IPA — с сертификатами владельца и разрешением Network Extension от Apple.
