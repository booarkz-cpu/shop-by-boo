# Управляемость из админки — v28.101.0

Сгенерировано командой `python scripts/generate-admin-matrix.py` из маршрутов приложения (`backend/app/admin_center.py`). Те же данные показывает «Система → Админ-центр».

Операции определяются по маршрутам API: GET → чтение, POST → создание, PUT/PATCH → изменение, DELETE → удаление; поиск/фильтр — параметры запроса (`status`, `q`, `actor`, `since`…); настройки и проверка — по путям (`config`, `test`, `health`…); журнал — изменяющий обработчик пишет в `audit_logs`. Статус `IMPLEMENTED` значит: раздел и API есть; `PASS` (этап 18) — каждое изменяющее действие модуля проверено тестом и у его разделов есть скриншоты ([ADMIN_VERIFICATION](ADMIN_VERIFICATION.md)).

Модулей с разделом в панели: **30 из 30**.

| № | Модуль | Разделы панели | Маршрутов API | Чтение | Создание | Изменение | Удаление | Поиск/фильтр | Настройки | Проверка | Журнал | Права | Статус |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Dashboard | Главная, Командный центр | 17 | ✓ | ✓ | ✓ | · | · | ✓ | · | ✓ | `analytics.read`, `provision_nodes`, `read`, `security.manage`, `settings.runtime.write` | PASS |
| 2 | Users | Клиенты магазина, Карточка клиента, Пользователи VPN | 37 | ✓ | ✓ | ✓ | · | ✓ | · | ✓ | ✓ | `backups.write`, `manage_users`, `ops.releases`, `provision_nodes`, `read`, `users.bulk`, `users.import`, `users.keys`, `users.read`, `users.write` | PASS |
| 3 | Subscriptions | Изменения подписок | 12 | ✓ | ✓ | ✓ | · | · | · | · | ✓ | `manage_plans`, `payments.read`, `payments.refund`, `read`, `users.write` | PASS |
| 4 | Tariffs | Тарифы, Конструктор тарифов, Пакеты трафика | 18 | ✓ | ✓ | ✓ | ✓ | · | · | ✓ | ✓ | `manage_plans`, `read` | PASS |
| 5 | Devices | Устройства | 6 | ✓ | ✓ | ✓ | ✓ | · | · | · | ✓ | `provision_nodes`, `security.manage` | PASS |
| 6 | Payments | Платежи, Платёжные агенты, Возвраты, Проверка платежей | 35 | ✓ | ✓ | ✓ | · | ✓ | ✓ | ✓ | ✓ | `ops.diagnostics`, `ops.providers`, `payments.read`, `payments.reconcile`, `payments.refund`, `payments.retry`, `read`, `security.manage`, `settings.runtime.write`, `staging_e2e.manage` | PASS |
| 7 | Finance | Финансовый журнал, Чеки в налоговую | 12 | ✓ | ✓ | ✓ | ✓ | · | · | ✓ | ✓ | `analytics.read`, `manage_plans`, `payments.read`, `payments.reconcile`, `payments.write`, `read` | PASS |
| 8 | Promo Codes | Акции и рассылки, Группы и предложения | 14 | ✓ | ✓ | ✓ | ✓ | · | · | · | ✓ | `manage_marketing`, `marketing.read` | PASS |
| 9 | Gifts | Подарки | 6 | ✓ | ✓ | · | ✓ | · | · | · | ✓ | `manage_marketing`, `marketing.read` | PASS |
| 10 | Referrals | Рефералы и партнёры | 13 | ✓ | ✓ | ✓ | ✓ | · | · | ✓ | ✓ | `referrals.read`, `referrals.reconcile`, `referrals.withdrawals.approve`, `referrals.withdrawals.pay`, `referrals.withdrawals.read` | PASS |
| 11 | Remnawave | Remnawave: панель, Серверы | 32 | ✓ | ✓ | ✓ | ✓ | ✓ | · | ✓ | ✓ | `backups.write`, `manage_users`, `ops.diagnostics`, `ops.releases`, `provision_nodes`, `read`, `settings.runtime.write`, `users.keys`, `users.read` | PASS |
| 12 | Installation | Установка Remnawave | 67 | ✓ | ✓ | ✓ | ✓ | · | ✓ | ✓ | ✓ | `provision_nodes`, `read`, `settings.runtime.write` | PASS |
| 13 | Servers | Серверы, Планирование мощности, Оркестратор | 11 | ✓ | ✓ | ✓ | · | · | ✓ | ✓ | ✓ | `ops.diagnostics`, `provision_nodes`, `settings.runtime.write` | PASS |
| 14 | Nodes | Серверы, Терминал узлов, Торренты на узлах | 33 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `manage_users`, `nodes.terminal`, `ops.diagnostics`, `provision_nodes`, `read`, `security.manage`, `settings.runtime.write` | PASS |
| 15 | Domains | Домены и сертификаты | 7 | ✓ | ✓ | ✓ | ✓ | · | · | ✓ | ✓ | `read`, `settings.runtime.write` | PASS |
| 16 | Certificates | Домены и сертификаты | 2 | ✓ | ✓ | · | · | · | · | ✓ | · | `read` | PASS |
| 17 | Reverse Proxy | Домены и сертификаты | 1 | ✓ | · | · | · | · | · | · | · | `read` | PASS |
| 18 | Subscription Portal | Портал подписки | 12 | ✓ | ✓ | ✓ | ✓ | ✓ | · | ✓ | ✓ | `ops.diagnostics`, `settings.runtime.write`, `users.write` | PASS |
| 19 | Node Extensions | Расширения Remnawave | 32 | ✓ | ✓ | ✓ | ✓ | · | ✓ | ✓ | ✓ | `provision_nodes`, `read`, `settings.runtime.write` | PASS |
| 20 | Monitoring | Мониторинг, Состояние системы, Запуск и оповещения, Инциденты, Доступность и качество | 17 | ✓ | ✓ | ✓ | ✓ | · | · | ✓ | ✓ | `ops.diagnostics`, `read`, `referrals.withdrawals.approve`, `referrals.withdrawals.pay`, `settings.runtime.write` | PASS |
| 21 | Backups | Резервные копии, Восстановление | 17 | ✓ | ✓ | ✓ | ✓ | · | ✓ | ✓ | ✓ | `backups.read`, `backups.restore`, `backups.write`, `manage_admins`, `payments.retry`, `read` | PASS |
| 22 | Updates | Обновления, Развёртывания | 14 | ✓ | ✓ | ✓ | · | · | · | ✓ | ✓ | `backups.write`, `ops.releases`, `provision_nodes`, `read`, `settings.runtime.write` | PASS |
| 23 | Automation | Automation Center, Автоматизация, Очередь задач, Фоновые процессы | 9 | ✓ | ✓ | · | ✓ | · | ✓ | ✓ | ✓ | `feature_flags.manage`, `manage_marketing`, `ops.diagnostics`, `payments.retry`, `read` | PASS |
| 24 | Telegram | Telegram-бот, Меню бота и Mini App, Дерево кнопок, Баннеры бота, Документы | 31 | ✓ | ✓ | ✓ | ✓ | · | · | ✓ | ✓ | `legal.write`, `manage_broadcasts`, `manage_content`, `manage_marketing`, `marketing.read`, `ops.diagnostics`, `read`, `settings.runtime.read` | PASS |
| 25 | Integrations | Интеграции, Почтовый домен: SPF, DKIM, DMARC | 17 | ✓ | ✓ | ✓ | · | · | · | ✓ | ✓ | `analytics.read`, `ops.diagnostics`, `security.manage`, `settings.runtime.write` | PASS |
| 26 | Plugins | Плагины | 14 | ✓ | ✓ | ✓ | ✓ | · | ✓ | · | ✓ | `ops.diagnostics`, `security.manage` | PASS |
| 27 | Security | Защита и 2FA, Ключи доступа, Роли и администраторы, Сессии, Антифрод | 28 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `analytics.read`, `manage_admins`, `ops.diagnostics`, `read`, `security.manage`, `security.stepup`, `sessions.manage`, `sessions.self`, `settings.runtime.write`, `users.read` | PASS |
| 28 | Logs | Журнал действий, События, Мониторинг | 6 | ✓ | ✓ | · | · | ✓ | · | · | ✓ | `ops.diagnostics`, `read` | PASS |
| 29 | GitHub | Обновления | 4 | ✓ | ✓ | ✓ | · | · | · | · | ✓ | `ops.releases`, `settings.runtime.write` | PASS |
| 30 | Settings | Настройки без перезапуска, Функции и модули, Оформление | 9 | ✓ | ✓ | ✓ | ✓ | · | ✓ | · | ✓ | `manage_content`, `settings.runtime.read`, `settings.runtime.write` | PASS |

