# Android and iOS apps

**Download:** [Android customer app](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-android.apk) · [Android admin app](https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-android-admin.apk) — always the latest release.

| | Android | iOS |
| --- | --- | --- |
| Customer app | Kotlin, Jetpack Compose, built-in VPN (Xray-core) | SwiftUI, Swift 6, Network Extension (Xray-core) |
| Admin app | Kotlin | SwiftUI |
| Sign-in | password, passkey, Telegram, Yandex, VK, Google, a link from the bot | the same |
| Builds | in CI only | in CI only (macOS) |

- Screens, banners and buttons come from the admin panel: «Приложения: экраны и кнопки».
- Reserve API addresses are signed with the shop's key: the app moves to a mirror by itself when the main address is blocked.
- Signed builds need the owner's keys (Android keystore, Apple certificates and the Network Extension entitlement).

More (Russian): [mobile API](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/MOBILE_API.md), [Android](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/ANDROID_ARCHITECTURE.md), [iOS](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/IOS_ARCHITECTURE.md), [VPN engine choice](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/VPN_ENGINE.md).
