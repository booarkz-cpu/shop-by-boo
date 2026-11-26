# Выпуск мобильных приложений

Сверено 16 ноября 2026 года по main `2a204cd3`. Это описание текущей цепочки
GitHub и реальных скриптов, а не подтверждение публикации в Google Play/App Store.
По решениям владельца №10/№11 сейчас используется GitHub; Apple Developer и
физические проверки остаются внешними условиями. PR #355 слит в main2a204cd3, но сам факт
слияния не подтверждает опубликованный выпуск v28.159.0/клиент1.10.1: требуется
проверка полного комплекта33assets и соответствующих манифестов.

## Продукты и версии

В задании `iOS • UI tests` CI проверяет четыре сценария магазина на симуляторе.
Если до первого сценария XCTest сообщает `XCTDaemonErrorDomain Code=18` с сообщением
`Timed out waiting for AX loaded notification` или `XCTFuture Code=1000` с сообщением
`Timed out while loading Accessibility`, CI один раз очищает и перезапускает симулятор.
Заданию отведено 65 минут с учётом второго запуска.
При ошибке проверки приложения задание завершается с ошибкой. Журналы обеих попыток
сохраняются в артефакте `xcuitest-results-<run_id>-<run_attempt>`; успешный результат
включает сводку xcresult с четырьмя выполненными сценариями.

| Продукт | Android | iOS |
|---|---|---|
| Магазин | [apps/vpn-shop/android](../apps/vpn-shop/android), package shop.remnawave.user | [apps/vpn-shop/ios](../apps/vpn-shop/ios), VpnShopUser |
| Администратор | [apps/lucy-admin/android](../apps/lucy-admin/android), package shop.remnawave.admin | [apps/lucy-admin/ios](../apps/lucy-admin/ios), VpnShopAdmin |
| Самостоятельный VPN-клиент | [apps/vpn-client/android](../apps/vpn-client/android), package shop.corgi.client | Отдельного выпущенного iOS-клиента эта цепочка не создаёт |

Версия магазина/админки — семейная: Android versionName/versionCode в
app/build.gradle.kts и iOS MARKETING_VERSION/параметры проекта должны совпадать.
Клиент имеет свою версию и versionCode. Дистрибутив магазина имеет отдельный
distribution_tag в [release-manifest.template.json](../release-manifest.template.json);
поле version там относится к runtime/API, его нельзя подставлять вместо тега
дистрибутива. Проверки семейства: [test_mobile_family_status.py](../tests/test_mobile_family_status.py).

После изменения версии применяются общие требования
[VERSIONING](VERSIONING.md), [RELEASE_PROCESS](RELEASE_PROCESS.md) и
[RELEASE_CHECKLIST](RELEASE_CHECKLIST.md): заметки, README, статусы и карта файлов.
Версия Android должна позволять обновление поверх уже установленного приложения;
увеличение versionName само по себе не заменяет versionCode.

## Два workflow, разные результаты

| Workflow | Когда и что делает | Что не следует из зелёного результата |
|---|---|---|
| [Mobile packages](../.github/workflows/mobile-release.yml) | PR по подходящим путям, каждый push main, ручной запуск; сборка/проверка Android+iOS, artifacts mobile-android/mobile-ios; на main — прикрепление разрешённых production-файлов к релизу своего SHA | PR-сборка не получает production signing secrets; успех PR не означает подписанный APK/IPA или установленное приложение |
| [Build mobile apps for a release](../.github/workflows/build-mobile.yml) | После Publish GitHub release, либо ручной запуск с tag; checkout refs/tags/<tag>, сборки Android APK/AAB и iOS, прикрепление к этому выпуску | Unsigned IPA/симулятор не являются подписанным устройственным iOS-приложением; этот workflow сам не публикует в магазины |

Автоматический build-mobile сравнивает время публикации релиза со временем
запуска publisher: maintenance-коммит без нового выпуска не должен пересобирать
старый latest. В Mobile packages прикрепление проверяет текущий main, состояние
CI и принадлежность тега тому же исходному коммиту. `Main moved` означает, что
пакеты остались workflow artifacts; это не подтверждение полного выпуска.

`mobile-production-status.json` фиксирует версию семейства, source_commit,
workflow_run и состояния android/ios. Android без ключа имеет
blocked_missing_signing_key, iOS без Apple identity — blocked_missing_apple_identity.
Эти состояния не надо заменять словом signed ради отчёта.

