# Shop by Boo — проектная спецификация

## Назначение

Платформа управляет VPN-подписками: каталогом тарифов, оплатами, entitlement-операциями, выдачей доступа через Remnawave, Telegram-ботом, Mini App, кабинетом пользователя и административным контролем.

## Контракты готовности

| Область | Реализация | Приёмка |
| --- | --- | --- |
| Remnawave | `backend/app/remnawave.py`, `provisioner.py` | retry-safe provisioning, ownership check, health evidence |
| Ноды | monitoring/provisioning API и worker | degraded/offline state, audit event, alert route |
| Платежи | YooKassa, Platega, RollyPay, sandbox | signature verification, idempotent webhook, ledger entry |
| Подписки | `subscription_commerce.py`, `subscriptions.py` | quote → payment → entitlement → retry |
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

