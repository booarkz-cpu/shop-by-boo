> Актуальный дистрибутив: `v28.25.0`; runtime/API: `21.5.1`. Точные границы готовности указаны в текущей матрице покрытия.

# Функции и отдельные инструкции

Наличие реализации означает наличие кода, а не подтверждённую работу чужой кассы, SMTP или VPN. Полная матрица статусов: [WORKSPACE_COVERAGE.md](docs/ru/WORKSPACE_COVERAGE.md).

| Функция | Отдельная инструкция |
| --- | --- |
| Регистрация, вход, профиль и сессии | [Кабинет](docs/ru/WORKSPACE_USER_GUIDE.md), [безопасность аккаунта](docs/ru/WORKSPACE_ACCOUNT_SECURITY.md) |
| Объединение собственных аккаунтов | [Две авторизации, preview, перенос и диагностика](docs/ru/ACCOUNT_MERGE_CURRENT.md) |
| Тарифы, конструктор и триал | [Администратор](docs/ru/WORKSPACE_ADMIN_GUIDE.md), [пользователь](docs/ru/WORKSPACE_USER_GUIDE.md) |
| Несколько подписок, названия и выбор профиля | [Подписки](docs/ru/WORKSPACE_SUBSCRIPTIONS.md) |
| Пропорциональная смена тарифа и докупка трафика | [Коммерческие операции](docs/ru/WORKSPACE_COMMERCE.md) |
| Кошелёк, платежи и квитанции | [Платежи](docs/ru/WORKSPACE_PAYMENTS.md), [кабинет](docs/ru/WORKSPACE_USER_GUIDE.md) |
| Подарки, конструктор подарков и подарочные карты | [Подписки и подарки](docs/ru/WORKSPACE_SUBSCRIPTIONS.md) |
| Автопродление и сохранённые условия | [Подписки](docs/ru/WORKSPACE_SUBSCRIPTIONS.md), [платежи](docs/ru/WORKSPACE_PAYMENTS.md) |
| Промокоды, рассылки и маркетинг | [Администратор](docs/ru/WORKSPACE_ADMIN_GUIDE.md) |
| Опросы, агрегированные ответы и награды | [Опросы](docs/ru/WORKSPACE_SURVEYS.md) |
| Бесплатный конкурс, выбор победителей | [Создание и розыгрыш](docs/ru/WORKSPACE_GIVEAWAYS.md#создать-конкурс) |
| Колесо призов и вероятности | [Настройка колеса](docs/ru/WORKSPACE_GIVEAWAYS.md#создать-колесо-призов) |
| Одноуровневые рефералы и заявки на выплаты | [Кабинет](docs/ru/WORKSPACE_USER_GUIDE.md), [администратор](docs/ru/WORKSPACE_ADMIN_GUIDE.md) |
| Переписка, приватные файлы, Support Pro | [Мост поддержки](docs/ru/WORKSPACE_SUPPORT_BRIDGE.md) |
| Telegram-бот и Mini App | [Администратор](docs/ru/WORKSPACE_ADMIN_GUIDE.md#telegram-бот) |
| Управление Remnawave, устройства и мониторинг | [Администратор](docs/ru/WORKSPACE_ADMIN_GUIDE.md), [архитектура](docs/ru/WORKSPACE_ARCHITECTURE.md) |
| Live-конфигурация, секреты и откат | [Настройки без перезапуска](docs/ru/RUNTIME_SETTINGS_CURRENT.md) |
| Android/iOS клиента и администратора | [Мобильные приложения](MOBILE.md) |
| Backup, восстановление и обновление | [Эксплуатация](OPERATIONS_RUNBOOK_RU.md), [обновление](docs/ru/WORKSPACE_UPGRADE.md) |
| Роли, 2FA, аудит и секреты | [Безопасность](SECURITY.md) |
| HTTP API и идемпотентность | [API](API_REFERENCE_RU.md) |

Многоуровневые рефералы, browser passkeys клиента, merge/split поддержки, безопасный профильный импорт и объединение аккаунтов реализованы в обозначенных границах. Native passkeys, исторический импорт VPN/платежей произвольной схемы, удалённый терминал, полный plugin runtime и native push/виджеты ещё не завершены. Полный реестр без скрытых пунктов: [критерии завершения v21.5.1](docs/ru/MATRIX_COMPLETION_21_5_1.md).

Справочники: [ключи доступа администратора](docs/ru/ADMIN_PASSKEYS.md), [метрики, dashboard и alerts](docs/ru/OPERATIONS_MONITORING.md). Мобильный workflow использует версию текущего манифеста; без owner signing secrets APK/IPA не объявляются подписанными production assets.

## Текущие дополнения

[Настройки без перезапуска](docs/ru/RUNTIME_SETTINGS_CURRENT.md), [многоуровневые рефералы и сеть](docs/ru/REFERRALS_CURRENT.md), [объединение аккаунтов](docs/ru/ACCOUNT_MERGE_CURRENT.md), [согласованный CLI backup](docs/ru/BACKUP_CURRENT.md), [актуальная установка через SSH/Termius](docs/ru/DEPLOYMENT_CURRENT.md).

Импорт users.db и массовые операции доступны роли admin в «Пользователи → Импорт и массовые операции». Порядок mapping, preview, применения и границы переноса: [инструкция](docs/ru/CUSTOMER_OPERATIONS_CURRENT.md).

В v21.3.0 добавлены [редакторы новостей, лендингов и юридических страниц](docs/ru/CONTENT_PUBLISHING_CURRENT.md), [промогруппы и персональные офферы](docs/ru/PERSONAL_OFFERS_CURRENT.md), пять previewed массовых действий включая ограничение/восстановление доступа в магазин.

В v21.4.0 добавлены [вложенные меню Telegram и Mini App](docs/ru/MENU_TREE_CURRENT.md): папки до четырёх уровней, стили, custom emoji, безопасные миниатюры и предпросмотр.

В v21.5.0 исправлена [синхронизация истории Support Pro после merge/split](docs/ru/SUPPORT_REMOTE_HISTORY_CURRENT.md): сообщения и файлы сохраняют идентичность, исходная очередь блокируется, внутренние заметки остаются на месте.
