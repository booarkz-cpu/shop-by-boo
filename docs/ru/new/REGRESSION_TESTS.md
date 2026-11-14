# Regression-тесты (этап 4)

Тесты, добавленные или изменённые в v28.58.0. Все входят в обычный CI: backend — `pytest` в job «Backend • Python + tests + migrations», кабинет — `npm test` (vitest), админка — e2e Chromium.

| Тест | Что проверяет | Ошибка | Где запускается |
| --- | --- | --- | --- |
| `apps/user-cabinet/src/http-json.test.tsx` | HTML и не-JSON в успешном ответе — ошибка с адресом запроса; JSON, пустой ответ, 204 и тело ответа с ошибкой — как раньше | BUG-H1, BUG-H2 | vitest |
| `tests/test_frontend_regressions.py` | Оба клиента API читают ответ через `readJsonBody`; функция баннера в «Документах» одна; `apps/lucy-admin/web/Dockerfile` копирует каждый файл кабинета, который импортирует админка | BUG-H1, BUG-H2, BUG-H3 | pytest |
| `tests/test_schema_matches_migrations.py` | На базе, поднятой миграциями: autogenerate не находит отличий от моделей; нет двух индексов на одних колонках; `gift_redemptions.operation_key` — `NOT NULL` | BUG-A1, BUG-A2 | pytest на PostgreSQL CI (`AUDIT_TEST_DATABASE_URL`) |
| `tests/test_subscription_middleware.py::test_webhook_receivers_must_be_public` | Получатель на `127.0.0.1`, `192.168.*`, `localhost`, `*.localhost` отклоняется при сохранении; к старому сохранённому адресу соединения нет | BUG-A3 | pytest |
| `tests/test_reconciliation.py::test_postback_addresses_must_be_public` | Постбэк на внутренний адрес (в том числе IPv6 `::1`) отклоняется при сохранении | BUG-A3 | pytest |
| `tests/test_provisioner.py` | Установка ноды по поддельному SSH: нет `get.docker.com`, есть проверка отпечатка, значения экранированы, ошибка без вывода, неверный запрос не подключается. Сценарий установщика в bash с поддельными утилитами: верный ключ — репозиторий добавлен; чужой ключ — код 21, репозиторий не добавлен; другая ОС — код 20; Docker уже стоит — ничего не ставится | BUG-A4, TECH-09 | pytest (нужен bash) |
| `tests/test_code_entry_rate_limits.py` | 11-й ввод кода в минуту с одного адреса получает 429 на каждом из шести маршрутов | BUG-A5 | pytest |
| `tests/test_heartbeat.py` | Файл жизни: свежий / устаревший / отсутствует; код выхода `python -m app.heartbeat`; worker не отмечается, когда Redis недоступен; у каждого долгоживущего сервиса compose есть healthcheck | BUG-A6 | pytest |
| `tests/test_history_import.py::test_uuid_of_remnawave_2_is_blocked_with_the_reason` | UUID блокируется в предпросмотре с причиной, числовой id той же выгрузки — «новый»; остальные тесты импорта используют короткие числовые id | BUG-A7 | pytest |
| `tests/test_v44_enterprise_suite.py::test_payment_provider_health_bootstraps_without_admin_page` | Проходит без `PAYMENTS_SANDBOX` в окружении | BUG-T1 | pytest |
| `tests/test_route_authorization.py` | Все административные маршруты требуют право; каждый изменяющий маршрут проверяет вызывающего (сессию, подпись, токен) или явно публичен; делегирующие и самопроверяющие обработчики действительно проверяют | SEC-05 | pytest |
