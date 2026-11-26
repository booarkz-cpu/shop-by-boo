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
| SBOM | отдельное задание `sbom` в `ci.yml`: Trivy строит граф репозитория, а официальный CycloneDX Gradle Plugin 3.6.1 — разрешённые прямые и транзитивные графы трёх Android-приложений | меньше 100 компонентов, меньше 30 Maven-компонентов, отсутствие лицензий Android, неполный граф или неверный SHA-256 блокируют слияние; `sbom.cdx.json` и `sbom.cdx.json.sha256` сохраняются одним артефактом `sbom` |
| Секреты и уязвимости репозитория | тот же шаг, Trivy `fs --scanners vuln,secret` | секрет в репозитории или уязвимость HIGH/CRITICAL в lock-файле |
| Уязвимости образов | `ci.yml`, «Container scan»: Trivy по каждому образу, который собирает магазин | HIGH/CRITICAL с готовым исправлением; исключения — `.trivyignore`, каждое с причиной и сроком |
| Лицензии зависимостей | `ci.yml`, «Dependency licences»: `pip-licenses` для backend, `license-checker` для admin, miniapp, cabinet → `scripts/ci/check-licenses.py` | сильный копилефт или source-available среди поставляемых зависимостей; слабый копилефт (LGPL, MPL) для библиотеки «как есть» допустим; исключение — строка в `ALLOWED` с причиной |
| Аудит npm | `ci.yml`, «JavaScript dependencies»: `npm audit --audit-level=high` для admin, miniapp, cabinet | уязвимость high и выше |

## Где взять SBOM конкретной версии

Артефакт `sbom` прогона «Corgi Lusi CI» на коммите выпуска (вкладка Actions → прогон → Artifacts). Release workflow
скачивает именно этот артефакт по ID проверенного CI, повторно сверяет SHA-256 и публикует рядом с архивом два
неизменяемых файла:

- `remnawave_vpn_shop_vX_Y_Z_sbom.cdx.json`;
- `remnawave_vpn_shop_vX_Y_Z_sbom.cdx.json.sha256`.

Publisher проверяет JSON как CycloneDX, контрольную сумму, размер и digest ответа GitHub до публикации release.
Выпуск также несёт отдельную аттестацию происхождения дистрибутива (`publish-release.yml`, см.
[RELEASE_PROCESS.md](RELEASE_PROCESS.md)).

## Граница состава Android

`scripts/ci/cyclonedx.init.gradle.kts` применяет Apache-2.0 CycloneDX Gradle Plugin 3.6.1 только в CI и не добавляет
его в runtime приложения. Gradle 9.9.2 разрешает фактические графы `apps/vpn-shop/android`,
`apps/vpn-client/android` и `apps/lucy-admin/android`. Плагин учитывает выбранные Gradle версии после constraints,
substitution и разрешения конфликтов; в итог входят прямые и транзитивные Maven-компоненты, отношения и известные
лицензии из POM. `scripts/ci/merge-cyclonedx.py` объединяет их с результатом Trivy, дедуплицирует по PURL и создаёт
детерминированные `bom-ref`, dependency graph, timestamp коммита и SHA-256.

## Ограничения доказательства

REQ-DOC-0036 остаётся `PARTIAL`, пока новый workflow не пройдёт на exact HEAD и затем реальный следующий выпуск не
опубликует и не подтвердит оба SBOM-файла. CI-кандидат и документация сами по себе не заменяют это выпускное
доказательство и не дают PASS. Native-компоненты Xray/libXray/hev фиксируются в `THIRD_PARTY_NOTICES.md` и файлах
provenance мобильных сборок; они не выдаются за Maven-компоненты.
