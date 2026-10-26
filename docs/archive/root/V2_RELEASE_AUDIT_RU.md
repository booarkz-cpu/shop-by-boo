# VPN Shop by Corgi v2 — итоговый аудит

Дата: 2026-09-23

## Исправлено

- Исправлен повреждённый JSX в `cabinet/src/main.tsx` в списке платёжных провайдеров.
- Исправлен типовой дефект `platformKeys` в кабинете.
- Добавлены Vite `ImportMetaEnv` declarations для всех frontend-приложений.
- Добавлен единый `tsconfig.json` и `typecheck` script для admin/cabinet/miniapp.
- Админский dashboard переработан в operational control center: KPI, состояние зависимостей, быстрые действия, выручка и security summary.
- Добавлен отдельный design-system слой для admin.
- Кабинет получил более плотную Material/Web3 систему карточек, форм, мобильной навигации и состояний.
- Mini App приведён к тому же визуальному языку.
- Все основные fallback-бренды приведены к `VPN Shop by Corgi`.
- Backend в production теперь отказывается стартовать с shipped `change-me` секретами для APP_SECRET/ADMIN_PASSWORD/DB_PASSWORD.
- Добавлена архитектурная документация v2.
- Добавлен автоматический source-level regression audit `scripts/static_audit.py`.

## Проверки

Успешно:

```text
python -m compileall -q backend/app
python scripts/static_audit.py
TypeScript parser/noCheck: admin PASS
TypeScript parser/noCheck: cabinet PASS
TypeScript parser/noCheck: miniapp PASS
```

Полный `npm ci` в изолированной среде не завершился из-за внешнего network/transport timeout. Поэтому полноценный Vite production bundle здесь не был подтверждён через установленный `node_modules`.

Python pytest suite также требует runtime dependencies PostgreSQL/Redis/`asyncpg`; в текущей изолированной среде collection останавливается на отсутствии `asyncpg`. Это ограничение среды, а не скрытая ошибка исходников.

## Production перед запуском

1. Установить зависимости в каждом frontend: `npm ci`.
2. Выполнить `npm run typecheck` и `npm run build`.
3. Запустить backend pytest suite в окружении с PostgreSQL/Redis/asyncpg.
4. Выполнить staging E2E.
5. Только после успешного staging E2E открыть production payment gate.
6. Задать уникальные секреты и домены в `.env`.
7. Включить MFA для всех admin accounts.
