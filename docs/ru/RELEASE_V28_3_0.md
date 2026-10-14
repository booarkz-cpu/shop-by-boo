# Выпуск v28.3.0 — безопасные настройки без перезапуска

Дата: 2026-10-14. Дистрибутив: `v28.3.0`. Runtime/API: `21.5.1`. Head магазина: `0064_runtime_settings`. Support Pro: `0006` / 3.6.

## Что завершено

- Полный типизированный реестр всех 144 полей приложения: 96 live-параметров, 46 deployment-параметров и 2 значения специализированных workflow.
- Двухфазное изменение `stage → apply`, optimistic version lock, HMAC fingerprint и защита от публикации устаревшего набора.
- AES-GCM для секретов и staged payload, маскирование в API/UI и audit без чувствительных значений.
- Telegram-бот запрашивает из `AppSetting` только публичные поля оформления и не загружает runtime overrides с секретами.
- Атомарное применение, межпроцессная сходимость API/worker/bot не позднее 5 секунд и безопасный откат только последней версии.
- Отдельный worker читает подтверждённые настройки до запуска заданий и продолжает отслеживать версии. Изменившийся `.env` блокирует устаревший apply/rollback; финальная проверка выполняется до записи.
- RBAC `settings.runtime.read` / `settings.runtime.write`, история ревизий, причина каждого действия и PostgreSQL race-тест.
- Новый адаптивный экран Obsidian/Amber: поиск, группы, Lucide-иконки, Radix/shadcn select, состояния источника, preview, loading-индикаторы и контекстная подсказка у каждого поля.
- Явный список параметров, которым нужен deployment или отдельная транзакционная процедура; интерфейс не выдаёт их за hot-reload.
- Миграция `0064_runtime_settings`, документация оператора, API-каталог, карта проекта, manifest и upgrade-инструкции.

## Обновление

Перед обновлением создайте согласованный backup базы и файлов. Затем используйте [проверяемый регламент обновления](DISTRIBUTION_UPGRADE_CURRENT.md) и примените миграции. После запуска проверьте:

```bash
docker compose exec -T backend alembic current
docker compose ps
curl -fsS https://API_DOMAIN/health/live
curl -fsS https://API_DOMAIN/health/ready
```

Ожидаемый head — `0064_runtime_settings`. Пошаговая эксплуатация нового раздела: [Настройки без перезапуска](RUNTIME_SETTINGS_CURRENT.md).

## Границы выпуска

CI, unit/integration tests и Docker-сборка подтверждают код на точном commit релиза. Они не подтверждают реальные платежи, доставку SMTP/Telegram, доступ к конкретному Remnawave или restore drill инфраструктуры владельца. Production gate остаётся закрытым до внешней приёмки. APK/IPA не считаются подписанными без owner signing secrets. Полный статус: [матрица покрытия](WORKSPACE_COVERAGE.md).
