# Shop by Boo — проектная спецификация

> Актуальный дистрибутив: `v28.13.0`; runtime/API: `21.5.1`; migration head: `0069_mail_domain`.

## Назначение

Платформа управляет VPN-подписками: каталогом тарифов, оплатами, entitlement-операциями, выдачей доступа через Remnawave, Telegram-ботом, Mini App, кабинетом пользователя и административным контролем.

Реестр конфигурации полностью классифицирует 144 поля: 96 параметров применяются live, 46 требуют deployment/restart, 2 принадлежат специализированным транзакционным workflow.

## Контракты готовности

| Область | Реализация | Приёмка |
| --- | --- | --- |
| Remnawave | `backend/app/remnawave.py`, `provisioner.py` | retry-safe provisioning, ownership check, health evidence |
| Ноды | monitoring/provisioning API и worker | degraded/offline state, audit event, alert route |
| Платежи | YooKassa, Platega, RollyPay, sandbox | signature verification, idempotent webhook, ledger entry |
| Подписки | `subscription_commerce.py`, `subscriptions.py` | quote → payment → entitlement → retry |
| Объединение аккаунтов | `account_merge.py`, миграция `0063_account_merge` | две авторизации, conflict preview, atomic transfer, reconciliation, retry journal |
| Runtime settings | `runtime_settings.py`, миграция `0064_runtime_settings` | typed registry, encrypted secrets, stage/apply, optimistic lock, audit, rollback, process convergence |
| Роли | permission dependencies и audit log | deny-by-default, protected mutation, traceable actor |
| Telegram alerts | worker/notification contracts | deduplicated alert, recovery notification, cooldown |
| Web UI | `admin`, `cabinet`, `miniapp` | typecheck/build, responsive states, keyboard focus |

## Нефункциональные требования

- Денежные операции идемпотентны и отражаются в неизменяемом ledger.
- Удалённые вызовы Remnawave выполняются после проверки владельца и с повторяемым operation key.
- Секреты не передаются через URL и не попадают в логи.
- Любая административная мутация создаёт audit evidence.
- Production-ready не заявляется без provider E2E, внешнего Remnawave stand и owner-signed mobile assets.

## Проверка релиза

```bash
python -m compileall -q backend/app
python scripts/check-current-docs.py
(cd admin && npm ci && npm run typecheck && npm run build)
(cd cabinet && npm ci && npm run typecheck && npm run build)
(cd miniapp && npm ci && npm run typecheck && npm run build)
bash scripts/test-up.sh
```


## Контракт дистрибутива v28.13.0

Runtime/API сохраняет `21.5.1`; магазин — `0069_mail_domain`, Support Pro — `0008`. Новая миграция добавляет глобальную версию и защищённую историю runtime-конфигурации; downgrade блокируется после появления истории. Реестр классифицирует все 144 поля: 96 live, 46 deployment и 2 специализированных workflow. `backend/app/release_identity.py` задаёт тег дистрибутива независимо от API. `release-manifest.template.json` — канонический источник имён релизных файлов. Загрузчик требует совпадения тега, версии API, SHA-256 и коммита; publisher проверяет CI и Docker на текущем `main`, не перемещает существующий тег и не заменяет несовпадающие assets. Матрица остаётся открытой для неперенесённых подсистем и внешней приёмки.
