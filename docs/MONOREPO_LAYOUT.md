# Структура монорепозитория: план перекладки

Решение владельца от 2026-11-14 ([OWNER_DECISIONS.md](OWNER_DECISIONS.md), № 14): переложить папки по структуре
мастер-промпта (REQ-MIG-0013 … 0017). Условия самого промпта (REQ-MIG-0018): не создавать пустых модулей и не терять
самостоятельность сборок. Поэтому перекладка идёт этапами — каждый этап отдельным выпуском с полностью зелёным CI —
и только для того, что действительно есть. Работающие серверы обновляются сами (`scripts/update.sh` копирует новое
дерево целиком), поэтому каждый этап проверяет и автообновление.

## Куда что переезжает

| Структура промпта | Сейчас | Этап | Состояние |
|---|---|---|---|
| `apps/vpn-client/android` | `mobile/android-client` | 1 | план |
| `apps/vpn-client/ios` | — (клиента iOS нет) | — | не создаётся: пустой модуль |
| `apps/vpn-shop/android`, `apps/vpn-shop/ios` | `mobile/android-user`, `mobile/ios-user` | 2 | план |
| `apps/lucy-admin/android`, `apps/lucy-admin/ios` | `mobile/android-admin`, `mobile/ios-admin` | 2 | план |
| `apps/lucy-admin/web` | `admin` | 3 | план |
| `apps/user-cabinet` | `cabinet` | 3 | план |
| `apps/telegram-mini-app` | `miniapp` | 3 | план |
| `apps/telegram-bot`, `apps/status-page` | модули бэкенда (`backend/app/bot*`, страница статуса) | 5 | вместе с бэкендом |
| `services/api` и остальные сервисы промпта | `backend` (один FastAPI с модулями: `auth*`, `payment*`, `subscription*`, `remnawave*`, `rw_*`, `autoselect*`, `masque*`, `notifications*`) | 5 | один сервис; модули перечисляются в карте, а не дробятся на пустые папки |
| `services/support` | `support-pro` | 5 | план |
| `packages/localization` | `mobile/l10n` | 2 | план |
| `packages/*` (shared-ui, shared-api, …) | — (общего кода между приложениями нет) | — | не создаются, пока нет общего кода |
| `infrastructure/deployment`, `infrastructure/reverse-proxy`, `infrastructure/monitoring` | `deploy` (установщик, Caddy, Prometheus/Grafana) | 4 | план; `deploy/install-vps.sh` остаётся переходником для старых команд установки |
| `infrastructure/provisioning` | `terraform` | 4 | план |
| `database/migrations` | `backend/alembic`, `support-pro/alembic` | 5 | вместе с сервисами |
| `scripts/…`, `tests/…`, `docs/…`, `.github/workflows` | уже на месте | — | без изменений |

Остальное (`browser-extension`, `desktop`, `corgi-cli`, `screenshots`) — в `apps/` на этапе 3, если это действующий код.

## Порядок и проверка каждого этапа

1. `git mv` папки (история файлов сохраняется).
2. Пути в CI (`.github/workflows`), скриптах, `docker-compose*.yml`, Dockerfile, генераторах документации.
3. Тесты, сборки Android/iOS, образы Docker — полностью зелёный CI, включая iOS.
4. Обновление установленного сервера: `tests/test_v2018_recovery.py` и сборка выпуска; старые пути, на которые
   ссылаются установленные серверы (`deploy/install-vps.sh`, `scripts/auto_update.py`), остаются или получают переходник.
5. Документация и `docs/PROJECT_FILE_MAP.md` перегенерированы.