## Android: сборка и подпись

[scripts/build-android-apk.sh](../scripts/build-android-apk.sh) собирает магазин
и администратора; самостоятельный клиент собирается отдельно в Mobile packages.
Общее VPN-ядро готовится [build-xray-aar.sh](../scripts/mobile/build-xray-aar.sh)
и копируется в соответствующие libs. Точные JDK/SDK/build-tools/Go выбирают
workflow и скрипт ядра; использование старого локального SDK не является
эквивалентом проверенной сборки CI.

| ANDROID_BUILD_MODE | Результат |
|---|---|
| auto | Без ANDROID_KEYSTORE — debug/preview, с ним — release |
| verify-release | Release-вариант без production-подписи, имена unsigned |
| release | Требует постоянный keystore, пароль, alias и пароль ключа; APK+AAB с проверкой сертификата |

Локальная проверочная сборка двух приложений, при установленном SDK и зависимостях:

```bash
ANDROID_BUILD_MODE=verify-release bash scripts/build-android-apk.sh "$PWD/dist/mobile"
```

Production workflow читает имена GitHub secrets:
ANDROID_KEYSTORE_BASE64, ANDROID_KEYSTORE_PASSWORD, ANDROID_KEY_ALIAS,
ANDROID_KEY_PASSWORD. Секреты не копируются в PR, логи или документы. В runner
keystore декодируется с приватными правами и удаляется по завершении шага.
CORGI_SHOP_URL берётся из vars либо mobile/shop-url.txt и должен быть HTTPS origin;
его изменение влияет на адрес магазина внутри приложений.

Публичный эталон сертификата находится в
[mobile/android-signing-cert.sha256](../mobile/android-signing-cert.sha256).
При сборке подписанного пакета нужен отпечаток из 64 шестнадцатеричных цифр.
Для APK сборка проверяет подпись командой `apksigner verify --verbose --print-certs`
и сравнивает SHA-256 сертификата единственного подписанта с эталоном. Android Build
Tools 35 и 36 обозначают подписанта по номеру, а версия 37 указывает схему подписи.
Сценарий проверяет подпись AAB с помощью `jarsigner` и сверяет отпечаток сертификата
из отчёта `keytool` с тем же эталоном. При отсутствии корректного эталона подписанная
сборка останавливается до запуска Gradle. Workflow сверяет версию APK и отклоняет
отладочную сборку или отладочный сертификат. Для обновления уже установленного
приложения нужен совместимый ключ подписи.

Постоянные имена для установки/обновлений:
corgi-lusi-android.apk, corgi-lusi-android-admin.apk, corgi-lusi-client.apk,
соответствующие .sha256 и .json с versionCode/versionName/sha256/apk.
Манифест должен описывать именно приложенные байты. AAB — пакет для соответствующей
цепочки распространения, не APK для обычной установки с GitHub.

## iOS: сборка отдельно от подписи

[build-ios-packages.sh](../scripts/build-ios-packages.sh) создаёт unsigned
device IPA и сборку симулятора с проверкой bundle version. Наличие этих файлов
не означает, что IPA можно установить на обычный iPhone.

[build-ios-signed.sh](../scripts/build-ios-signed.sh) требует macOS/Xcode,
IOS_CERTIFICATE_BASE64, IOS_CERTIFICATE_PASSWORD, IOS_USER_PROFILE_BASE64,
IOS_ADMIN_PROFILE_BASE64, IOS_TEAM_ID. Дополнительные профили
IOS_USER_PUSH_PROFILE_BASE64 и IOS_USER_TUNNEL_PROFILE_BASE64 нужны для
соответствующих extensions. Для tunnel профиль проверяется на entitlement
packet-tunnel-provider. Скрипт сверяет team, bundle ID и срок профиля,
создаёт временный keychain, архивирует/экспортирует и очищает временную identity.

IOS_EXPORT_METHOD по умолчанию release-testing; допустимые значения ограничены
скриптом. Передача app-store-connect — только выбор метода экспорта: скрипт
сам не отправляет пакет в App Store и не создаёт Apple Developer аккаунт.
Сертификаты/профили в этой документационной сверке не предоставлялись и реальные
iOS-устройства не проверялись. Без профиля tunnel приложение может передавать
подписку внешнему VPN-клиенту; зелёная сборка такого варианта не доказывает
работу собственного Network Extension на устройстве.

