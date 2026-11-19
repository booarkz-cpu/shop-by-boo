# Совместимость Remnawave

Актуально на 19 ноября 2026 года. Матрица фиксирует только официальные стабильные версии, реально используемые проектом. Плавающие `main` и `latest` не являются доказательством совместимости.

| Компонент | Версия и тег | Точный upstream commit | Образ и multi-platform index digest | Лицензия | Проверка проекта |
| --- | --- | --- | --- | --- | --- |
| Backend / panel | `3.4.11`, tag `3.4.11` | `6853666801d6d1925b6aec55824106100485777a` | `remnawave/backend:3.4.11@sha256:a5b9f81fe2cfacec1c41bd2bb43fa1a5980228b81aa2e744be4adffa3a00135b` | AGPL-3.0-only | Живой API-контракт, пользователи, HWID, ноды, профили, subscription proxy, расширения |
| Node | `3.4.6`, tag `3.4.6` | `52d0f1c00c23bf99912687cb3b75faffb2d3bffb` | `remnawave/node:3.4.6@sha256:3d5fde656a36920f53c5c080f2dc821df8318f453803b07c4e5242752a549d69` | AGPL-3.0-only | Нода запускается с host network, получает ключ панели и участвует в live-contract |
| Subscription page | `8.0.1`, tag `8.0.1` | `9045728e6e197a2581c6da40f4f92b170a8bad53` | `remnawave/subscription-page:8.0.1@sha256:ba8445b1e0d1c170cf314686ef638b73cabf42a0c6217d027e6cb958ca161ca6` | AGPL-3.0-only | Страница запускается рядом с панелью и отвечает через настоящий HTTP-контракт |
| Backend contract | `3.4.17` | файл `libs/contract/package.json` в commit backend `68536668…` | npm-контракт не встраивается в Python runtime | AGPL-3.0-only в составе backend | Все используемые магазином методы и тела проверяются `tests/live/test_remnawave_live.py` |
| Node contract | `3.4.5` | зависимость backend `3.4.11` | npm-зависимость upstream backend | AGPL-3.0-only в составе backend | Совместимость панели 3.4.11 и node 3.4.6 проверяется их реальным соединением |

## API, ABI и миграции

Интеграция магазина использует HTTP/JSON API панели, Docker Compose и переменные окружения; нативного ABI между магазином и Remnawave нет. Backend 3.4.11 обновляет зависимости и содержит исправление защиты до аутентификации от DoS. Ломающего изменения используемых маршрутов в живом контракте не обнаружено.

Prisma-миграции Remnawave выполняет официальный backend-контейнер. SQL-схема магазина этим обновлением не меняется. Перед обновлением реальной панели обязательны согласованная резервная копия и проверка восстановления; этот PR не выдаёт CI-контейнер за настоящий VPS.

## Единый источник версий

- эксплуатационные образы: `services/backend/app/rw_plan.py`;
- node-only provisioning: `services/backend/app/provisioner.py` и `node_autoscale.py`;
- живой контракт: `scripts/ci/remnawave-live.sh`;
- защита от рассинхронизации: `tests/test_remnawave_version_pins.py`.

Live-contract запускает именно указанные tag + digest и завершает job ошибкой, если label контейнера не совпал с ожидаемой версией. Новая upstream-версия сначала получает отдельный PR, API-diff и полный CI; автоматическая подмена `latest` запрещена.

## Границы доказательства

CI подтверждает запуск контейнеров, API, provisioning-конфигурацию и контракт подписки в среде GitHub Actions. Он не подтверждает физическое Android/iOS-устройство, настоящий VPS, публичный DNS/TLS, производственные webhook, merchant/OAuth/Apple-ключи или реальные платежи. Эти пункты остаются внешними ограничениями O1–O14.
