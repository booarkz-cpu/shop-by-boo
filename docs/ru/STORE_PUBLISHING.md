# Публикация приложений в Google Play, RuStore и App Store (TestFlight)

Актуально для приложений 3.2.0 (дистрибутив v28.52.0). Всё, что можно подготовить в репозитории, уже лежит в `mobile/store/`. Загрузку в сторы делает владелец: нужны его аккаунты разработчика и ключи подписи. В репозиторий ключи не попадают.

## Что уже готово

| Что | Где |
| --- | --- |
| Иконки: 1024×1024 (App Store, RuStore), 512×512 (Google Play), иконка админ-приложения | `mobile/store/icons/` |
| Иконки приложений Android (mipmap) и iOS (AppIcon) | `mobile/android-*/app/src/main/res/mipmap-*`, `mobile/ios-*/*/Assets.xcassets` |
| Графический баннер Google Play 1024×500 | `mobile/store/google-play/feature-graphic.png` |
| Скриншоты в оформлении стора с подписями: Android 1080×1920, iPhone 6,9" 1320×2868 | `mobile/store/screenshots/{android,ios}/` |
| Название, краткое и полное описание (ru, en) | `mobile/store/google-play/{ru-RU,en-US}/` |
| Название, подзаголовок, описание, ключевые слова, промотекст, что нового (ru, en) | `mobile/store/app-store/{ru,en-US}/` |
| Описание для RuStore | `mobile/store/rustore/` |
| Сборка AAB для Google Play | `scripts/build-android-apk.sh` при заданном `ANDROID_KEYSTORE` |

Картинки пересобираются командой `python3 scripts/store/render.py` (нужны Pillow, NumPy и Playwright с Chromium). Скриншоты для них берутся из `screenshots/mobile/`: их снимает workflow «Mobile screenshots» в демо-режиме приложений.

## Перед сборкой

1. Вшейте адрес магазина, чтобы клиентам не пришлось вводить адрес API:
   - Android: `-Pcorgi.shop_url=https://api.example.com` или переменная `CORGI_SHOP_URL`;
   - iOS: настройка сборки `CORGI_SHOP_URL=https://api.example.com` в `xcodebuild`.
2. Push: Firebase для Android (`CORGI_FIREBASE_*`), APNs для iOS (`APNS_*` на сервере) — см. [PUSH_NOTIFICATIONS_CURRENT.md](PUSH_NOTIFICATIONS_CURRENT.md).
3. Схема ссылок `corgi://` уже зарегистрирована в обоих приложениях. Если меняете её, задайте ту же в `MOBILE_APP_SCHEME` на сервере.

## Google Play

1. Создайте ключ загрузки: `keytool -genkeypair -v -keystore upload.jks -alias corgi -keyalg RSA -keysize 4096 -validity 10000`. Храните его вне репозитория.
2. В GitHub → Settings → Secrets задайте `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`. Workflow «Mobile packages» соберёт подписанные APK и AAB.
3. Play Console → создайте приложение `shop.remnawave.user` и включите **Play App Signing**. Загрузите AAB во внутреннее тестирование.
4. Тексты и картинки возьмите из `mobile/store/google-play/`.
5. **Безопасность данных** (Data safety):
   - Собираются: адрес электронной почты (вход), идентификаторы пользователя аккаунта (сессия), история покупок (подписка).
   - Анонимная статистика: события приложения, без привязки к рекламе.
   - Шифрование при передаче: да. Удаление данных: по запросу в кабинете.
   - Рекламных идентификаторов нет.
6. **Политика VPN.** Сборка из «Mobile packages» включает встроенный VPN (`VpnService`, Xray-core). В Play Console заполните декларацию VpnService: основная функция — VPN-сервис по подписке, трафик шифруется до серверов магазина, данные пользователей не продаются, реклама в трафик не встраивается. Foreground service типа `systemExempted` используется только пока туннель включён. Сборка без `libv2ray.aar` туннель не поднимает: декларация для неё не нужна.
7. Рейтинг контента — анкета IARC (без насилия и азартных игр; розыгрыши бесплатные). Целевая аудитория — 18+.

## RuStore

1. Зарегистрируйтесь в RuStore Консоли как ИП, самозанятый или юрлицо.
2. Загрузите подписанный APK (тот же ключ, что для Google Play, или отдельный) из артефакта «mobile-android».
3. Иконка 512×512 — `mobile/store/icons/icon-512.png`. Скриншоты — `mobile/store/screenshots/android/`. Описание — `mobile/store/rustore/`.
4. RuStore проверяет приложения с VPN-функциями. Укажите, что приложение — клиент магазина подписок, а туннель поднимает сторонний клиент.

## App Store и TestFlight

1. В Apple Developer создайте идентификаторы `shop.remnawave.user` и `shop.remnawave.admin`. Подключите Push Notifications и Associated Domains (`applinks:<CORGI_ASSOCIATED_DOMAIN>`).
2. Создайте сертификат Apple Distribution и профили App Store. В GitHub Secrets задайте значения для `scripts/build-ios-signed.sh`: `IOS_CERTIFICATE_BASE64`, `IOS_CERTIFICATE_PASSWORD`, `IOS_USER_PROFILE_BASE64`, `IOS_ADMIN_PROFILE_BASE64`, `IOS_TEAM_ID`.
3. Workflow «Mobile packages» соберёт подписанный `.ipa`. Загрузите его через Transporter или `xcrun altool --upload-app` и выберите сборку в TestFlight.
4. Тексты и картинки — `mobile/store/app-store/` и `mobile/store/screenshots/ios/`.
5. **Экспортное соответствие.** Приложение использует только HTTPS (стандартное шифрование ОС): ответ «использует исключённое шифрование». Ключ `ITSAppUsesNonExemptEncryption = NO` можно добавить в Info.plist.
6. **Конфиденциальность** (App Privacy): e-mail и идентификатор пользователя связаны с аккаунтом; покупки связаны с аккаунтом; данные использования не связаны с личностью и не используются для отслеживания.
7. **Заметки для ревьюера.** Укажите тестовый аккаунт (почта и пароль) на рабочем магазине с активной подпиской. Объясните, что VPN-туннель включает выбранный клиент (Happ или v2RayTun).
8. Оплата цифровой подписки внутри iOS по правилам App Store идёт через In-App Purchase. Магазин поддерживает проверку покупок App Store на сервере (`APPLE_*`). Для других стран и способов оплаты действуют правила App Review 3.1.1 и 3.1.3.

## Проверка перед отправкой

- Иконки и скриншоты на месте; размеры проверяет `tests/test_store_assets.py`.
- Длины текстов не превышают лимиты сторов: название — 30 символов, краткое описание Google Play — 80, подзаголовок App Store — 30, ключевые слова — 100, промотекст — 170, полное описание — 4000.
- `versionCode`/`CURRENT_PROJECT_VERSION` = 3200, `versionName`/`MARKETING_VERSION` = 3.2.0. Каждое обновление в сторе требует большего `versionCode`/`CURRENT_PROJECT_VERSION`.
