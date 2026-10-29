> Актуальная инструкция дистрибутива v28.51.0. Runtime/API `21.5.1`, head магазина `0085_loyalty`, Support Pro `0008`.

# Ключи доступа в приложениях Android и iOS

Клиент входит в приложение магазина отпечатком пальца, лицом или PIN-кодом устройства — без пароля. Это те же ключи доступа (passkeys), что и в [веб-кабинете](CUSTOMER_PASSKEYS_CURRENT.md): ключ, добавленный в браузере, работает в приложении той же платформы, и наоборот, если менеджер паролей устройства синхронизирует ключи.

- Android — Credential Manager (Android 9 и новее; на Android 9–13 через сервисы Google Play).
- iOS — AuthenticationServices (iOS 16 и новее, связка ключей iCloud).

## Как это работает

Владелец ключа (relying party) — домен личного кабинета из `CUSTOMER_WEBAUTHN_ORIGIN`. Система разрешает приложению работать с ключами этого домена, только если домен подтверждает, что приложение принадлежит магазину:

| Платформа | Файл на домене кабинета | Что в нём |
| --- | --- | --- |
| Android | `https://cabinet.ДОМЕН/.well-known/assetlinks.json` | имя пакета и SHA-256 отпечаток сертификата подписи приложения |
| iOS | `https://cabinet.ДОМЕН/.well-known/apple-app-site-association` | `webcredentials` с идентификатором приложения `TEAMID.bundle-id` |

Оба файла отдаёт backend по значениям из `.env`; Caddy пересылает эти два пути на домене кабинета в backend.

Порядок входа в приложении:

1. Приложение запрашивает у сервера параметры входа. Сервер возвращает одноразовый challenge (5 минут) и ключ привязки. У приложения нет cookie, поэтому ключ привязки хранится только в памяти на время одной операции и возвращается в заголовке `X-Shop-Passkey-Binding`.
2. Система показывает окно выбора ключа и подтверждения биометрией или PIN-кодом.
3. Сервер проверяет подпись, challenge, RP ID, обязательную проверку пользователя (UV), user handle, счётчик и **происхождение** подписи:
   - Android: `android:apk-key-hash:…` — хэш сертификата подписи из `ANDROID_USER_CERT_SHA256`. Ключ, подписанный чужим приложением или браузером, не принимается.
   - iOS: адрес кабинета — iOS подписывает им запросы только приложений из `apple-app-site-association`.
4. Сервер выдаёт тот же одноразовый код, связанный с PKCE, что и при входе по паролю. Приложение обменивает его на сессию в `/api/auth/mobile/token`. Без PKCE-заголовка вход не начинается, и challenge не тратится.

Добавить или удалить ключ можно на вкладке **Безопасность** в приложении. Для этого нужен текущий пароль; если у аккаунта нет пароля (вход через Telegram или OAuth), нужен вход не более чем за 5 минут до действия. На аккаунт — не больше 10 ключей.

## Настройка сервера

```dotenv
CUSTOMER_WEBAUTHN_ORIGIN=https://cabinet.example.com
# Android: пакет и SHA-256 отпечаток сертификата подписи (через запятую, если ключей несколько)
ANDROID_USER_PACKAGE=shop.remnawave.user
ANDROID_USER_CERT_SHA256=AB:CD:...:EF
# iOS: TEAMID.bundle-id; если пусто — берётся APNS_TEAM_ID и APNS_BUNDLE_ID
IOS_USER_APP_ID=TEAM123456.shop.remnawave.user
```

1. Отпечаток сертификата Android:
   - для своего ключа подписи: `keytool -list -v -keystore release.jks -alias ALIAS | grep SHA256`;
   - при подписи через Google Play: Play Console → Тестирование и выпуск → Целостность приложения → Подпись приложений, «Отпечаток сертификата SHA-256» (ключ Google, а не ключ загрузки).
2. Укажите переменные в `.env` и перезапустите backend: `docker compose up -d backend`.
3. Проверьте, что файлы открываются по HTTPS без перенаправлений:

   ```bash
   curl -fsS https://cabinet.example.com/.well-known/assetlinks.json
   curl -fsS https://cabinet.example.com/.well-known/apple-app-site-association
   ```

   При пустых настройках сервер отдаёт пустой список, а вход по ключу в приложении этой платформы отвечает «не настроено» (HTTP 503).
