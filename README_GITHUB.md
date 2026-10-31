> Актуальный дистрибутив: `v28.56.0`; runtime/API: `21.5.1`. Точные границы готовности указаны в текущей матрице покрытия.

# VPN Shop by Corgi

Актуальное описание проекта, команды запуска, функциональные ограничения и разрешения: [README.md](README.md). Все инструкции: [DOCUMENTATION.md](DOCUMENTATION.md). Дистрибутив v28.56.0 сохраняет runtime/API v21.5.1 и добавляет безопасные live-настройки; [отчёт](docs/ru/RELEASE_V28_20_0.md), [регламент](docs/ru/RUNTIME_SETTINGS_CURRENT.md), [критерии завершения матрицы](docs/ru/MATRIX_COMPLETION_21_5_1.md).

Справочники: [ключи доступа администратора](docs/ru/ADMIN_PASSKEYS.md), [метрики, dashboard и alerts](docs/ru/OPERATIONS_MONITORING.md). Мобильный workflow использует версию текущего манифеста; без owner signing secrets APK/IPA не объявляются подписанными production assets.

Импорт users.db и массовые операции доступны роли admin в «Пользователи → Импорт и массовые операции». Порядок mapping, preview, применения и границы переноса: [инструкция](docs/ru/CUSTOMER_OPERATIONS_CURRENT.md).

В v21.3.0 добавлены [редакторы новостей, лендингов и юридических страниц](docs/ru/CONTENT_PUBLISHING_CURRENT.md), [промогруппы и персональные офферы](docs/ru/PERSONAL_OFFERS_CURRENT.md), пять previewed массовых действий включая ограничение/восстановление доступа в магазин.

В v21.4.0 добавлены [вложенные меню Telegram и Mini App](docs/ru/MENU_TREE_CURRENT.md): папки до четырёх уровней, стили, custom emoji, безопасные миниатюры и предпросмотр.

В v21.5.0 исправлена [синхронизация истории Support Pro после merge/split](docs/ru/SUPPORT_REMOTE_HISTORY_CURRENT.md): сообщения и файлы сохраняют идентичность, исходная очередь блокируется, внутренние заметки остаются на месте.
