# Документация VPN Shop by Corgi

Текущий тег дистрибутива: **v26**. Внутренняя версия runtime/API: **21.5.1**, миграция магазина **0062_support_delivery_identity**, Support Pro **0006** / 3.6. Production-ready не подтверждён: рабочие сценарии и незавершённые внешние проверки описаны отдельно, реальные платежи не сертифицированы.

| Задача | Инструкция |
| --- | --- |
| Выбрать путь установки | [INSTALL.md](INSTALL.md) |
| Выполнить шаги через SSH/Termius | [INSTALL_STEPS.md](INSTALL_STEPS.md) |
| Найти инструкции по всем функциям | [FUNCTIONS.md](FUNCTIONS.md) |
| Кабинет и Mini App | [Пользователь](docs/ru/WORKSPACE_USER_GUIDE.md) |
| Настроить административные разделы | [Администратор](docs/ru/WORKSPACE_ADMIN_GUIDE.md) |
| Пароль, email и восстановление | [Безопасность аккаунта](docs/ru/WORKSPACE_ACCOUNT_SECURITY.md) |
| Несколько подписок и подарки | [Подписки](docs/ru/WORKSPACE_SUBSCRIPTIONS.md) |
| Смена тарифа, трафик и возвраты | [Коммерческие операции](docs/ru/WORKSPACE_COMMERCE.md) |
| Кассы и ограничения допуска | [Платежи](docs/ru/WORKSPACE_PAYMENTS.md) |
| Опросы | [Опросы и награды](docs/ru/WORKSPACE_SURVEYS.md) |
| Конкурсы и колесо | [Конкурсы и призы](docs/ru/WORKSPACE_GIVEAWAYS.md) |
| Support Pro и история | [Мост поддержки](docs/ru/WORKSPACE_SUPPORT_BRIDGE.md) |
| Обновить базу и приложения | [Обновление](docs/ru/WORKSPACE_UPGRADE.md) |
| Android/iOS | [MOBILE.md](MOBILE.md) |
| Резервирование, диагностика и инциденты | [Эксплуатация](OPERATIONS_RUNBOOK_RU.md) |
| Права и защита данных | [SECURITY.md](SECURITY.md) |
| HTTP API | [API_REFERENCE_RU.md](API_REFERENCE_RU.md) |
| Карта проекта и дизайн | [PROJECT_MAP_RU.md](docs/PROJECT_MAP_RU.md) |
| Дерево каталогов и архитектурные границы | [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) |
| Проверки этого выпуска | [Отчёт v26](docs/ru/RELEASE_V26.md) |
| Что ещё не реализовано | [Матрица покрытия](docs/ru/WORKSPACE_COVERAGE.md), [критерии завершения](docs/ru/MATRIX_COMPLETION_21_5_1.md) |

Исторические корневые справочники сохранены в `docs/archive/*_BEFORE_ALPHA_6.md`. Они фиксируют прежние версии и могут описывать отключённые кассы, старую структуру кода и неподтверждённые сценарии. Для текущей установки используйте инструкции выше. Исторические release notes остаются без изменения.

Изменения alpha.7: [ключи доступа администратора](docs/ru/ADMIN_PASSKEYS.md), [метрики, dashboard и alerts](docs/ru/OPERATIONS_MONITORING.md). Мобильный workflow использует версию текущего манифеста; без owner signing secrets APK/IPA не объявляются подписанными production assets.

## Выпуск v26

Тег v26 закрепляет проверенный commit `98ceb7f`, зелёные CI/Docker-сборки и runtime `21.5.1`. Установочные команды используют тег `v26`; ожидаемая версия `/health` и API остаётся `21.5.1`. [Полные заметки](docs/ru/RELEASE_V26.md). Открытые внешние проверки не объявлены готовыми; production gate закрыт.

Импорт users.db и массовые операции доступны роли admin в «Клиенты → Импорт и массовые операции». Порядок mapping, preview, применения и границы переноса: [инструкция](docs/ru/CUSTOMER_OPERATIONS_CURRENT.md).

В v21.3.0 добавлены [редакторы новостей, лендингов и юридических страниц](docs/ru/CONTENT_PUBLISHING_CURRENT.md), [промогруппы и персональные офферы](docs/ru/PERSONAL_OFFERS_CURRENT.md), пять previewed массовых действий включая ограничение/восстановление доступа в магазин.

В v21.4.0 добавлены [вложенные меню Telegram и Mini App](docs/ru/MENU_TREE_CURRENT.md): папки до четырёх уровней, стили, custom emoji, безопасные миниатюры и предпросмотр.

В v21.5.0 исправлена [синхронизация истории Support Pro после merge/split](docs/ru/SUPPORT_REMOTE_HISTORY_CURRENT.md): сообщения и файлы сохраняют идентичность, исходная очередь блокируется, внутренние заметки остаются на месте.
