# v26 — актуальный стабильный дистрибутив

Дата публикации: 9 октября 2026 года. Тег: `v26`. Проверенный commit: `98ceb7f678070ecbc5c590a50a74ea8db067892d`.

## Идентичность версии

`v26` — номер GitHub-релиза и устанавливаемого тега. Внутренняя версия FastAPI runtime остаётся `21.5.1`, поэтому `/health`, `/health/ready` и служебные API возвращают `21.5.1`. Это не ошибка обновления.

| Контракт | Значение |
| --- | --- |
| GitHub tag | `v26` |
| Runtime/API | `21.5.1` |
| Миграция магазина | `0062_support_delivery_identity` |
| Support Pro | `0006` / 3.6 |
| Release commit | `98ceb7f678070ecbc5c590a50a74ea8db067892d` |

## Что подтверждено

- основной GitHub CI завершён успешно;
- Docker workflow завершён успешно для `main` и тега `v26`;
- dependency security audit и сборка пяти контейнеров завершены успешно;
- исправлена переносимость advisory locks между PostgreSQL и SQLite;
- стабилизирован WebAuthn E2E для административных passkeys;
- актуализированы зависимости, карта проекта, PROJECT_SPEC и runbook мониторинга Remnawave;
- обновлены визуальные токены административной панели и кабинета.

## Что не подтверждается самим релизом

Релиз не открывает production-платежи автоматически. Для коммерческого допуска по-прежнему нужны внешний application E2E v2 с реальными тестовыми аккаунтами провайдеров, отдельный Remnawave-стенд, SMTP-проверка, restore drill и подписанные владельцем мобильные пакеты. Флаги `production_ready`, `full_function_transfer`, `production_e2e_verified` и `signed` остаются `false`.

## Установка

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v26/install.sh -o /root/shop-install.sh
sudo BRANCH=v26 bash /root/shop-install.sh
```

Либо из Git:

```bash
git clone --branch v26 --depth 1 https://github.com/booarkz-cpu/shop-by-boo.git
cd shop-by-boo
sudo bash deploy/install-vps.sh
```

Полная инструкция: [установка на VDS](DEPLOYMENT_CURRENT.md). Обновление существующего магазина: [согласованный upgrade](WORKSPACE_UPGRADE.md).

## Проверка после установки

```bash
docker compose ps
docker compose exec -T backend python -c 'from app.main import APP_VERSION; print(APP_VERSION)'
docker compose exec -T backend alembic current
docker compose logs --tail=100 backend worker support_pro support_worker
```

Ожидаются runtime `21.5.1`, migration head `0062_support_delivery_identity` и Support Pro `0006`.

## Документация

- [главный README](../../README.md);
- [единый указатель](../../DOCUMENTATION.md);
- [проектная спецификация](../../PROJECT_SPEC.md);
- [структура проекта](../../PROJECT_STRUCTURE.md);
- [карта функционального покрытия](WORKSPACE_COVERAGE.md);
- [мониторинг Remnawave](../NODE_MONITORING_RUNBOOK_RU.md);
- [операционный регламент](../../OPERATIONS_RUNBOOK_RU.md).
