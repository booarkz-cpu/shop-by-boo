> Актуальная инструкция дистрибутива v28.18.0. Runtime/API `21.5.1`, head магазина `0072_traffic_analysis`, Support Pro `0008`.

# 16. Мобильные приложения

## Для чего

В репозитории есть исходники четырёх приложений:

| Приложение | Каталог |
| --- | --- |
| Android для клиентов | `mobile/android-user` |
| iOS для клиентов | `mobile/ios-user` |
| Android для администраторов | `mobile/android-admin` |
| iOS для администраторов | `mobile/ios-admin` |

Клиентское приложение показывает подписку, тарифы, кошелёк, подарки и промокоды, поддержку, push-уведомления. На Android есть виджет со статусом подписки, вход возможен по ключу доступа (passkey). Сам VPN-туннель обеспечивает сторонний клиент (Happ, v2rayNG и другие) по ссылке подписки.

Готовых подписанных APK/IPA в выпуске нет: каждый владелец собирает и подписывает приложения своими ключами. Файл `mobile-production-status.json` в выпуске GitHub показывает фактический статус сборок.

## Где и кто

| Раздел | Что делает | Права |
| --- | --- | --- |
| **Бот и кабинет → Android и iOS** | Для клиента и для администратора: показывать или нет, название RU/EN, текст RU/EN, ссылка (стор или прямая), файл приложения; логотип для кабинета и приложений; скачать приложение администратора | `manage_content` |
| Кабинет → «Приложения» | Клиент скачивает опубликованные приложения | клиент |

## Сборка

**Адрес магазина.** Приложение спрашивает «Адрес API» при первом входе. Клиент вводит `https://api.ДОМЕН`. Пересобирать приложение под каждый магазин не нужно, но распространять его вы будете под своей подписью.

**Android** (Linux/macOS, Android SDK 35, JDK):

```bash
export ANDROID_HOME=$HOME/android-sdk
# release-подпись своим ключом; без ANDROID_KEYSTORE собирается debug
export ANDROID_KEYSTORE=/secure/release.jks ANDROID_KEYSTORE_PASSWORD=... ANDROID_KEY_ALIAS=... ANDROID_KEY_PASSWORD=...
bash scripts/build-android-apk.sh "$PWD/dist/mobile"
```

Для push передайте данные Android-приложения своего Firebase-проекта переменными `CORGI_FIREBASE_APP_ID`, `CORGI_FIREBASE_API_KEY`, `CORGI_FIREBASE_PROJECT_ID`, `CORGI_FIREBASE_SENDER_ID` (или свойствами Gradle `corgi.firebase.*`) — [модуль 12](12-notifications-push.md). Debug-сборка получает пакет `shop.remnawave.user.preview`.

**iOS** (macOS, Xcode): подпись профилем своего Apple Developer-аккаунта:

```bash
CORGI_ASSOCIATED_DOMAIN=cabinet.ДОМЕН bash scripts/build-ios-signed.sh "$PWD/dist/mobile"
```

`CORGI_ASSOCIATED_DOMAIN` нужен для ключей доступа. В App ID включите Associated Domains и Push Notifications.

Ключи подписи и профили храните вне репозитория, не коммитьте их.

## Публикация

1. **Android и iOS** → карточка «Покупатель»: включите «Показывать», заполните названия и тексты на двух языках.
2. Загрузите файл (APK) или укажите HTTPS-ссылку на стор или TestFlight.
3. «Сохранить приложения». Кабинет показывает карточку и контрольную сумму файла.
4. Загрузка IPA его не подписывает: распространять iOS-приложение можно только подписанным.

## Ключи доступа в приложениях

В `.env`:

```dotenv
CUSTOMER_WEBAUTHN_ORIGIN=https://cabinet.ДОМЕН
ANDROID_USER_PACKAGE=shop.remnawave.user
ANDROID_USER_CERT_SHA256=AB:CD:...:EF        # отпечаток ключа подписи; при Google Play — ключ Play App Signing
IOS_USER_APP_ID=TEAMID.shop.remnawave.user   # пусто — из APNS_TEAM_ID и APNS_BUNDLE_ID
```

Отпечаток своего ключа: `keytool -list -v -keystore release.jks -alias ALIAS | grep SHA256`.

После перезапуска backend кабинет отдаёт `/.well-known/assetlinks.json` и `/.well-known/apple-app-site-association`. Функция `passkeys` должна быть включена.

## Виджет Android

Клиент добавляет виджет «VPN Shop» на рабочий стол и включает «Показывать подписку на виджете» во вкладке «Безопасность» приложения. На виджете видны:

- название тарифа и состояние подписки;
- дата окончания;
- остаток трафика;
- число непрочитанных уведомлений.

Ссылка подписки, балансы и email на виджет никогда не попадают. Обновление — раз в 30 минут.

## Проверка

1. Установите собранное приложение, введите `https://api.ДОМЕН`, войдите тестовым клиентом: видны подписка и тарифы.
2. Проверьте доступность файлов привязки:
   - `curl -fsS https://cabinet.ДОМЕН/.well-known/assetlinks.json`;
   - `curl -fsS https://cabinet.ДОМЕН/.well-known/apple-app-site-association`.
3. Добавьте ключ доступа и войдите им.
4. Включите push и получите тестовое уведомление.

## Проблемы

| Симптом | Причина | Что делать |
| --- | --- | --- |
| «Не удалось подключиться» к API | Неверный адрес или нет HTTPS | Вводите `https://api.ДОМЕН` |
| Вход по ключу: «не настроено» (503) | Пустые `ANDROID_USER_CERT_SHA256` / `IOS_USER_APP_ID` | Задайте и перезапустите backend |
| На Android ключ не находится | Отпечаток не совпадает с ключом, которым подписано приложение | Возьмите отпечаток ключа Play App Signing, если подписывает Google |
| Оплата в приложении | Встроенная оплата Apple и Google отключена (410) | Оплата идёт через платёжных агентов магазина |

## API

`GET|PUT /api/admin/apps`, `POST|DELETE /api/admin/apps/{id}/file`, `POST|DELETE /api/admin/apps/logo`, `GET /api/admin/mobile/ops`. Клиент: `POST /api/auth/mobile/token`, `GET /api/me/widget`, `/.well-known/assetlinks.json`, `/.well-known/apple-app-site-association`.

## Подробнее

[Android и iOS: установка и подключение](../MOBILE_GUIDE.md) · [Ключи доступа в приложениях](../NATIVE_PASSKEYS_CURRENT.md) · [Виджет и профили](../WIDGET_AND_PROFILES_CURRENT.md) · [Push](../PUSH_NOTIFICATIONS_CURRENT.md).