## Публикация и проверка полноты

1. Проверить свежий commit SHA PR, все применимые workflow, CI gate и iOS.
   Reviews/конфликты должны быть разобраны. Слить обычным squash с обязательными
   трейлерами проекта; не обходить main protection.
2. Дождаться CI/Docker/publisher именно итогового SHA main. До полной публикации
   не сливать следующий PR: иначе packages могут остановиться с Main moved.
3. Проверить tag, draft=false, source SHA, состав assets и завершение обоих
   мобильных этапов. Для текущей согласованной конфигурации ожидаются33 файла;
   это не обещание подписанной iOS-версии. Статус, имена и подписи важнее одного
   числа файлов.
4. Проверить .sha256, сертификат APK, package/version и согласованность трёх
   update JSON с их APK. Unsigned/preview нельзя выдавать за production Android.
5. Самостоятельный клиент также получает client-v<version>, который не должен
   перехватывать latest дистрибутива. Его JSON указывает на APK собственного
   client-тега; при повторной сборке той же версии сохраняется первый клиентский
   выпуск. Проверить обе точки загрузки, а не только общий latest.

Пример чтения фактически опубликованного тега без изменения релиза:

```bash
TAG=v28.158.0
gh api "repos/booarkz-cpu/shop-by-boo/releases/tags/$TAG" \
  --jq '{tag: .tag_name, draft: .draft, files: (.assets | length), assets: [.assets[] | {id,name,size,state}]}'
```

В среде с ограниченным GraphQL скачивать нужный asset следует через REST:
`gh api -H "Accept: application/octet-stream" repos/booarkz-cpu/shop-by-boo/releases/assets/<id>`.
ID берётся из фактического ответа, не конструируется. Команды этого раздела
не выполнялись в рамках создания документа; это воспроизводимые инструкции.

## Неполный выпуск и повтор запуска

Сначала установить причину по source SHA, failed step и списку assets. Очередь
раннеров не исправляется отменой чужих проверок. Если main сместился, нельзя
прикреплять пакеты нового коммита к старому тегу и менять тег ради прохождения
проверки. Проверить, какую версию и исходный SHA действительно собирает workflow.

У build-mobile есть ручной параметр tag, но его upload использует `--clobber`:
повтор может заменить существующие мобильные assets. Поэтому запуск не является
безусловно read-only восстановлением. До повторной публикации нужно проверить
текущий код, уже приложенные файлы/манифесты, полномочия и решения владельца;
не заменять известные правильные файлы случайной пересборкой. Исторический
v28.152 не чинить по более позднему решению владельца №20, даже если старый
стартовый текст предписывал обратное. Не удалять/передвигать теги обходом прокси.

## Обновление установленного приложения и откат

Android проверяет APK, подпись, versionCode и разрешения системы. Проверка
обновлений/попытка установки через PackageInstaller не гарантирует установку
без участия человека на любой версии Android/прошивке. Разрешение неизвестных
источников и первое подтверждение могут требовать действия владельца устройства.
Возобновление VPN после MY_PACKAGE_REPLACED нуждается в отдельной проверке
живого телефона; CI-сборка этого не доказывает.

Обычный APK с меньшим versionCode поверх нового не устанавливается как штатное
обновление. Предпочтителен исправляющий выпуск с большим versionCode. Перед
удалением клиента для возврата старой версии нужна проверенная защищённая
переносимая копия: удаление стирает данные/Keystore, файл SharedPreferences
не заменяет экспорт под паролем. Нельзя обещать сохранность подписок при таком
откате без проверки восстановления. iOS не обновляет себя APK-подобной установкой
с GitHub; текущий GitHub-процесс не заменяет Apple-подписанное распространение.

## Доказательства и оставшиеся проверки

Проверки исходной цепочки: [mobile-client-release.test.cjs](../tests/mobile-client-release.test.cjs),
[release-publisher.test.cjs](../tests/release-publisher.test.cjs),
[test_download_links.py](../tests/test_download_links.py),
[test_mobile_family_status.py](../tests/test_mobile_family_status.py),
[android-client.yml](../.github/workflows/android-client.yml).
Симулятор/эмулятор, подписанный пакет, успешная установка, реальный VPN и
автообновление на телефоне — разные доказательства. Для каждого выпуска записать
реальные run/commit/assets и отдельно отсутствующие внешние проверки; не
переносить зелёный результат предыдущего head на новый.
