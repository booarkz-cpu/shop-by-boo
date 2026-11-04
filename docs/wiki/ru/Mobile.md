# Приложения Android и iOS

| | Android | iOS |
| --- | --- | --- |
| Клиент | Kotlin, Jetpack Compose, встроенный VPN (Xray-core) | SwiftUI, Swift 6, Network Extension (Xray-core) |
| Админ | Kotlin | SwiftUI |
| Вход | пароль, passkey, Telegram, Яндекс, VK, Google, ссылка из бота | то же |
| Сборка | только в CI | только в CI (macOS) |

- Вид экранов, баннеры и кнопки приходят из админки: «Приложения: экраны и кнопки».
- Резервные адреса API подписаны ключом магазина: приложение переходит на зеркало само, если основной адрес заблокирован.
- Подписанные сборки — с ключами владельца (Android keystore, сертификаты Apple и разрешение Network Extension).

Подробно: [API приложений](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/MOBILE_API.md), [Android](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/ANDROID_ARCHITECTURE.md), [iOS](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/IOS_ARCHITECTURE.md), [выбор движка VPN](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/VPN_ENGINE.md).
