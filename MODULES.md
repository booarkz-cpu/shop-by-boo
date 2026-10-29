> Актуальный дистрибутив: `v28.46.0`; runtime/API: `21.5.1`. Точные границы готовности указаны в текущей матрице покрытия.

> Актуальная инструкция v21.5.1. head магазина `0081_subscription_proxy`, Support Pro `0008`.

# Компоненты проекта

| Каталог / сервис | Назначение |
| --- | --- |
| `backend/app`, `backend/worker.py` | API магазина, checkout, выдача, финансовый журнал, задачи и бот |
| `backend/alembic` | Миграции PostgreSQL; текущий head `0081_subscription_proxy` |
| `admin` | Административная React-панель, поиск, таблицы и операторские действия |
| `cabinet` | Общий пользовательский React-интерфейс |
| `miniapp` | Telegram-поверхность, импортирующая общий кабинет |
| `support-pro` | Отдельная поддержка и защищённый мост; текущий head `0008` (мост Zendesk/Freshdesk) |
| `mobile/android-user`, `mobile/android-admin` | Исходники Android клиента и администратора |
| `mobile/ios-user`, `mobile/ios-admin` | Исходники iOS клиента и администратора |
| `desktop`, `browser-extension`, `corgi-cli` | Дополнительные клиентские инструменты; проверяйте отдельные README |
| `deploy`, `scripts` | Установка, backup/update/recovery, диагностика и упаковка |
| `tests`, `.github/workflows` | Регрессии, CI, сборки и публикация |

[Архитектура](docs/ru/WORKSPACE_ARCHITECTURE.md), [точная функциональная матрица](docs/ru/WORKSPACE_COVERAGE.md), [эксплуатация](OPERATIONS_RUNBOOK_RU.md).

Текущие дополнения: [настройки без перезапуска](docs/ru/RUNTIME_SETTINGS_CURRENT.md), [объединение аккаунтов](docs/ru/ACCOUNT_MERGE_CURRENT.md), [ключи доступа администратора](docs/ru/ADMIN_PASSKEYS.md), [метрики, dashboard и alerts](docs/ru/OPERATIONS_MONITORING.md). Мобильный workflow использует версию текущего манифеста; без owner signing secrets APK/IPA не объявляются подписанными production assets.
