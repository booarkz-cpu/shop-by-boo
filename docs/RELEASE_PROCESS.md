# Процесс выпуска (REQ-DOC-0030)

Как изменение попадает в выпуск `vX.Y.Z` с 33 файлами. Каждый шаг сверен с файлами в `.github/workflows/` и
`scripts/`; чек-лист ручной проверки — [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md), что не проверено —
[RELEASE_LIMITATIONS.md](RELEASE_LIMITATIONS.md).

## 1. Подготовка изменения

1. Ветка от `origin/main`. История `main` не переписывается, force push и обход защиты ветки запрещены.
2. Версия дистрибутива поднимается во всех местах сразу (README, `release-manifest.template.json`, CHANGELOG,
   `docs/ru/RELEASE_VX_Y_Z.md`, `scripts/check-current-docs.py`); версия runtime/API (`/health`) — отдельное число.
3. Перед PR локально: `scripts/check-current-docs.py`, `scripts/check-doc-links.py`,
   `scripts/check-runtime-placeholders.py`, `scripts/generate-project-map.py --check`,
   `scripts/audit/requirements_register.py --check`.

## 2. Pull request

- `ci.yml` («Corgi Lusi CI») запускается на каждый PR; итог — задание `CI gate`, в `needs` которого перечислены все
  задания (новое задание обязательно добавляется туда).
- Сливается только при полностью зелёном CI, включая iOS; способ — squash, с трейлерами автора.
- Пока предыдущий выпуск не опубликован со всеми файлами, следующий PR в `main` не сливается: «Mobile packages»
  прикрепляет файлы, только если `main` не ушёл вперёд (иначе — «Main moved», файлы остаются только артефактами).

## 3. Что происходит после слияния

| Шаг | Workflow | Запуск |
|---|---|---|
| Проверки `main` | `ci.yml`, `docker.yml` | push в `main` |
| Выпуск и дистрибутив | `publish-release.yml` («Publish GitHub release»): проверяет успешные CI и Docker на текущем `main`, собирает дистрибутив (`scripts/package-distribution.py`), публикует тег, ставит аттестацию происхождения | после завершения CI и Docker |
| Приложения к выпуску | `build-mobile.yml` | после «Publish GitHub release»; вручную — вход `tag=vX.Y.Z` |
| Подписанные пакеты, клиент | `mobile-release.yml` («Mobile packages»): APK/AAB, iOS, контрольные суммы; отдельный выпуск `client-v<версия>` клиента | push в `main`, ждёт CI |
| Развёртывание | `deploy.yml` | после «Publish GitHub release» или вручную с точным тегом |

Готовый выпуск — 33 файла. Проверка: `gh api repos/<owner>/<repo>/releases/tags/vX.Y.Z --jq '.assets|length'`.

## 4. Если что-то упало

- Сбой сборки приложений из-за GitHub — перезапустить `build-mobile.yml` с `tag=vX.Y.Z`.
- Нестабильное задание CI на `main` — перезапуск упавших заданий; «Mobile packages» ждёт перезапуска.
- Установленные серверы берут выпуск сами (ночное автообновление, [AUTO_UPDATE.md](AUTO_UPDATE.md)) и не ставят
  выпуск, у которого `min_upgrade_from` выше их версии (`scripts/github_release_fetch.py`).
