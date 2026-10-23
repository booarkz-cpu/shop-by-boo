# Документация VPN Shop by Corgi

Текущий тег дистрибутива: **v28.11.0**. Внутренняя версия runtime/API: **21.5.1**, миграция магазина **0068_network_intel**, Support Pro **0007** / 3.7. Production-ready не подтверждён: рабочие сценарии и незавершённые внешние проверки описаны отдельно, реальные платежи не сертифицированы.

| Задача | Инструкция |
| --- | --- |
| Выбрать путь установки | [INSTALL.md](INSTALL.md) |
| Выполнить шаги через SSH/Termius | [INSTALL_STEPS.md](INSTALL_STEPS.md) |
| Найти инструкции по всем функциям | [FUNCTIONS.md](FUNCTIONS.md) |
| Кабинет и Mini App | [Пользователь](docs/ru/WORKSPACE_USER_GUIDE.md) |
| Настроить административные разделы | [Администратор](docs/ru/WORKSPACE_ADMIN_GUIDE.md) |
| Изменить live-конфигурацию | [Настройки без перезапуска](docs/ru/RUNTIME_SETTINGS_CURRENT.md) |
| Пароль, email и восстановление | [Безопасность аккаунта](docs/ru/WORKSPACE_ACCOUNT_SECURITY.md) |
| Объединить два клиентских аккаунта | [Account merge](docs/ru/ACCOUNT_MERGE_CURRENT.md) |
| Несколько подписок и подарки | [Подписки](docs/ru/WORKSPACE_SUBSCRIPTIONS.md) |
| Смена тарифа, трафик и возвраты | [Коммерческие операции](docs/ru/WORKSPACE_COMMERCE.md) |
| Кассы и ограничения допуска | [Платежи](docs/ru/WORKSPACE_PAYMENTS.md) |
| Опросы | [Опросы и награды](docs/ru/WORKSPACE_SURVEYS.md) |
| Конкурсы и колесо | [Конкурсы и призы](docs/ru/WORKSPACE_GIVEAWAYS.md) |
| Support Pro и история | [Мост поддержки](docs/ru/WORKSPACE_SUPPORT_BRIDGE.md) |
| Email-канал поддержки | [Email-канал](docs/ru/SUPPORT_EMAIL_CHANNEL_CURRENT.md) |
| Плагины и внешние сервисы | [Плагины](docs/ru/PLUGINS_CURRENT.md) |
| ASN и репутация адресов узлов | [Сеть узлов](docs/ru/NETWORK_INTEL_CURRENT.md) |
| Разделы, кнопки и поля админ-панели | [Админ-панель](docs/ru/ADMIN_PANEL_CURRENT.md) |
| Вход по ключу доступа в приложениях | [Ключи доступа в Android и iOS](docs/ru/NATIVE_PASSKEYS_CURRENT.md) |
| Обновить базу и приложения | [Обновление](docs/ru/WORKSPACE_UPGRADE.md) |
| Android/iOS | [MOBILE.md](MOBILE.md) |
| Push-уведомления в приложениях | [Push Android/iOS](docs/ru/PUSH_NOTIFICATIONS_CURRENT.md) |
| Виджет Android и профили админ-приложений | [Виджет и профили](docs/ru/WIDGET_AND_PROFILES_CURRENT.md) |
| Резервирование, диагностика и инциденты | [Эксплуатация](OPERATIONS_RUNBOOK_RU.md) |
| Права и защита данных | [SECURITY.md](SECURITY.md) |
| HTTP API | [API_REFERENCE_RU.md](API_REFERENCE_RU.md) |
| Карта проекта и дизайн | [PROJECT_MAP_RU.md](docs/PROJECT_MAP_RU.md) |
| Дерево каталогов и архитектурные границы | [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) |
| Проверки этого выпуска | [Отчёт v28.11.0](docs/ru/RELEASE_V28_11_0.md) |
| Что ещё не реализовано | [Матрица покрытия](docs/ru/WORKSPACE_COVERAGE.md), [критерии завершения](docs/ru/MATRIX_COMPLETION_21_5_1.md) |

