# Структура монорепозитория: план перекладки

Решение владельца от 2026-11-14 ([OWNER_DECISIONS.md](OWNER_DECISIONS.md), № 14): переложить папки по структуре
мастер-промпта (REQ-MIG-0013 … 0017). Условия самого промпта (REQ-MIG-0018): не создавать пустых модулей и не терять
самостоятельность сборок. Поэтому перекладка идёт этапами — каждый этап отдельным выпуском с полностью зелёным CI —
и только для того, что действительно есть. Работающие серверы обновляются сами (`scripts/update.sh` копирует новое
дерево целиком), поэтому каждый этап проверяет и автообновление.

## Куда что переезжает

| Структура промпта | Сейчас | Этап | Состояние |
|---|---|---|---|
| `apps/vpn-client/android` | бывш. `mobile/android-client` | 1 | **перенесено в v28.149.0** |
| `apps/vpn-client/ios` | — (клиента iOS нет) | — | не создаётся: пустой модуль |
| `apps/vpn-shop/android`, `apps/vpn-shop/ios` | бывш. `mobile/android-user`; `mobile/ios-user` | 2а / 2б | Android перенесён в v28.151.0; iOS — следующим выпуском |
| `apps/lucy-admin/android`, `apps/lucy-admin/ios` | бывш. `mobile/android-admin`; `mobile/ios-admin` | 2а / 2б | Android перенесён в v28.151.0; iOS — следующим выпуском |
| `apps/lucy-admin/web` | бывш. `admin` | 3 | **перенесено в v28.153.0** |
| `apps/user-cabinet` | бывш. `cabinet` | 3 | **перенесено в v28.153.0** |
| `apps/telegram-mini-app` | бывш. `miniapp` | 3 | **перенесено в v28.153.0** |
| `apps/telegram-bot`, `apps/status-page` | модули бэкенда (`backend/app/bot*`, страница статуса) | 5 | вместе с бэкендом |
| `services/api` и остальные сервисы промпта | `backend` (один FastAPI с модулями: `auth*`, `payment*`, `subscription*`, `remnawave*`, `rw_*`, `autoselect*`, `masque*`, `notifications*`) | 5 | один сервис; модули перечисляются в карте, а не дробятся на пустые папки |
| `services/support` | `support-pro` | 5 | план |
| `packages/localization` | бывш. `mobile/l10n` | 2а | **перенесено в v28.151.0** |
| `packages/*` (shared-ui, shared-api, …) | — (общего кода между приложениями нет) | — | не создаются, пока нет общего кода |
| `infrastructure/deployment` (установщик, сборка, WireGuard, сертификат почты), `infrastructure/reverse-proxy` (Caddy, nginx), `infrastructure/monitoring` (Prometheus, Grafana) | бывш. `deploy` | 4 | **перенесено в v28.154.0**; в `deploy/` остались пять переходников (`install-vps.sh`, `install-docker.sh`, `install-status.sh`, `resume-vps-after-pin.sh`, `build-production.sh`) |
| `infrastructure/provisioning` | бывш. `terraform` | 4 | **перенесено в v28.154.0** |
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

## Этап 4 (v28.154.0): что проверено

* **Старые пути.** `deploy/*.sh` вызывают перенесённые скрипты с теми же аргументами и тем же кодом возврата
  (`tests/test_layout_stage4.py`). Обновление установленного сервера идёт так: старый `scripts/update.sh` копирует новое
  дерево поверх и запускает `deploy/build-production.sh` — теперь это переходник.
* **Сертификат почты.** Файлы, которые оператор положил в `deploy/mail-tls`, при первом обновлении копируются в
  `infrastructure/deployment/mail-tls` (права сохраняются, продлённый в новой папке сертификат не затирается).
* **Откат.** `scripts/rollback.sh` запускает сборку из восстановленного снимка, даже если снимок со старой раскладкой.
* **Docker Compose.** Всё, что монтируется или собирается из `./infrastructure/…`, существует; ссылок на `./deploy/…` нет.
* **История Git (REQ-INFRA-0019).** Перенос сделан `git mv`: `git log --follow` показывает прежние коммиты файла
  (у `infrastructure/deployment/install-vps.sh` — 45 коммитов до переноса).
* **Старые проекты (REQ-INFRA-0022).** Ничего не удалено: исходные репозитории, ветки и выпуски не тронуты
  (решения № 12 и 16 в [OWNER_DECISIONS.md](OWNER_DECISIONS.md)); на сервере старая папка `deploy/` остаётся на месте.
* **Не проверено:** обновление настоящего сервера со старой раскладки — VPS пока нет (решение № 11).

Следующий — этап 5 (`services/` ← `backend`, `support-pro`), последним.
