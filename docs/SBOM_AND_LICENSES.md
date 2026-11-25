# Состав (SBOM) и лицензии (REQ-DOC-0036)

Что входит в магазин и под какими лицензиями — и где это проверяется автоматически. Всё ниже сверено с
`.github/workflows/ci.yml` и `scripts/ci/check-licenses.py`.

## Лицензия проекта

Авторский код — по собственной лицензии из [LICENSE](../LICENSE). Лицензии зависимостей она не заменяет: состав и
обязательные уведомления — в [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). Чужой код из проектов под AGPL,
Commons Clause или без лицензии не копируется — только идеи (решение владельца № 13, `docs/OWNER_DECISIONS.md`;
источники — [REFERENCE_REPOSITORIES.md](REFERENCE_REPOSITORIES.md)).

## Что проверяется в каждом PR

| Проверка | Где | Что блокирует слияние |
|---|---|---|
| SBOM | Trivy в `ci.yml` строит список компонентов CycloneDX. `scripts/ci/check-sbom.py` проверяет его по строгой JSON-схеме версии 1.6 или 1.7 | ошибка схемы или 100 и менее компонентов. CI сохраняет проверенный `sbom.cdx.json` в артефакте `sbom` |
| Секреты и уязвимости репозитория | тот же шаг, Trivy `fs --scanners vuln,secret` | секрет в репозитории или уязвимость HIGH/CRITICAL в lock-файле |
| Уязвимости образов | `ci.yml`, «Container scan»: Trivy по каждому образу, который собирает магазин | HIGH/CRITICAL с готовым исправлением; исключения — `.trivyignore`, каждое с причиной и сроком |
| Лицензии зависимостей | `ci.yml`, «Dependency licences»: `pip-licenses` для backend, `license-checker` для admin, miniapp, cabinet → `scripts/ci/check-licenses.py` | сильный копилефт или source-available среди поставляемых зависимостей; слабый копилефт (LGPL, MPL) для библиотеки «как есть» допустим; исключение — строка в `ALLOWED` с причиной |
| Аудит npm | `ci.yml`, «JavaScript dependencies»: `npm audit --audit-level=high` для admin, miniapp, cabinet | уязвимость high и выше |

## Где взять SBOM конкретной версии

Для опубликованного `v28.161.0` доступен артефакт `sbom` в соответствующем прогоне «Corgi Lusi CI».
Для следующего выпуска `publish-release.yml` берёт проверенный файл из CI текущего коммита `main`.
Рядом с ZIP дистрибутива публикуется файл с тем же базовым именем и расширением `.cdx.json`.
Его имя, размер в байтах и SHA-256 записаны в поле `sbom` отдельного манифеста выпуска.
Скачанный файл можно сверить командой `sha256sum <имя-файла>.cdx.json` и сопоставить с `sbom.sha256`.
Порядок публикации описан в [RELEASE_PROCESS.md](RELEASE_PROCESS.md).

## Чего пока нет

- Зависимостей Android-приложений в SBOM нет: у Gradle-проектов нет `gradle.lockfile`, а Trivy `fs` читает только
  lock-файлы (в репозитории это `package-lock.json` и `requirements*.txt`). Их версии обновляет Dependabot (`gradle`).
