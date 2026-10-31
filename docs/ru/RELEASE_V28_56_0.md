# Выпуск v28.56.0 — исправления затенённого API, чёрных экранов и контрактов OpenAPI

Дистрибутив: `v28.56.0`. Runtime/API: `21.5.1`. Head магазина: `0088_filter_and_regions`.
Support Pro: `0008` / 3.8. Мобильные приложения: 3.4.0.

Выпуск **не меняет схему базы данных** и не требует миграций: head остаётся `0088_filter_and_regions`.
Обновление совместимо с `v28.55.0` в обе стороны. Дистрибутив `v28.55.0` остаётся доступным для отката.

## Что исправлено

**Кабинет и Mini App снова показывают трафик.** Путь `GET /api/me/traffic` был зарегистрирован дважды:
`operations_api.py` отвечал счётчиками (`traffic_used_bytes`, `traffic_limit_bytes`, `devices`), а
`panel_usage.py` — разбивкой по дням (`days`, `nodes`, `total_bytes`) для «Моей статистики». Starlette
обслуживает первый совпавший маршрут, поэтому раздел получал ответ без `days` и падал на
`data.days.length` — это и была ошибка `Cannot read properties of undefined (reading 'length')`,
из-за которой блок статистики исчезал. Теперь один обработчик в `panel_usage.py` отдаёт оба набора полей.
Если у панели нет статистики `bandwidth-stats`, `days` остаётся пустым списком, а не `undefined`.

Файлы: `backend/app/panel_usage.py`, `backend/app/operations_api.py`.

**Кнопка «Трафик» в карточке клиента снова работает.** Маршрут `GET /api/admin/users/{user_id}/traffic`
объявлен в `panel_usage.py`; после устранения дубликата он снова виден в таблице маршрутов и отвечает
администратору с правом `users.read`.

**Чёрные экраны панели и кабинета.** Оба приложения рендерятся целиком на клиенте. Исключение в
провайдерах или корневом компоненте размонтировало всё дерево React, и посетитель видел пустую страницу
без объяснения и без выхода. Добавлены `admin/src/app/error.tsx` и `cabinet/src/app/error.tsx` —
экран ошибки Next.js с причиной, повтором (`reset`, сессия сохраняется) и перезагрузкой — и корневые
boundary `AdminErrorBoundary` / `CabinetRootBoundary`, которые ловят сбой выше уровня страницы.
Текст экрана прямо сообщает, что подписка и платежи не затронуты.

Файлы: `admin/src/app/error.tsx`, `cabinet/src/app/error.tsx`, `admin/src/main.tsx`, `cabinet/src/main.tsx`.

**Уникальные `operationId` в OpenAPI.** `/api/webhooks/freekassa` обслуживал GET и POST одним
`api_route`, поэтому FastAPI выводил одинаковый `operationId` для обоих методов и перезаписывал первый
в схеме — сгенерированные клиенты получали задвоенную операцию. Методы разведены на отдельные маршруты
`freekassa_webhook_get` и `freekassa_webhook_post`; поведение подписи и подтверждения платежа не изменилось.

Файл: `backend/app/payments_api.py`.

## Проверки

| Проверка | Результат | Подтверждение |
| --- | --- | --- |
| Lint (ruff 0.14.2) | PASS | `ruff check backend scripts tests` → All checks passed |
| Lint (shell) | PASS | `bash -n` по всем 45 отслеживаемым `*.sh` |
| Backend-тесты | PASS | 1813 passed, 684 skipped (только PostgreSQL-сценарии) |
| Typecheck admin | PASS | `tsc --noEmit` и `tsc --noEmit -p tsconfig.ui.json` |
| Typecheck cabinet | PASS | `tsc --noEmit` |
| Vitest cabinet | PASS | 55 passed (16 файлов) |
| Сборка admin | PASS | `next build` |
| Сборка cabinet | PASS | `next build` |
| Контракты документации | PASS | `check-current-docs.py`, `check-runtime-placeholders.py` |
| Миграции | PASS | `alembic heads` → единственный head `0088_filter_and_regions` |
| Docker Compose | PASS | три compose-файла разбираются, 17/7/3 сервиса |

Добавлены регрессионные тесты: `test_no_path_answers_twice`, `test_openapi_operation_ids_are_unique`,
`test_me_traffic_answers_both_contracts`, `test_me_traffic_still_answers_when_the_panel_has_no_statistics`,
`test_both_frontends_render_an_error_screen_instead_of_a_black_page`.

## Ограничения выпуска

Выпуск **не является** подтверждением готовности к production и не меняет флаги
`production_ready`, `full_function_transfer`, `production_e2e_verified` и `signed` — они остаются `false`.

Не проверено в этом выпуске, требует внешних секретов и доступа:

- реальный платёжный цикл ни одного из 15 провайдеров (нужны ключи магазина);
- живой обмен с Remnawave и обратным прокси (нужны `REMNAWAVE_URL`, `REMNAWAVE_TOKEN`, сервер);
- Telegram-бот и `initData` Mini App (нужен `BOT_TOKEN` и боевой домен);
- OAuth почты, VK и Яндекса (нужны client id/secret);
- ночное автообновление на реальном VPS (нужен хост с systemd и установленным магазином);
- сборка мобильных приложений на устройстве (нужны Android SDK и Xcode).

Пошаговые сценарии для каждого пункта — в [TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md](TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md).
Полный перечень ограничений — в [RELEASE_LIMITATIONS.md](RELEASE_LIMITATIONS.md).

## Обновление

```bash
bash scripts/backup.sh
sudo env APP_DIR=/opt/vpn-shop RELEASE_TAG=v28.56.0 bash /opt/vpn-shop/scripts/update-from-github.sh
```

Миграций нет; откат — повторным запуском обновления с `RELEASE_TAG=v28.55.0`.
