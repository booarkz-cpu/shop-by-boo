# CI/CD

Каждое изменение проходит через pull request. Он вливается в `main` только с зелёным CI. Выпуск публикуется сам, после успешного CI на `main` при смене версии.

## Что проверяется на каждом PR и push в `main` (`ci.yml`)

| Задание | Что проверяет |
| --- | --- |
| Backend • Python + tests + migrations (1/2, 2/2) | установка зависимостей, инварианты публикации выпуска, `alembic heads` (одна голова), `alembic upgrade head` на PostgreSQL 18, тесты на PostgreSQL и Redis. С v28.74.0 набор поделён на две половины (`scripts/ci/test-shard.py`, по размеру файлов), они идут на разных машинах |
| Lint • Python (ruff) and shell syntax | `ruff`, `bash -n` всех скриптов |
| Content, customer operations and passkeys • Chromium end-to-end | Playwright в настоящем Chromium: контент, операции с клиентами, WebAuthn |
| Support Pro • runtime tests | служба поддержки |
| Dependency vulnerability audit | `pip-audit` зависимостей Python, `bandit` (статический анализ безопасности кода), `npm audit` интерфейсов |
| admin / cabinet / miniapp • typecheck + build | `tsc` и сборка трёх интерфейсов |
| Docker Compose • configuration | `docker compose config` всех профилей |
| Containers • non-root startup and Redis authentication | контейнеры стартуют без root, Redis с паролем |
| Android / iOS | сборки PKCE, VPN-движок, UI-тесты, расширения туннеля и push |

## Отдельные процессы

| Workflow | Когда | Что делает |
| --- | --- | --- |
| `docs-links.yml` | каждую ночь, вручную | внешние ссылки документации (внутренние ссылки и якоря проверяет `scripts/check-doc-links.py` в задании Backend) |
| `docker.yml` | push в `main` и теги | образы backend, bot, admin, cabinet, miniapp |
| `publish-release.yml` | после зелёных CI и Docker на `main` | архивы, SHA-256, манифест, выпуск GitHub |
| `mobile-release.yml`, `build-mobile.yml` | выпуск | APK/IPA или честный `mobile-production-status.json` без подписи. С v28.75.0 ждёт перезапуска упавшего CI, а не падает сразу |
| `remnawave-live.yml` | PR с кодом Remnawave, push в `main`, раз в неделю | живая установка Remnawave из мастера, модули нод, Telegram Bot API |
| `load-security.yml` | PR с backend, push в `main`, раз в неделю | нагрузочная проверка и базовый OWASP ZAP |
| `resolve-image-digests.yml` | вручную или PR этого файла | digest новых образов Remnawave для закрепления |
| `deploy.yml` | вручную | развёртывание точного выпуска на свой сервер через проверенный updater |
| `payments-acceptance.yml`, `hetzner-live.yml`, `load-live.yml` | вручную или по расписанию, нужны секреты | живые кассы, настоящие VPS, нагрузка |

## Безопасность цепочки

- **Образы** закреплены по digest. Remnawave обновляется на серверах только до digest, проверенных живыми тестами выпуска ([автообновление](AUTO_UPDATE.md)).
- **Выпуск** проверяется по SHA-256 и манифесту; уже опубликованный выпуск не перезаписывается.
- **Секреты** — в GitHub Actions secrets, в журналы не попадают. Без секретов живые проверки получают статус `BLOCKED_SECRETS`, а не «успех».
- **Ветки** защищены набором правил «Rules»: без force push, удаление веток — только владельцем.

## Подготовка выпуска

1. Поднять версию в одном PR: `release-identity`, README, CHANGELOG, `docs/ru/RELEASE_V*.md`, статусы.
2. Перегенерировать каталоги: `scripts/generate-api-docs.py`, `generate-admin-matrix.py`, `generate-db-schema.py`, `generate-project-map.py`. CI проверяет их актуальность.
3. Влить PR с зелёным CI. Выпуск и вложения появятся сами примерно через 40–60 минут.

Общее описание для разработчиков — [CI_CD_RU.md](../../../CI_CD_RU.md).

## Встроенный VPN Android на эмуляторе (с v28.82.0)

`android-vpn-e2e.yml` проверяет, что VPN приложения работает, а не просто показывает статус.
- **Стенд.** На машине CI запускаются Xray-сервер (VLESS по TCP) и подписка с этим сервером на `http://10.0.2.2`. Сервер отправляет адрес `198.18.0.42:80` на страницу «corgi-tunnel-ok».
- **Почему это доказательство.** Этот адрес больше никто не обслуживает, поэтому страница отвечает только через туннель.
- **Шаги** (`scripts/mobile/vpn-e2e.sh`):
  1. без VPN страница не отвечает;
  2. приложение подключается движком Xray-core (`libv2ray.aar`) — страница отвечает;
  3. после отключения страница снова не отвечает.
- **Ограничения.** Подписку по http с `10.0.2.2` принимает только отладочная сборка. Разрешение VPN в CI выдаётся через `appops`. На настоящей ноде — BLOCKED_EXTERNAL.
