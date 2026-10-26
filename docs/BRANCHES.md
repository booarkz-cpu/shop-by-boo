# Ветки и очистка проекта

Проверено 26 октября 2026 для `main` на коммите `461ffc1c1210818272089ada555e53d5fffb965e` (v28.25.1): на GitHub 52 ветки кроме `main`: 51 к удалению и одна ветка открытого PR.

`main` содержит опубликованный код. Теги `v*` и `mobile-v*`, миграции, тесты, исторические CHANGELOG и документы в `docs/archive/` сохраняются.

## Как почистить ветки

```bash
bash scripts/cleanup-branches.sh           # показать план, ничего не меняя
bash scripts/cleanup-branches.sh --apply   # выполнить
```

Скрипт оставляет `main` и ветки открытых PR. Ветку, полностью вошедшую в `main` (`git merge-base --is-ancestor`), он удаляет. Любую другую ветку (влитую squash-мержем или заброшенную) сначала сохраняет тегом `archive/<ветка>` на её последнем коммите и только потом удаляет: ни один коммит не теряется, ветка восстанавливается командой `git checkout -b <ветка> archive/<ветка>`.

Нужны права push в репозиторий и вход в GitHub CLI (`gh auth login`). Активный ruleset `Rules` запрещает удаление веток всем, кроме ролей и приложений из списка обхода ([правила](https://github.com/booarkz-cpu/shop-by-boo/rules/23903620)): запускайте скрипт от учётной записи владельца. Из сессий Claude удаление и создание git-ссылок закрыто политикой среды, поэтому очистка выполняется этим скриптом у владельца.

## Состав на 26 октября

**18 веток полностью в `main`** — удаляются без тега:

- `cleanup/project-hygiene-20261003`
- `codex/v28-1-0-update-20261012`
- `fix/pending-grants-support-drafts-20261002`
- `release/alpha6-giveaways-20261003`
- `release/alpha7-passkeys-monitoring-20261003`
- `release/full-function-transfer-20261002`
- `release/v21.0.0-stable`
- `release/v21.0.1-referrals-backup`
- `release/v21.1.0-matrix-functions`
- `release/v21.2.0-customer-operations`
- `release/v21.3.0-content-offers`
- `release/v21.4.0-menu-hierarchy`
- `release/v21.5.0-support-history`
- `rework/unified-workspace-20261001`
- `transfer/account-readiness-20261002`
- `transfer/remaining-features-20261002`
- `transfer/support-bridge-20261002`
- `transfer/surveys-20261003`

**33 веток с коммитами вне `main`** — содержимое влито squash-мержем или PR закрыт как устаревший; сохраняются тегом `archive/…` и удаляются:

- `audit/payment-contracts-vds-20260928` — #35 закрыт влит
- `audit/v20.0.11-payments` — #24 закрыт влит
- `audit/v20.0.12-deep-security` — #25 закрыт влит
- `audit/v20.0.13-staging-e2e-guide` — #26 закрыт влит
- `audit/v20.0.14-security` — #28 закрыт влит
- `audit/v20.0.8` — #18 закрыт влит
- `audit/v20.0.9` — #22 закрыт влит
- `audit/v21.1.0-published-assets` — без PR
- `cleanup/obsolete-publish-artifacts` — #21 закрыт влит
- `dependabot/github_actions/actions/upload-artifact-7` — #41 закрыт не влит
- `dependabot/pip/support-pro/aiofiles-25.1.0` — #111 закрыт не влит
- `docs/real-payments-readme-guide` — #27 закрыт влит
- `docs/staging-vds-e2e-operator-v20-0-18` — #34 закрыт влит
- `docs/ui-screenshots` — #83 закрыт влит
- `feat/customer-import-operations` — #60 закрыт не влит
- `feat/email-support-channel` — #80 закрыт влит
- `feat/native-push` — #78 закрыт влит
- `feat/network-intel` — #82 закрыт влит
- `feat/nextjs-remna-redesign` — #77 закрыт влит
- `feat/plugin-runtime` — #81 закрыт влит
- `feat/runtime-settings-v28.3.0` — #67 закрыт влит
- `feat/widget-multiprofile` — #79 закрыт влит
- `fix/docker-buildx-v20.0.8` — #19 закрыт не влит
- `fix/docker-buildx-v20.0.8-ready` — #20 закрыт влит
- `fix/mobile-release-distribution-tag-v28.3.0` — #68 закрыт влит
- `fix/provider-metric-counters` — #84 закрыт влит
- `fix/release-maintenance-publish-v28.3.0` — #69 закрыт влит
- `fix/sandbox-payment-v20.0.10` — #23 закрыт влит
- `fix/v20-0-18-recovery-audit` — #33 закрыт влит
- `fix/v20.0.16-release-assets` — #32 закрыт влит
- `fix/v20.0.16-vds-production` — #31 закрыт влит
- `release/mobile-2.14.1` — #29 закрыт влит
- `release/security-20.0.15` — #30 закрыт влит

**Остаются:** `main` и ветки открытых PR (сейчас — обновление зависимостей от Dependabot).

## Локальные файлы

Удалены кэши Python/pytest, результаты браузерных проверок, `admin/dist`, `cabinet/dist`, `miniapp/dist` и пустое рабочее дерево подготовки CMS. Зависимости `node_modules` оставлены для последующей разработки, но не входят в Git и релиз. `.gitignore` также исключает ссылки `node_modules`, отчёты браузера/покрытия, временные файлы редактора и результаты сборки iOS.

Перед очисткой смотрите `git status --short` и `git clean -ndX`. Не запускайте безусловный `git clean -fdX`: он может удалить локальный `.env`, ключи, базы и резервные копии. Удаляйте только явно перечисленные кэши и сборочные каталоги. Для новой задачи создавайте короткоживущую ветку от актуального `main`, публикуйте PR, проверяйте CI и после объединения повторно проверяйте ветку перед удалением.
