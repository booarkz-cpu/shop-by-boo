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
| SBOM | `ci.yml`, шаг «Secret and vulnerability scan of the repository, SBOM»: Trivy (закреплён по digest) строит список компонентов CycloneDX | меньше 100 компонентов — значит, сканирование сломано; файл `sbom.cdx.json` сохраняется артефактом `sbom` прогона CI |
| Секреты и уязвимости репозитория | тот же шаг, Trivy `fs --scanners vuln,secret` | секрет в репозитории или уязвимость HIGH/CRITICAL в lock-файле |
| Уязвимости образов | `ci.yml`, «Container scan»: Trivy по каждому образу, который собирает магазин | HIGH/CRITICAL с готовым исправлением; исключения — `.trivyignore`, каждое с причиной и сроком |
| Лицензии зависимостей | `ci.yml`, «Dependency licences»: `pip-licenses` для backend, `license-checker` для admin, miniapp, cabinet → `scripts/ci/check-licenses.py` | сильный копилефт или source-available среди поставляемых зависимостей; слабый копилефт (LGPL, MPL) для библиотеки «как есть» допустим; исключение — строка в `ALLOWED` с причиной |
| Аудит npm | `ci.yml`, «JavaScript dependencies»: `npm audit --audit-level=high` для admin, miniapp, cabinet | уязвимость high и выше |

## Где взять SBOM конкретной версии

Артефакт `sbom` прогона «Corgi Lusi CI» на коммите выпуска (вкладка Actions → прогон → Artifacts). Выпуск, кроме
того, несёт аттестацию происхождения дистрибутива (`publish-release.yml`, см. [RELEASE_PROCESS.md](RELEASE_PROCESS.md)).

## Чего пока нет

- Зависимостей Android-приложений в SBOM нет: у Gradle-проектов нет `gradle.lockfile`, а Trivy `fs` читает только
  lock-файлы (в репозитории это `package-lock.json` и `requirements*.txt`). Их версии обновляет Dependabot (`gradle`).
- SBOM не прикрепляется к выпуску файлом — только артефактом CI (хранится по сроку артефактов GitHub).
