# Документация VPN Shop by Corgi

Текущий тег дистрибутива: **v28.20.0**. Внутренняя версия runtime/API: **21.5.1**, миграция магазина **0073_e2e_v2**, Support Pro **0008** / 3.8. Реальные платежи открыты сразу после установки; незавершённые внешние проверки описаны отдельно.

| Задача | Инструкция |
| --- | --- |
| **Запустить магазин с нуля до первой продажи** | [Руководство по запуску](docs/ru/LAUNCH_GUIDE.md) |
| **Работать с каждым разделом панели (30 модулей)** | [Инструкции по модулям](docs/ru/modules/README.md) |
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
| Сквозная проверка платежей на стенде (по желанию) | [Staging E2E v2](docs/ru/STAGING_E2E_V2_IMPLEMENTATION.md) |
| Опросы | [Опросы и награды](docs/ru/WORKSPACE_SURVEYS.md) |
| Конкурсы и колесо | [Конкурсы и призы](docs/ru/WORKSPACE_GIVEAWAYS.md) |
| Support Pro и история | [Мост поддержки](docs/ru/WORKSPACE_SUPPORT_BRIDGE.md) |
| Email-канал поддержки | [Email-канал](docs/ru/SUPPORT_EMAIL_CHANNEL_CURRENT.md) |
| Глубокий анализ трафика на узлах (классификатор, nDPI) | [Анализ трафика](docs/ru/TRAFFIC_ANALYSIS_CURRENT.md) |
| Торренты на узлах (BitTorrent по журналу Xray) | [Торренты](docs/ru/TORRENT_DETECTION_CURRENT.md) |
| Терминал узлов (оболочка на VPN-сервере) | [Терминал узлов](docs/ru/NODE_TERMINAL_CURRENT.md) |
| Собственный приём почты (MX) для служебных адресов | [Приём почты](docs/ru/MAIL_RECEIVER_CURRENT.md) |
| Почтовый домен: SPF, DKIM, DMARC и отчёты | [Почтовый домен](docs/ru/MAIL_DOMAIN_CURRENT.md) |
| Zendesk и Freshdesk в Support Pro | [Мост helpdesk](docs/ru/SUPPORT_HELPDESK_BRIDGE_CURRENT.md) |
| Плагины и внешние сервисы | [Плагины](docs/ru/PLUGINS_CURRENT.md) |
| ASN и репутация адресов узлов | [Сеть узлов](docs/ru/NETWORK_INTEL_CURRENT.md) |
| Разделы, кнопки и поля админ-панели | [Админ-панель](docs/ru/ADMIN_PANEL_CURRENT.md) |
| Вход по ключу доступа в приложениях | [Ключи доступа в Android и iOS](docs/ru/NATIVE_PASSKEYS_CURRENT.md) |
| Обновить базу и приложения | [Обновление](docs/ru/WORKSPACE_UPGRADE.md) |
| Android/iOS | [MOBILE.md](MOBILE.md) |
| Push-уведомления в приложениях | [Push Android/iOS](docs/ru/PUSH_NOTIFICATIONS_CURRENT.md) |
| Виджет Android и профили админ-приложений | [Виджет и профили](docs/ru/WIDGET_AND_PROFILES_CURRENT.md) |
| Резервные копии, восстановление, аварийный режим | [Модуль 30](docs/ru/modules/30-backups-recovery.md), [полная копия](docs/ru/BACKUP_CURRENT.md) |
| Резервирование, диагностика и инциденты | [Эксплуатация](OPERATIONS_RUNBOOK_RU.md) |
| Права и защита данных | [SECURITY.md](SECURITY.md) |
| HTTP API | [API_REFERENCE_RU.md](API_REFERENCE_RU.md) |
| Карта проекта и дизайн | [PROJECT_MAP_RU.md](docs/PROJECT_MAP_RU.md) |
| Дерево каталогов и архитектурные границы | [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) |
| Проверки этого выпуска | [Отчёт v28.20.0](docs/ru/RELEASE_V28_20_0.md) |
| Что ещё не реализовано | [Матрица покрытия](docs/ru/WORKSPACE_COVERAGE.md), [критерии завершения](docs/ru/MATRIX_COMPLETION_21_5_1.md) |

Исторические корневые справочники сохранены в `docs/archive/*_BEFORE_ALPHA_6.md`. Они фиксируют прежние версии и могут описывать отключённые кассы, старую структуру кода и неподтверждённые сценарии. Для текущей установки используйте инструкции выше. Исторические release notes остаются без изменения.

Справочники: [ключи доступа администратора](docs/ru/ADMIN_PASSKEYS.md), [метрики, dashboard и alerts](docs/ru/OPERATIONS_MONITORING.md). Мобильный workflow использует версию текущего манифеста; без owner signing secrets APK/IPA не объявляются подписанными production assets.

## Выпуск v28.20.0

