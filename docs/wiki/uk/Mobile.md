# Застосунки Android і iOS

**Завантажити:** [клієнт Android](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-android.apk) · [«Коргі Люсі: клієнт»](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-client.apk) · [адмінка Android](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-android-admin.apk) — завжди останній випуск.

| | Android | iOS |
| --- | --- | --- |
| Клієнт | Kotlin, Jetpack Compose, вбудований VPN (Xray-core) | SwiftUI, Swift 6, Network Extension (Xray-core) |
| Адмін | Kotlin | SwiftUI |
| Вхід | пароль, passkey, Telegram, Яндекс, VK, Google, посилання з бота | те саме |
| Збірка | лише в CI | лише в CI (macOS) |

- Вигляд екранів, банери й кнопки приходять з адмінки: «Приложения: экраны и кнопки».
- Резервні адреси API підписані ключем магазину: застосунок сам переходить на дзеркало, якщо основну адресу заблоковано.
- Підписані збірки — з ключами власника (Android keystore, сертифікати Apple і дозвіл Network Extension).

Докладніше (російською): [API застосунків](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/MOBILE_API.md), [Android](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/ANDROID_ARCHITECTURE.md), [iOS](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/IOS_ARCHITECTURE.md), [вибір рушія VPN](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/VPN_ENGINE.md).
