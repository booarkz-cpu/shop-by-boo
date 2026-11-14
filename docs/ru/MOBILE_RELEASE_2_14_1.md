# Мобильные клиенты 2.14.1

[Скачать сборки на GitHub](https://github.com/booarkz-cpu/shop-by-boo/releases/tag/mobile-v2.14.1).

Четыре приложения магазина: Android и iOS для покупателя и администратора. Сервер должен быть обновлён до **20.0.14**. Все проекты имеют версию **2.14.1**, номер сборки **2141** и новый вход с PKCE S256. После обновления войдите заново. Серверная версия и номер мобильного приложения независимы.

Это клиенты магазина и управления подписками. Встроенный VPN forwarding engine не реализован; для подключения используется импорт подписки во внешний VPN-клиент.

## Android

| Файл | Назначение |
| --- | --- |
| `corgi_lusi_android_user_2_14_1_preview.apk` | Покупатель, тестовая установка |
| `corgi_lusi_android_admin_2_14_1_preview.apk` | Администратор, тестовая установка |
| `*_release.apk` | Вместо preview, только если сборке предоставлен постоянный release-ключ |

Нужен Android 8.0 или новее. Скачайте APK нужной роли, разрешите установку из выбранного браузера/файлового менеджера и откройте файл. На экране входа укажите HTTPS-адрес **API** вашей установки (например, `https://api.example.com`), email и пароль; для администратора — также требуемый MFA-код. Домен админки/кабинета вместо API не подходит.

При отсутствии release-ключа workflow публикует **preview**: debug-подпись, отдельные package IDs `shop.remnawave.user.preview` и `shop.remnawave.admin.preview`, названия VPN Shop Preview / VPN Admin Preview. Эти приложения устанавливаются рядом с прежними и предназначены для тестового аккаунта/стенда. Ключ debug создаётся на временном CI runner и не сохраняется; следующая preview-сборка может потребовать удаления предыдущей preview. Основное приложение при этом удалять не нужно.

Production APK требует постоянного ключа владельца. В GitHub → Settings → Secrets and variables → Actions задайте `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`. Для обновления уже установленного production APK нужен **тот же** ключ подписи. Workflow не подменяет release-подпись debug-ключом. Отпечаток публичного сертификата и метаданные каждого APK опубликованы рядом в `.certificate.txt` и `.package.txt`; приватные ключи не публикуются.

## iOS

| Файл | Назначение |
| --- | --- |
| `corgi_lusi_ios_user_2_14_1_unsigned.ipa` | Покупатель, сборка arm64 для последующей подписи |
| `corgi_lusi_ios_admin_2_14_1_unsigned.ipa` | Администратор, сборка arm64 для последующей подписи |
| `*_simulator.zip` | Приложение для iOS Simulator на Mac |

Нужен iOS 16 или новее. **Unsigned IPA нельзя напрямую установить на iPhone.** Это готовый собранный пакет без Apple-подписи, не TestFlight/App Store-релиз. Для установки на физическое устройство нужны сертификат Apple и provisioning profile, соответствующие bundle ID и выбранному способу распространения. Эти данные не включены в репозиторий.

Для собственной подписанной сборки откройте `apps/vpn-shop/ios/VpnShopUser.xcodeproj` или `apps/lucy-admin/ios/VpnShopAdmin.xcodeproj` в Xcode. В Signing & Capabilities выберите свой Team, включите signing и задайте разрешённый Team bundle ID. В Build Settings измените `CODE_SIGNING_ALLOWED` с `NO` на `YES`. Выполните Product → Archive → Distribute App; способ распространения определяется вашим Apple Developer аккаунтом. Одна только перепаковка/переименование unsigned IPA не добавляет подпись.

Для симулятора распакуйте `*_simulator.zip`, загрузите совместимый iOS Simulator и выполните:

```sh
xcrun simctl install booted VpnShopUser.app
xcrun simctl launch booted shop.remnawave.user
```

Для администратора используйте `VpnShopAdmin.app` и `shop.remnawave.admin`.

## Проверка файлов и происхождения

Скачайте соседний `.sha256` вместе с приложением и выполните в одной директории:

```sh
sha256sum -c corgi_lusi_android_user_2_14_1_preview.apk.sha256
# macOS:
shasum -a 256 -c corgi_lusi_ios_user_2_14_1_unsigned.ipa.sha256
```

`SHA256SUMS` содержит все шесть бинарных пакетов. `BUILD.txt` указывает исходный commit и GitHub Actions run. Исходники доступны по тегу `mobile-v2.14.1`. Workflow `Mobile packages` проверяет обе платформы до публикации; существующие опубликованные бинарники автоматически не заменяются. Повторный запуск позволяет восстановить незавершённый draft, новый публичный выпуск требует нового тега/версии.

## Сборка из исходников

Android: JDK 17, Android SDK 35, Gradle wrapper из репозитория:

```sh
bash scripts/build-android-apk.sh "$PWD/dist/mobile"
```

Без `ANDROID_KEYSTORE` создаются preview APK. Для release дополнительно передайте путь к keystore и переменные `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD` через безопасное окружение.

iOS: macOS с Xcode:

```sh
bash scripts/build-ios-packages.sh "$PWD/dist/mobile"
```

Скрипт создаёт unsigned device IPA и simulator ZIP для обеих ролей. Подпись Apple выполняется отдельно владельцем аккаунта.

## Публикация в собственной витрине

Веб-админка → Приложения: загрузите проверенный APK/подписанный IPA в соответствующую карточку роли и платформы. Preview APK обозначайте как тестовый; unsigned IPA не выставляйте покупателям как устанавливаемое приложение. Загрузка GitHub Release не меняет карточки или файлы на вашем VDS автоматически.

Официальные инструкции: [Apple — распространение на зарегистрированные устройства](https://developer.apple.com/documentation/xcode/distributing-your-app-to-registered-devices), [Android — подпись приложений](https://developer.android.com/studio/publish/app-signing).
