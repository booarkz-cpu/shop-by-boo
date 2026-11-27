# Актуальная документация

Тег дистрибутива v28.161.0, runtime/API 21.5.1, миграция 0094_store_subscriptions. [Главный указатель](../DOCUMENTATION.md) содержит текущие инструкции по всем функциям. [Установка](../INSTALL.md), [шаги SSH/Termius](../INSTALL_STEPS.md), [функции](../FUNCTIONS.md), [live-настройки](ru/RUNTIME_SETTINGS_CURRENT.md), [объединение аккаунтов](ru/ACCOUNT_MERGE_CURRENT.md), [заметки v28.161.0](ru/RELEASE_V28_161_0.md), [границы готовности](ru/FINAL_RELEASE_READINESS.md).

[Матрица покрытия](ru/WORKSPACE_COVERAGE.md), [критерии завершения](ru/MATRIX_COMPLETION_21_5_1.md), [API](API_ENDPOINTS.md), [обновление](ru/WORKSPACE_UPGRADE.md), [мобильные приложения](../MOBILE.md), [лицензия](../LICENSE).

## Руководства по задачам

| Задача | Руководство |
| --- | --- |
| Разобраться в архитектуре и границах служб | [Обзор системы](architecture/SYSTEM_OVERVIEW.md) · [Модули](modules/README.md) |
| Установить магазин на VPS | [Требования, DNS и установка](INSTALLATION.md) · [Первая продажа](ru/LAUNCH_GUIDE.md) |
| Настроить магазин и работать в Lucy Admin | [Админ-панель](ru/new/ADMIN_PANEL_GUIDE.md) · [Настройки по разделам](ru/modules/README.md) |
| Войти в личный кабинет и управлять подпиской | [Руководство покупателя](ru/new/USER_CABINET_GUIDE.md) |
| Внести изменение и проверить его перед PR | [Руководство разработчика](../CONTRIBUTING.md) |
| Подключить кассу и проверить уведомления | [Платежи](wiki/ru/Payments.md) |
| Установить панель Remnawave и связать её с магазином | [Настройка Remnawave](ru/new/REMNAWAVE_INSTALLATION_GUIDE.md) |
| Добавить VPN-ноду и включить на ней нужные функции | [Добавление нод](ru/new/REMNAWAVE_INSTALLATION_GUIDE.md#5-добавлять-ноды) · [Плагины нод](ru/new/NODE_PLUGINS.md) |
| Выдавать доступ по MASQUE | [Ноды и подписки MASQUE](MASQUE_PANEL.md) |
| Установить мобильное приложение и подключиться | [Приложения для Android и iOS](ru/MOBILE_GUIDE.md) |
| Восстановить базы и файлы после сбоя | [Проверка и восстановление резервной копии](ru/BACKUP_CURRENT.md) |
| Обновить магазин и при необходимости откатить версию | [Обновление магазина](wiki/ru/Updates.md) |
| Защитить доступ администратора и секреты | [Безопасность магазина](wiki/ru/Security.md) |

## История

История v20.0.29: [VDS](ru/VDS_PRODUCTION_20_0_29.md). Исторические инструкции сохранены в `archive/*_BEFORE_ALPHA_6.md` и версиях release notes. Они не являются текущим обещанием возможностей. v28.161.0 находится в stable-канале; перед обновлением проверьте ограничения и backup/restore.

Справочники: [Passkeys](ru/ADMIN_PASSKEYS.md), [операционный мониторинг](ru/OPERATIONS_MONITORING.md), [проверки и ограничения](ru/RELEASE_21_0_0_ALPHA_7.md).

Точное обновление: [DISTRIBUTION_UPGRADE_CURRENT.md](ru/DISTRIBUTION_UPGRADE_CURRENT.md). Проверка сервера: [INFRASTRUCTURE_CHECKS_CURRENT.md](ru/INFRASTRUCTURE_CHECKS_CURRENT.md). Полная карта: [PROJECT_FILE_MAP.md](PROJECT_FILE_MAP.md).

## Эксплуатационные основания

[Безопасность](SECURITY_BASELINE.md), [карта персональных данных](PRIVACY_DATA_MAP.md), [наблюдаемость](OBSERVABILITY.md), [обновление и откат](UPGRADE_ROLLBACK.md), [выпуск приложений](MOBILE_RELEASE_GUIDE.md), [измеренный CI baseline](PERFORMANCE_BASELINE.md). Каждый документ отдельно перечисляет подтверждённое поведение и оставшиеся внешние проверки.
