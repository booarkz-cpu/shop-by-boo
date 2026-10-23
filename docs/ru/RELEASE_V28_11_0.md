# Выпуск v28.11.0 — ключи доступа в приложениях Android и iOS

Дистрибутив: `v28.11.0`. Runtime/API: `21.5.1`. Head магазина: `0068_network_intel` (без новых миграций). Support Pro: `0007` / 3.7. Дата и commit фиксируются тегом выпуска.

## Что завершено

Строка матрицы «WebAuthn/passkeys/биометрия» закрыта и для приложений: раньше ключи доступа работали только в админке и веб-кабинете. [Инструкция](NATIVE_PASSKEYS_CURRENT.md).

- **Android.** Вход «Войти с ключом доступа» и раздел «Ключи доступа» на вкладке «Безопасность» (список, добавление, удаление) через Credential Manager.
- **iOS.** То же через AuthenticationServices (системные passkeys, связка ключей iCloud).
- **Сервер.** Нативный режим ceremonies для клиентов `android-user` и `ios-user`:
  - происхождение подписи `android:apk-key-hash:…` по отпечатку сертификата приложения или адрес кабинета для iOS;
  - привязка challenge через заголовок `X-Shop-Passkey-Binding` вместо cookie;
  - вход заканчивается одноразовым кодом, связанным с PKCE, как вход по паролю; без PKCE challenge не тратится;
  - браузерный `Origin` в нативном режиме отклоняется.
- **Связь приложений с доменом кабинета.** Backend отдаёт `/.well-known/assetlinks.json` и `/.well-known/apple-app-site-association`, Caddy пересылает эти пути на домене кабинета.
- Ключ, созданный в веб-кабинете, подходит приложению той же платформы и наоборот: RP ID общий — домен кабинета.

### Настройки

- Новые переменные `.env`:
  - `ANDROID_USER_PACKAGE` (по умолчанию `shop.remnawave.user`);
  - `ANDROID_USER_CERT_SHA256` — SHA-256 отпечатки сертификата подписи;
  - `IOS_USER_APP_ID` — `TEAMID.bundle-id`; если пусто, берутся `APNS_TEAM_ID` и `APNS_BUNDLE_ID`.
- Реестр настроек — 156 полей: 96 live, 58 deployment, 2 workflow.
- iOS: настройка сборки `CORGI_ASSOCIATED_DOMAIN` (домен кабинета) задаёт entitlement `webcredentials:`; скрипт `scripts/build-ios-signed.sh` передаёт её из окружения. В профиле подписи нужна возможность Associated Domains.

### CI

- Тест фонового worker больше не оставляет реальные циклы push, плагинов и сетевой аналитики — это устранило зависание CI.
- Вывод pytest пишется в файл, время шага и задания ограничено, а сводка ошибки называет зависший тест.
- Шлюз публикации выпуска сопоставляет прогоны CI и Docker с commit на стороне скрипта (API GitHub иногда не находил прогон по `head_sha`).

## Обновление

Миграций нет. Используйте [проверяемый регламент обновления](DISTRIBUTION_UPGRADE_CURRENT.md), затем:

1. Добавьте в `.env` переменные платформ, которые публикуете, и перезапустите backend.
2. Обновите `deploy/Caddyfile` из дистрибутива (маршруты `/.well-known/*` на домене кабинета) и перезапустите Caddy.
3. Проверьте файлы:

   ```bash
   curl -fsS https://CABINET_DOMAIN/.well-known/assetlinks.json
   curl -fsS https://CABINET_DOMAIN/.well-known/apple-app-site-association
   docker compose exec -T backend alembic current
   ```

4. Соберите и подпишите приложения ключом, отпечаток которого указан в `.env` (Android), и с `CORGI_ASSOCIATED_DOMAIN` (iOS).

Ожидаемые head: магазин `0068_network_intel`, Support Pro `0007`.

## Проверка

- Python: полный набор на SQLite и PostgreSQL, включая `tests/test_native_passkeys.py` с реальными подписями ECDSA.
- Сборки Android и iOS, браузерные сценарии и Support Pro — в CI.

## Границы выпуска

Автотесты проверяют серверную часть и сборку приложений. Системное окно ключей на физических устройствах, синхронизацию ключей между устройствами и загрузку `apple-app-site-association` через CDN Apple проверяет оператор на стенде с подписанными сборками. Внешние payment/SMTP/Remnawave E2E и production gate остаются за оператором. Полный статус — [матрица покрытия](WORKSPACE_COVERAGE.md) и [реестр завершения](MATRIX_COMPLETION_21_5_1.md).
