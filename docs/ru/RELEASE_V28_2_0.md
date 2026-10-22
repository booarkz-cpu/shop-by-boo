# v28.2.0 — безопасное объединение клиентских аккаунтов

Дистрибутив `v28.2.0` содержит runtime/API `21.5.1`, магазин `0063_account_merge` и Support Pro `0007` / 3.7. Дата, точный commit и результаты CI фиксируются GitHub Release.

## Изменения

- Добавлен подтверждаемый обеими сторонами account merge: одноразовый код исходного аккаунта, повторная проверка основного аккаунта, неизменяющий preview и явное согласие.
- Кошелёк, реферальный баланс, подписки, платежи, ledger, поддержка, устройства, маркетинговая история и профильные связи переносятся атомарно с финансовой сверкой.
- Telegram, Яндекс, VK, email и passkeys исходного аккаунта сохраняются как login aliases; пароль всех email после merge соответствует основному аккаунту.
- Конфликтный план блокирует уникальные дубли, активные коммерческие операции, реферальные циклы, несовместимые singleton-профили и превышение лимитов.
- `Idempotency-Key`, operation journal и сохранение текущей подтверждённой сессии позволяют безопасно повторить запрос после потерянного ответа. Остальные сессии отзываются.
- Добавлена миграция `0063_account_merge`, очистка просроченных разрешений и защита downgrade после появления merge-истории.
- В кабинете появился адаптивный двухшаговый интерфейс с подсказками к каждому полю, итоговыми суммами, конфликтами и недоступной кнопкой до явного подтверждения.
- Обновлены API-каталог, карта файлов, матрица, эксплуатационные инструкции и [руководство account merge](ACCOUNT_MERGE_CURRENT.md).

## Файлы релиза

| Файл | Назначение |
| --- | --- |
| `remnawave_vpn_shop_v28_2_0_full_release.zip` | Отслеживаемые исходники без локальных секретов и сборочных продуктов |
| `remnawave_vpn_shop_v28_2_0_full_release.zip.sha256` | Контрольная сумма архива |
| `remnawave_vpn_shop_v28_2_0_full_release_manifest.json` | API/runtime, distribution tag, commit, SHA-256, CI evidence и границы готовности |

## Обновление

До миграции сделайте согласованный backup. Затем обновите исходники, пересоберите backend/worker/cabinet/miniapp, выполните `alembic upgrade head` и убедитесь, что current head равен `0063_account_merge`. Порядок команд: [обновление дистрибутива](DISTRIBUTION_UPGRADE_CURRENT.md) и [production-регламент](PRODUCTION_CURRENT.md).

Downgrade `0063_account_merge` разрешён только до первого объединения. После появления alias или operation journal используйте исправление вперёд либо согласованное восстановление backup.

## Проверки

CI применяет миграции на PostgreSQL, запускает backend и browser tests, typecheck/build трёх интерфейсов, Support Pro, Compose, non-root container checks, dependency audit и Docker build. Регрессии account merge отдельно проверяют обе авторизации, self/cycle, конфликтный rollback, перенос финансов/подписок/истории/passkeys, login aliases, idempotent replay, сохранение текущей сессии и конкурентное подтверждение PostgreSQL.

## Границы выпуска

`production_ready`, `full_function_transfer` и `production_e2e_verified` остаются `false`: реальные кассы, SMTP, Remnawave, restore drill и мобильные подписи требуют evidence конкретной установки. Account merge закрыт как реализованная локальная подсистема, но не закрывает остальные строки [матрицы](WORKSPACE_COVERAGE.md). Новая реализация Freekassa не добавлена; разрешённые агенты новых покупок остаются YooKassa, RollyPay и Platega. Архив не подписан криптографически; SHA-256 и commit-bound manifest подтверждают целостность опубликованных файлов.