Исторические корневые справочники сохранены в `docs/archive/*_BEFORE_ALPHA_6.md`. Они фиксируют прежние версии и могут описывать отключённые кассы, старую структуру кода и неподтверждённые сценарии. Для текущей установки используйте инструкции выше. Исторические release notes остаются без изменения.

Изменения alpha.7: [ключи доступа администратора](docs/ru/ADMIN_PASSKEYS.md), [метрики, dashboard и alerts](docs/ru/OPERATIONS_MONITORING.md). Мобильный workflow использует версию текущего манифеста; без owner signing secrets APK/IPA не объявляются подписанными production assets.

## Выпуск v28.11.0

Тег v28.11.0 добавил ключи доступа в приложения Android и iOS ([инструкция](docs/ru/NATIVE_PASSKEYS_CURRENT.md)). Тег v28.10.0 переработал админ-панель: страница «Все разделы» с описанием каждой функции, группы как в рабочем порядке оператора, заголовок и описание у каждого раздела, подписанные поля форм и новые скриншоты ([руководство](docs/ru/ADMIN_PANEL_CURRENT.md)). Тег v28.9.0 добавил сетевую аналитику узлов: ASN, владельца сети, страну RIR и репутацию IP с отметкой свежести ([регламент](docs/ru/NETWORK_INTEL_CURRENT.md)). Тег v28.8.0 добавил среду плагинов: подписанные пакеты, подтверждение прав, обновление и откат без перезапуска ([регламент](docs/ru/PLUGINS_CURRENT.md)). Тег v28.7.0 добавил email-канал поддержки в Support Pro 3.7: письма клиентов становятся обращениями, ответы уходят письмом ([регламент](docs/ru/SUPPORT_EMAIL_CHANNEL_CURRENT.md)). Тег v28.6.0 добавил виджет подписки на рабочий стол Android и несколько профилей магазинов в админ-приложениях ([регламент](docs/ru/WIDGET_AND_PROFILES_CURRENT.md)). Тег v28.5.0 добавил нативные push-уведомления в приложения Android и iOS ([регламент](docs/ru/PUSH_NOTIFICATIONS_CURRENT.md)). Тег v28.4.0 перевёл админ-панель, личный кабинет и Telegram Mini App на Next.js в дизайне Remna Dark, добавил сверяемый перенос истории подписок и платежей с откатом ([регламент](docs/ru/HISTORY_IMPORT_CURRENT.md)) и редактирование профиля клиента. Тег v28.3.0 добавил типизированный реестр 96 live-настроек с зашифрованными секретами, staged apply, версионным откатом и audit. Ожидаемая версия `/health` и API остаётся `21.5.1`, migration head — `0068_network_intel`. [Полные заметки](docs/ru/RELEASE_V28_11_0.md). Открытые внешние проверки не объявлены готовыми; production gate закрыт.

Импорт users.db и массовые операции доступны роли admin в «Пользователи → Импорт и массовые операции». Порядок mapping, preview, применения и границы переноса: [инструкция](docs/ru/CUSTOMER_OPERATIONS_CURRENT.md).

В v21.3.0 добавлены [редакторы новостей, лендингов и юридических страниц](docs/ru/CONTENT_PUBLISHING_CURRENT.md), [промогруппы и персональные офферы](docs/ru/PERSONAL_OFFERS_CURRENT.md), пять previewed массовых действий включая ограничение/восстановление доступа в магазин.

В v21.4.0 добавлены [вложенные меню Telegram и Mini App](docs/ru/MENU_TREE_CURRENT.md): папки до четырёх уровней, стили, custom emoji, безопасные миниатюры и предпросмотр.

В v21.5.0 исправлена [синхронизация истории Support Pro после merge/split](docs/ru/SUPPORT_REMOTE_HISTORY_CURRENT.md): сообщения и файлы сохраняют идентичность, исходная очередь блокируется, внутренние заметки остаются на месте.
