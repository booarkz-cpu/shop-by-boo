# Релиз v28.149.0 — клиент в apps/vpn-client/android (этап 1 новой структуры папок)

Дистрибутив: `v28.149.0`. Runtime/API: `21.5.1`. Head магазина: `0094_store_subscriptions` (без новых миграций). Support Pro: `0008` / 3.8.

Дата: 2026-11-14. Решение владельца № 14 (`docs/OWNER_DECISIONS.md`): переложить папки по структуре мастер-промпта,
по этапам (`docs/MONOREPO_LAYOUT.md`).

## Что перенесено

- «Корги Люси: клиент» (Android) — из `mobile/android-client` в `apps/vpn-client/android` через `git mv`: история
  каждого файла сохраняется (`git log --follow`).
- Обновлены пути в CI (`android-client.yml`, `mobile-release.yml`, `mobile-screenshots.yml`, `xray-core-watch.yml`),
  `dependabot.yml`, `.gitignore`, скриптах сборки, проверки стиля, баннеров и значков, в тестах и документации.

## Что не изменилось

- Имена файлов выпуска (`corgi-lusi-client.apk`, отдельный выпуск `client-v<версия>`) и подпись — установленные
  клиенты обновляются сами, как прежде.
- Сервер магазина клиент не собирает, поэтому обновление установленных серверов этот перенос не затрагивает.

## Чем проверено

Полный CI с iOS: сборка и UI-тесты клиента (`android-client.yml`), `tests/test_store_assets.py` (значки всех трёх
приложений по новому пути), `tests/test_client_banners.py`, карта файлов проекта.
