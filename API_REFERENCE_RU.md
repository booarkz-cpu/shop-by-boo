> Актуальный дистрибутив: `v28.47.0`; runtime/API: `21.5.1`. Точные границы готовности указаны в текущей матрице покрытия.

# HTTP API

Точный каталог маршрутов: [docs/API_ENDPOINTS.md](docs/API_ENDPOINTS.md). Реальные схемы запросов: `/openapi.json` собственного backend. Проверяйте права серверной роли; наличие кнопки интерфейса не авторизует действие.

Для клиента используется текущая веб-сессия или поддерживаемая мобильная авторизация. Изменяющие запросы с cookie требуют штатной CSRF-защиты. Чужой владелец, отозванная сессия и ограниченный аккаунт не должны получать финансовые/приватные операции. Для покупок сохраняйте исходный `Idempotency-Key` и снимок заказа при повторах; не меняйте его после потери ответа.

## Настройки без перезапуска v28.47.0

| Метод | Маршрут | Право / результат |
| --- | --- | --- |
| GET | `/api/admin/runtime-settings` | `settings.runtime.read`; masked catalog, version, history and full field classification |
| POST | `/api/admin/runtime-settings/stage` | `settings.runtime.write`; strict validation, dependency check and encrypted staged payload |
| POST | `/api/admin/runtime-settings/changes/{id}/apply` | `settings.runtime.write`; expected version and HMAC fingerprint required |
| POST | `/api/admin/runtime-settings/changes/{id}/rollback` | `settings.runtime.write`; only the latest applied revision |
| DELETE | `/api/admin/runtime-settings/changes/{id}` | `settings.runtime.write`; discards a staged revision |

Значения секретов не возвращаются ни одним ответом. Полный контракт: [RUNTIME_SETTINGS_CURRENT.md](docs/ru/RUNTIME_SETTINGS_CURRENT.md).

## Объединение аккаунтов v28.2.0

| Метод | Маршрут | Результат |
| --- | --- | --- |
| POST | `/api/me/account-merge/authorization` | Повторная проверка исходного владельца и одноразовый код на десять минут |
| POST | `/api/me/account-merge/preview` | Неизменяющий план сумм, объектов, эффектов и конфликтов |
| POST | `/api/me/account-merge/confirm` | Повторная проверка основного владельца и атомарный перенос; обязателен `Idempotency-Key` |

Политика конфликтов, переносимых данных и диагностика: [ACCOUNT_MERGE_CURRENT.md](docs/ru/ACCOUNT_MERGE_CURRENT.md). Код не передавайте в URL или журналы.

## Конкурсы и колесо (alpha.6)

| Метод | Маршрут | Право / результат |
| --- | --- | --- |
| GET | `/api/admin/giveaways?before=ID` | `marketing.read`, до 200 акций |
| POST | `/api/admin/giveaways` | `manage_marketing`, создание черновика |
| POST | `/api/admin/giveaways/{id}/publish` | Публикация фиксированных условий |
| POST | `/api/admin/giveaways/{id}/close` | Закрытие без повторного открытия |
| DELETE | `/api/admin/giveaways/{id}` | Только черновик без участия |
| POST | `/api/admin/giveaways/{id}/draw` | Единственный розыгрыш конкурса после окончания |
| GET | `/api/admin/giveaways/{id}/entries?after=ID` | `manage_marketing`, страницы по 100 |
| GET | `/api/me/giveaways?after=ID` | Сессия клиента, страницы по 50, свой результат |
| POST | `/api/me/giveaways/{id}/enter` | Сессия клиента, однократное участие; без суммы/победителя в запросе |

Схемы и ограничения: `backend/app/giveaways.py`, [отдельная инструкция](docs/ru/WORKSPACE_GIVEAWAYS.md). Клиентские ответы имеют `Cache-Control: private, no-store`. Участие возвращает один сохранённый исход на аккаунт; новая попытка не требует нового idempotency key.

Справочники: [ключи доступа администратора](docs/ru/ADMIN_PASSKEYS.md), [метрики, dashboard и alerts](docs/ru/OPERATIONS_MONITORING.md). Мобильный workflow использует версию текущего манифеста; без owner signing secrets APK/IPA не объявляются подписанными production assets.

## Реферальная программа v21.5.0

GET/PUT `/api/admin/referrals/program` требует `referrals.reconcile`. GET `/api/me/referral/network` показывает собственную обезличенную сеть с `depth=1..5`, `limit=2..1000`. Условия начисления фиксируются сервером; [подробности](docs/ru/REFERRALS_CURRENT.md).