Тег v28.20.0 открыл реальные платежи сразу после установки с аварийной остановкой; staging E2E v2 стал добровольным ([заметки](docs/ru/RELEASE_V28_20_0.md)). Тег v28.19.0 добавил допуск реальных платежей через [staging E2E v2](docs/ru/STAGING_E2E_V2_IMPLEMENTATION.md) с подписанным результатом стенда и решения по сигналам антифрода ([заметки](docs/ru/RELEASE_V28_19_0.md)). Тег v28.18.0 полностью обновил инструкции: [руководство по запуску](docs/ru/LAUNCH_GUIDE.md) и [30 инструкций по модулям](docs/ru/modules/README.md); в админке — редактор тарифов с выбором профиля Remnawave, раздел «Рефералы и партнёры», исправленный выход из аварийного режима, наблюдения антиабуза из журнала Xray ([заметки](docs/ru/RELEASE_V28_18_0.md)). Тег v28.17.0 добавил собственный приём почты (MX) для служебных адресов: SPF, DKIM, DMARC, грейлистинг, лимиты, ClamAV, отчёты DMARC и обращения Support Pro ([инструкция](docs/ru/MAIL_RECEIVER_CURRENT.md)). Тег v28.16.0 добавил глубокий анализ трафика на узлах: встроенный классификатор (BitTorrent, DHT, uTP, трекеры, эвристика шифрованного BitTorrent) или nDPI с привязкой к клиенту по журналу Xray ([инструкция](docs/ru/TRAFFIC_ANALYSIS_CURRENT.md)). Тег v28.15.0 добавил распознавание BitTorrent на узлах по журналу Xray: счётчики без адресов, отметку в антиабузе и уведомление клиенту ([инструкция](docs/ru/TORRENT_DETECTION_CURRENT.md)). Тег v28.14.0 добавил терминал узлов: оболочку на VPN-сервере через агент с подтверждением 2FA и зашифрованной записью сессии ([инструкция](docs/ru/NODE_TERMINAL_CURRENT.md)). Тег v28.13.0 добавил проверку почтового домена (MX, SPF, DKIM, DMARC) и отчёты DMARC ([инструкция](docs/ru/MAIL_DOMAIN_CURRENT.md)). Тег v28.12.0 добавил в Support Pro 3.8 мост Zendesk и Freshdesk ([инструкция](docs/ru/SUPPORT_HELPDESK_BRIDGE_CURRENT.md)). Тег v28.11.0 добавил ключи доступа в приложения Android и iOS ([инструкция](docs/ru/NATIVE_PASSKEYS_CURRENT.md)). Тег v28.10.0 переработал админ-панель: страница «Все разделы» с описанием каждой функции, группы как в рабочем порядке оператора, заголовок и описание у каждого раздела, подписанные поля форм и новые скриншоты ([руководство](docs/ru/ADMIN_PANEL_CURRENT.md)). Тег v28.9.0 добавил сетевую аналитику узлов: ASN, владельца сети, страну RIR и репутацию IP с отметкой свежести ([регламент](docs/ru/NETWORK_INTEL_CURRENT.md)). Тег v28.8.0 добавил среду плагинов: подписанные пакеты, подтверждение прав, обновление и откат без перезапуска ([регламент](docs/ru/PLUGINS_CURRENT.md)). Тег v28.7.0 добавил email-канал поддержки в Support Pro 3.7: письма клиентов становятся обращениями, ответы уходят письмом ([регламент](docs/ru/SUPPORT_EMAIL_CHANNEL_CURRENT.md)). Тег v28.6.0 добавил виджет подписки на рабочий стол Android и несколько профилей магазинов в админ-приложениях ([регламент](docs/ru/WIDGET_AND_PROFILES_CURRENT.md)). Тег v28.5.0 добавил нативные push-уведомления в приложения Android и iOS ([регламент](docs/ru/PUSH_NOTIFICATIONS_CURRENT.md)). Тег v28.4.0 перевёл админ-панель, личный кабинет и Telegram Mini App на Next.js в дизайне Remna Dark, добавил сверяемый перенос истории подписок и платежей с откатом ([регламент](docs/ru/HISTORY_IMPORT_CURRENT.md)) и редактирование профиля клиента. Тег v28.3.0 добавил типизированный реестр 96 live-настроек с зашифрованными секретами, staged apply, версионным откатом и audit. Ожидаемая версия `/health` и API остаётся `21.5.1`, migration head — `0073_e2e_v2`. [Полные заметки](docs/ru/RELEASE_V28_19_0.md). Открытые внешние проверки не объявлены готовыми; production gate закрыт.

Импорт users.db и массовые операции доступны роли admin в «Пользователи → Импорт и массовые операции». Порядок mapping, preview, применения и границы переноса: [инструкция](docs/ru/CUSTOMER_OPERATIONS_CURRENT.md).

В v21.3.0 добавлены [редакторы новостей, лендингов и юридических страниц](docs/ru/CONTENT_PUBLISHING_CURRENT.md), [промогруппы и персональные офферы](docs/ru/PERSONAL_OFFERS_CURRENT.md), пять previewed массовых действий включая ограничение/восстановление доступа в магазин.

В v21.4.0 добавлены [вложенные меню Telegram и Mini App](docs/ru/MENU_TREE_CURRENT.md): папки до четырёх уровней, стили, custom emoji, безопасные миниатюры и предпросмотр.

В v21.5.0 исправлена [синхронизация истории Support Pro после merge/split](docs/ru/SUPPORT_REMOTE_HISTORY_CURRENT.md): сообщения и файлы сохраняют идентичность, исходная очередь блокируется, внутренние заметки остаются на месте.