«·» — у модуля нет маршрута для этой операции; это не обязательно недостаток. Например, у журнала действий нет удаления: записи неизменяемы.

## Разделы вне 30 модулей задания

Ещё 157 административных маршрутов относятся к разделам, которых нет в списке задания: поддержка, кабинет и приложения, конкурсы, опросы, страницы, корпоративные клиенты и другие. Они управляются из своих разделов панели. Префиксы и число маршрутов: `advertisements` 2, `app-analytics` 1, `app-config` 2, `apps` 4, `cabinet` 4, `cabinet-texts` 1, `churn` 2, `cohorts` 1, `connection-quality` 1, `content` 1, `control-center` 1, `corporate` 6, `corporate-accounts` 1, `corporate-seller` 1, `digest` 2, `dns-filter` 1, `e2e-v2` 6, `email-templates` 2, `enterprise` 7, `family` 1, `feedback` 1, `fields` 2, `giveaways` 6, `guest-checkout` 1, `images` 2, `incident-mode` 1, `install` 7, `loyalty` 1, `marketing` 1, `marketplace` 6, `miniapp` 4, `mobile` 4, `mobile-layout` 1, `moderation` 7, `network` 2, `notifications` 1, `openapi.json` 1, `pages` 6, `push` 1, `push-campaigns` 4, `push-style` 1, `speedtest` 1, `standby` 2, `status-page` 2, `subscription-feed` 1, `support` 11, `support-pro` 2, `surveys` 5, `system` 1, `v15` 2, `v16` 2, `v3` 5, `v41` 16.