4. В админке должен быть включён флаг `passkeys` (**Система → Функции и модули**).

Переменные относятся к настройкам развёртывания (меняются через `.env` и перезапуск), реестр настроек — 226 полей: 134 live, 90 deployment, 2 workflow.

## Сборка приложений

**Android.** Ничего дополнительно задавать не нужно: приложение использует Credential Manager. В `assetlinks.json` должен быть отпечаток того ключа, которым подписана установленная сборка. Отладочная сборка из CI (`shop.remnawave.user.preview`, отладочный ключ) с боевым доменом не работает — для неё нужен отдельный стенд со своими значениями `ANDROID_USER_PACKAGE` и `ANDROID_USER_CERT_SHA256`.

**iOS.**

1. В Apple Developer включите для App ID `shop.remnawave.user` возможность **Associated Domains** и перевыпустите профиль подписи.
2. Домен кабинета передаётся в сборку настройкой `CORGI_ASSOCIATED_DOMAIN` — она попадает в entitlement `webcredentials:ДОМЕН`:

   ```bash
   CORGI_ASSOCIATED_DOMAIN=cabinet.example.com bash scripts/build-ios-signed.sh "$PWD/dist/mobile"
   ```

   Без неё подписанная сборка получает заглушку `cabinet.example.com`, и вход по ключу на реальном домене не работает.
3. Apple кэширует `apple-app-site-association` через свой CDN: после первой публикации файла может пройти до суток.

## Ошибки

| Сообщение | Причина |
| --- | --- |
| «На устройстве нет ключа доступа для этого магазина» | Ключ ещё не создан — войдите по паролю и добавьте его на вкладке «Безопасность». |
| `Native passkeys need ANDROID_USER_CERT_SHA256` / `IOS_USER_APP_ID` | Не заданы переменные для этой платформы. |
| `Passkey authentication verification failed` | Приложение подписано другим ключом, чем указан в `ANDROID_USER_CERT_SHA256`, или ключ удалён. |
| Окно выбора ключа не появляется (Android) | Файл `assetlinks.json` недоступен, отпечаток или пакет не совпадают, на устройстве нет сервисов Google Play. |
| Окно выбора ключа не появляется (iOS) | Профиль без Associated Domains, неверный `CORGI_ASSOCIATED_DOMAIN` или Apple ещё не загрузила файл. |

## API

| Метод | Путь | Назначение |
| --- | --- | --- |
| `POST` | `/api/auth/passkeys/login/options` | параметры входа; для приложения — также `binding` |
| `POST` | `/api/auth/passkeys/login/verify` | проверка ключа; приложению — `authorization_code` для PKCE-обмена |
| `POST` | `/api/auth/passkeys/registration/options` / `verify` | добавление ключа |
| `GET` | `/api/auth/passkeys` | список ключей аккаунта |
| `POST` | `/api/auth/passkeys/{id}/delete` | удаление ключа |
| `GET` | `/.well-known/assetlinks.json` | связь Android-приложения с доменом |
| `GET` | `/.well-known/apple-app-site-association` | связь iOS-приложения с доменом |

Приложение передаёт заголовок `X-Shop-Client` (`android-user` или `ios-user`) и не передаёт `Origin`; запрос с браузерным `Origin` в нативном режиме отклоняется. Админ-приложения используют вход администратора и в этот режим не входят.

## Проверка

`tests/test_native_passkeys.py` (SQLite и PostgreSQL) на реальных подписях ECDSA проверяет:

- регистрацию и вход Android с происхождением `android:apk-key-hash`;
- вход iOS с адресом кабинета;
- выдачу кода, связанного с PKCE, и его обмен;
- отказы: ключ браузера в Android-режиме, ключ чужого приложения, отсутствие ключа привязки, отсутствие PKCE (challenge сохраняется для повтора), браузерный `Origin`;
- ответ 503 без настроек платформы;
- содержимое `assetlinks.json` и `apple-app-site-association`;
- маршруты Caddy на домене кабинета.

Сборки Android и iOS проверяются в CI. Работу с системным окном ключей на физических устройствах и синхронизацию ключей проверяет оператор на своём стенде с подписанными сборками.
