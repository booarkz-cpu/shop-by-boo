# Проверка админки по модулям

Сгенерировано `python scripts/verify-admin-matrix.py` (этап 18). Для каждого модуля [матрицы управляемости](ADMIN_CONTROL_MATRIX.md) проверено, что каждый маршрут API, который что-то меняет (POST, PUT, PATCH, DELETE), вызывается тестом — backend-тестом или браузерным e2e. Также проверено, что у каждого раздела модуля есть скриншот. Сами тесты выполняются в CI; здесь — какой тест что покрывает.

**PASS** — все изменяющие маршруты покрыты тестами, у всех разделов есть скриншот. **PARTIAL** — ниже перечислено, что не покрыто.

Изменяющих маршрутов: **351 из 351** покрыты тестами; модулей PASS: **30 из 30**.

| № | Модуль | Маршрутов | Изменяющих | Покрыто тестами | Статус |
| --- | --- | --- | --- | --- | --- |
| 1 | Dashboard | 17 | 4 | 4 | PASS |
| 2 | Users | 37 | 18 | 18 | PASS |
| 3 | Subscriptions | 12 | 7 | 7 | PASS |
| 4 | Tariffs | 18 | 12 | 12 | PASS |
| 5 | Devices | 6 | 4 | 4 | PASS |
| 6 | Payments | 35 | 19 | 19 | PASS |
| 7 | Finance | 12 | 7 | 7 | PASS |
| 8 | Promo Codes | 14 | 11 | 11 | PASS |
| 9 | Gifts | 6 | 3 | 3 | PASS |
| 10 | Referrals | 13 | 8 | 8 | PASS |
| 11 | Remnawave | 32 | 15 | 15 | PASS |
| 12 | Installation | 85 | 56 | 56 | PASS |
| 13 | Servers | 11 | 8 | 8 | PASS |
| 14 | Nodes | 35 | 26 | 26 | PASS |
| 15 | Domains | 7 | 6 | 6 | PASS |
| 16 | Certificates | 2 | 1 | 1 | PASS |
| 17 | Reverse Proxy | 1 | 0 | 0 | PASS |
| 18 | Subscription Portal | 12 | 7 | 7 | PASS |
| 19 | Node Extensions | 54 | 36 | 36 | PASS |
| 20 | Monitoring | 17 | 9 | 9 | PASS |
| 21 | Backups | 17 | 11 | 11 | PASS |
| 22 | Updates | 14 | 9 | 9 | PASS |
| 23 | Automation | 9 | 4 | 4 | PASS |
| 24 | Telegram | 31 | 22 | 22 | PASS |
| 25 | Integrations | 17 | 11 | 11 | PASS |
| 26 | Plugins | 14 | 11 | 11 | PASS |
| 27 | Security | 28 | 12 | 12 | PASS |
| 28 | Logs | 8 | 4 | 4 | PASS |
| 29 | GitHub | 5 | 2 | 2 | PASS |
| 30 | Settings | 9 | 8 | 8 | PASS |
