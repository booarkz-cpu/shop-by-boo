# Отчёт о тестировании — этап 18

Состояние на 2026-11-05, выпуски v28.77.0 – v28.129.0. Все цифры — из прогонов CI на коммите PR #197 (`stage-18-client`), который стал выпуском v28.86.0.

## Наборы и результаты

| Набор | Где | Результат |
| --- | --- | --- |
| Backend: модели, API, миграции, платежи, Remnawave, безопасность (SQLite и PostgreSQL) | «Backend • Python + tests + migrations», 2 части | **2787 passed**, 96 skipped (живые тесты без ключей и платформенные), 0 failed |
| Схема БД против миграций, карта проекта, документы, ссылки, матрица управляемости, сверка админки | там же, шаги `--check` | PASS |
| Админка и кабинет в браузере (Playwright, Chromium): все разделы на 1440 и 390 px, разделы без пункта меню, документы, импорт, passkeys | «Content, customer operations and passkeys • Chromium end-to-end» | **55 passed** |
| Кабинет (vitest) | «cabinet • typecheck + build» | **57 passed** (17 файлов) |
| Admin, Mini App, кабинет: типы и сборка | «admin / miniapp / cabinet • typecheck + build» | PASS |
| Support Pro | «Support Pro • runtime tests» | **118 passed** |
| Android клиент магазина и админка: сборки, UI-тесты | «Android • …» | PASS |
| Встроенный VPN клиента магазина на эмуляторе | `android-vpn-e2e.yml` | PASS: без VPN страница недоступна, с VPN — только через туннель, после отключения — снова недоступна |
| «Корги Люси: клиент»: JUnit, сборки, VPN на эмуляторе | `android-client.yml` | PASS |
| iOS: сборки, расширения туннеля и push, UI-тесты (Swift 6) | «iOS • …» | PASS (4 UI-теста) |
| Контейнеры: запуск без root, пароль Redis | «Containers • …» | PASS |
| Docker Compose, образы | «Docker Compose • configuration», `docker.yml` | PASS |
| Аудит зависимостей | «Dependency vulnerability audit» | PASS |
| Нагрузка и безопасность (базовая линия) | `load-security.yml` | PASS |
| Remnawave вживую: настоящая панель, нода, страница подписки; мастер установки по SSH; SelfSteal и модули нод; on-demand TLS; TinyAuth; вход через магазин; бот в Telegram | `remnawave-live.yml` (7 заданий) | PASS |

## Что проверено на этапе 18 впервые

| Что | Как |
| --- | --- |
| Каждое действие админки, которое что-то меняет (315 маршрутов) | `scripts/verify-admin-matrix.py --check` в CI, [ADMIN_VERIFICATION](ADMIN_VERIFICATION.md) |
| Продление, блокировка, разблокировка на живой панели | `tests/live/test_remnawave_live.py::test_renewal_block_and_reactivation_on_the_real_panel` |
| Трафик действительно идёт через встроенный VPN | эмулятор + Xray на раннере, страница доступна только через туннель |
| Подпись выпускных APK и AAB ключом владельца | сверка отпечатка в `scripts/build-android-apk.sh` и `mobile-release.yml` |
| Вход в панель Remnawave через TinyAuth и через магазин | настоящие образы Caddy и TinyAuth в CI |

## Не проверено (нужен внешний доступ)

См. [KNOWN_LIMITATIONS](KNOWN_LIMITATIONS.md): настоящие VPS и домены (BLOCKED_EXTERNAL), живые платежи (BLOCKED_SECRETS), push на Android (нужен проект Firebase), iOS на устройстве (нужен аккаунт Apple Developer), приложения на настоящем телефоне и ТВ.
