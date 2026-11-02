# Реестр ошибок

Заполняется на этапах 3–4. Каждая запись: ID, где найдено, симптом, первопричина, исправление, regression-тест, статус. Исторические ошибки из задания проверяются в первую очередь.

| ID | Где | Симптом | Первопричина | Исправление | Тест | Статус |
| --- | --- | --- | --- | --- | --- | --- |
| BUG-H1 | admin, cabinet, Mini App | `Cannot read properties of undefined (reading 'trim')` | Гипотеза этапа 3 (TECH-01): `req()` возвращает `{}` на ответ 2xx, который не JSON, и поле строки оказывается `undefined`. Прежние правки (`2673787d`, `a251c11b`, `a708b318`) нормализовали значение на месте вызова | — | — | IN_PROGRESS (причина не подтверждена воспроизведением) |
| BUG-H2 | admin, cabinet, Mini App | `(s \|\| []).map is not a function` | Гипотеза этапа 3 (TECH-01): тот же `{}` или объект вместо массива проходит через `(x \|\| [])`, потому что объект истинный; 70 таких мест | — | — | IN_PROGRESS (причина не подтверждена воспроизведением) |
| BUG-H3 | `admin/src/documents.tsx` | Внутри `edit` вложена вторая копия функции `banner`; работает, но код дублируется, и правка одной копии не меняет другую | Ошибка слияния | — | — | NOT_STARTED |
| BUG-A1 | `backend/alembic/versions/0032_v2_0_0_product_features.py` | `gift_redemptions.operation_key` допускает `NULL`, в модели `NOT NULL` | Колонка добавлена `nullable=True` и не ужесточена | — | — | NOT_STARTED |
| BUG-A2 | миграции, 16 таблиц | 26 лишних индексов, расхождение моделей и миграций (110 операций autogenerate) | Модели с `unique=True, index=True` поверх ограничений, созданных миграциями | — | — | NOT_STARTED |
| BUG-A3 | `webhook_tee.py`, `ad_postbacks.py` | Запросы на любые `https://`, включая внутренние адреса (SEC-01) | Не используется общая проверка публичного адреса | — | — | NOT_STARTED |
| BUG-A4 | `provisioner.py` | `curl https://get.docker.com \| sh` от root на ноде (SEC-02) | Установка Docker непроверенным скриптом | — | — | NOT_STARTED |
| BUG-A5 | `main.py` `RATE_LIMITS` | Нет лимита частоты у погашения подарков, подарочных карт, реферальных и корпоративных кодов, гостевого входа (SEC-03) | Маршруты не добавлены в таблицу | — | — | NOT_STARTED |
| BUG-A6 | `docker-compose.yml` | Нет healthcheck у worker, bot, mail_receiver, support_worker, backend_standby (TECH-08) | — | — | — | NOT_STARTED |
| BUG-A7 | `subscriptions.remnawave_uuid`, `history_import.py` | В колонке числовой `id` панели; импорт может записать UUID, который API 3.4 не принимает (TECH-04) | Название колонки осталось от старого API | — | — | NOT_STARTED |
