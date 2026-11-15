# Проверка v21.0.0-alpha.7

Выпуск добавляет административный WebAuthn, операционные метрики БД, dashboard/alerts и исправляет публикацию мобильных assets для актуального тега. Это предварительный релиз, не заявление о завершении всей [матрицы функций](WORKSPACE_COVERAGE.md).

## Изменения

- [Passkeys](ADMIN_PASSKEYS.md): реальный серверный verifier, discoverable credentials, обязательные user presence/verification, пароль/MFA перед регистрацией, одноразовые browser-bound challenges, счётчики под PostgreSQL lock и существующие отзывные административные сессии. Новая миграция `0053_admin_passkeys`.
- [Мониторинг](OPERATIONS_MONITORING.md): статусы очереди, платежей, возвратов, поддержки, age queued job, heartbeat worker, локальные подписки, явный gauge доступности БД. Dashboard из 14 панелей, sample scrape config, пять alert rules. Внешний Grafana/Alertmanager не объявляется развёрнутым.
- Mobile workflow читает версию манифеста, ждёт успешного main CI и релиза того же commit; повтор одинакового asset безопасен, другой APK/IPA поверх существующего не перезаписывается, upload digest/size проверяется.

## Проверки

Python-тесты используют настоящую EC-криптографию, COSE и ECDSA, а не mock successful verifier. Отрицательные случаи включают неверную подпись/challenge/origin, отсутствие UV, чужой userHandle, replay, expired challenge, disabled admin, изменения регистрационной учётной записи, duplicate credential и cross-origin assertions. PostgreSQL CI дополнительно проверяет race одного challenge и двух challenges с одинаковым sign counter.

CI также выполняет отдельный Chromium virtual authenticator сценарий через браузерный UI: регистрация → выход → discoverable вход → reload → удаление. Локальная загрузка Chromium в рабочей среде первоначально вернула повреждённый CDN-архив; после получения того же Chromium из официального Chrome for Testing хранилища полный локальный UI-сценарий прошёл (1 passed). Финальный источник истины для браузерного job — успешный CI на конкретном release commit.

Существующие services/backend/Support Pro тесты, Alembic, audits, три web build/typecheck, Docker/non-root/Redis и Android/iOS compile checks остаются обязательными. Конкретный CI run, commit и статус включаются в detached release manifest после успешного main CI.

Локальная общая suite: **684 passed, 144 skipped** (PostgreSQL проверки входят в CI). Аудиты pip/npm не обнаружили известных уязвимостей. Админка прошла typecheck/build. Promtool 3.15.0 проверил scrape config, пять alert rules, их пять сценариев срабатывания и 14 PromQL запросов dashboard.

## Границы

Внешний application payment E2E v2 всё ещё не реализован и не подтверждён на отдельных provider sandbox/Remnawave; production gate закрыт. Не добавлены клиентские/native passkeys, полный импорт другого бота, multi-level referral graph, support merge/split и прочие незавершённые строки матрицы. Внешние SMTP/VPN/browser/native устройства и owner signing keys не заменяются unit-тестами. `full_function_transfer=false`, `production_e2e_verified=false`, `signed=false` сохраняются.

Текущие условия использования — редакция 2.3 с прежними разрешениями своего коммерческого магазина и ограничениями распространения. Библиотеки WebAuthn/Playwright сохраняют собственные лицензии. Перед установкой нужны проверенный backup и [регламент обновления](WORKSPACE_UPGRADE.md); downgrade 0053 блокируется при наличии ключей.
