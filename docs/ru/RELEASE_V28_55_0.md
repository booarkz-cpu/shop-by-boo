# Выпуск v28.55.0 — версия в разделе «Обновления» и документация аудита

Дистрибутив: `v28.55.0`. Runtime/API: `21.5.1`. Head магазина: `0088_filter_and_regions`.
Support Pro: `0008` / 3.8. Мобильные приложения: 3.4.0.

Выпуск не меняет схему базы данных и не требует миграций. Обновление совместимо с `v28.54.0`
в обе стороны.

## Что изменено

**Раздел «Обновления» показывает фактическую версию.** Раньше вместо номера установленной версии
выводился захардкоженный текст-заглушка. Администратор не мог узнать по интерфейсу, какая версия
работает. Теперь версия берётся из ответа `/api/admin/github-update` (`current_tag`), при отсутствии
ответа — прочерк.

Файл: `admin/src/main.tsx`.

**Документация автообновления.** Механизм ночного обновления существовал и раньше, но не был описан
для оператора. Добавлены:

- [AUTO_UPDATE.md](AUTO_UPDATE.md) — архитектура: источник только стабильные GitHub Releases,
  systemd-расписание, обмен между панелью и агентом через два JSON-файла;
- [AUTO_UPDATE_SECURITY.md](AUTO_UPDATE_SECURITY.md) — модель угроз, разделение полномочий
  непривилегированной панели и root-агента, перечень того, чего механизм **не** делает;
- [AUTO_UPDATE_TROUBLESHOOTING.md](AUTO_UPDATE_TROUBLESHOOTING.md) — симптом, причина, команда;
- [AUTO_UPDATE_TESTING.md](AUTO_UPDATE_TESTING.md) — 19 сценариев с фактическими статусами.

**Документация тестирования и релиза.**

- [TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md](TESTING_GUIDE_EXTERNAL_DEPENDENCIES.md) — пошаговое
  тестирование Remnawave, reverse proxy, Telegram, Mini App, 15 платёжных провайдеров, OAuth,
  GitHub Actions, Docker, установщика, обновления, Android/iOS;
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md), [RELEASE_LIMITATIONS.md](RELEASE_LIMITATIONS.md),
  [EXTERNAL_DEPENDENCIES.md](EXTERNAL_DEPENDENCIES.md);
- [CLAUDE_GITHUB_AUTOMATION.md](CLAUDE_GITHUB_AUTOMATION.md), [AUTOMATION_LOG.md](AUTOMATION_LOG.md);
- [MASTER_ROADMAP_VPN_SHOP.md](MASTER_ROADMAP_VPN_SHOP.md),
  [ROADMAP_UI_AND_SCREENSHOTS.md](ROADMAP_UI_AND_SCREENSHOTS.md).

**Ночная проверка контрактов.** Добавлен `.github/workflows/claude-roadmap.yml`: ежедневно в 02:20 UTC
проверяет контракт документации, отсутствие заглушек в production-коде, актуальность карты файлов,
lint и единственность head миграций. Права `contents: read`, без вызова внешних LLM API, без
коммитов — workflow не может изменить репозиторий, даже если шаг поведёт себя неверно.

## Что проверено

| Проверка | Результат |
| --- | --- |
| `ruff check backend scripts tests` | PASS |
| `bash -n` по всем `*.sh` | PASS |
| `compileall app worker.py` | PASS |
| Backend-тесты, полный набор | PASS — 2507 собрано, 0 падений |
| Typecheck admin (оба tsconfig) | PASS |
| Build admin | PASS |
| Typecheck, vitest и build cabinet | PASS |
| `check-current-docs.py`, `check-runtime-placeholders.py`, `generate-project-map.py --check` | PASS |
| `alembic heads` | PASS — один head |
| GitHub Actions на PR (18 проверок) | PASS |

## Что не проверено

Честный перечень, без округлений:

- живые Remnawave, платёжные провайдеры, Telegram, Mini App, OAuth, push — нет ключей
  (`BLOCKED_SECRETS`);
- Docker-сборка и запуск 17 сервисов, установщик на чистом VPS — нет Docker и сервера
  (`BLOCKED_ACCESS`);
- ночное автообновление по расписанию и откат при реальном сбое — нужен VPS с systemd
  (`BLOCKED_ACCESS`);
- сборка и подпись мобильных приложений — нет Android SDK, Xcode и ключей.

Подробно: [RELEASE_LIMITATIONS.md](RELEASE_LIMITATIONS.md).

## Обновление

```bash
sudo bash /opt/vpn-shop/scripts/auto-update.sh run
```

Либо дождитесь ночного запуска. Миграций нет, откат при необходимости —
`sudo bash /opt/vpn-shop/scripts/rollback.sh`.
