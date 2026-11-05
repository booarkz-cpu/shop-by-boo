# Проверка админки по модулям

Сгенерировано `python scripts/verify-admin-matrix.py` (этап 18). Для каждого модуля [матрицы управляемости](ADMIN_CONTROL_MATRIX.md) проверено, что каждый маршрут API, который что-то меняет (POST, PUT, PATCH, DELETE), вызывается тестом — backend-тестом или браузерным e2e. Также проверено, что у каждого раздела модуля есть скриншот. Сами тесты выполняются в CI; здесь — какой тест что покрывает.

**PASS** — все изменяющие маршруты покрыты тестами, у всех разделов есть скриншот. **PARTIAL** — ниже перечислено, что не покрыто.

Изменяющих маршрутов: **234 из 314** покрыты тестами; модулей PASS: **9 из 30**.

| № | Модуль | Маршрутов | Изменяющих | Покрыто тестами | Статус |
| --- | --- | --- | --- | --- | --- |
| 1 | Dashboard | 17 | 4 | 2 | PARTIAL |
| 2 | Users | 37 | 18 | 12 | PARTIAL |
| 3 | Subscriptions | 12 | 7 | 7 | PASS |
| 4 | Tariffs | 18 | 12 | 12 | PASS |
| 5 | Devices | 6 | 4 | 3 | PARTIAL |
| 6 | Payments | 35 | 19 | 12 | PARTIAL |
| 7 | Finance | 12 | 7 | 4 | PARTIAL |
| 8 | Promo Codes | 14 | 11 | 11 | PASS |
| 9 | Gifts | 6 | 3 | 3 | PASS |
| 10 | Referrals | 13 | 8 | 5 | PARTIAL |
| 11 | Remnawave | 32 | 15 | 3 | PARTIAL |
| 12 | Installation | 58 | 40 | 37 | PARTIAL |
| 13 | Servers | 9 | 6 | 6 | PASS |
| 14 | Nodes | 31 | 23 | 13 | PARTIAL |
| 15 | Domains | 7 | 6 | 5 | PARTIAL |
| 16 | Certificates | 2 | 1 | 0 | PARTIAL |
| 17 | Reverse Proxy | 1 | 0 | 0 | PASS |
| 18 | Subscription Portal | 12 | 7 | 6 | PARTIAL |
| 19 | Node Extensions | 31 | 21 | 20 | PARTIAL |
| 20 | Monitoring | 17 | 9 | 4 | PARTIAL |
| 21 | Backups | 17 | 11 | 4 | PARTIAL |
| 22 | Updates | 14 | 9 | 7 | PARTIAL |
| 23 | Automation | 9 | 4 | 2 | PARTIAL |
| 24 | Telegram | 31 | 22 | 22 | PASS |
| 25 | Integrations | 17 | 11 | 8 | PARTIAL |
| 26 | Plugins | 14 | 11 | 11 | PASS |
| 27 | Security | 28 | 12 | 7 | PARTIAL |
| 28 | Logs | 6 | 3 | 2 | PARTIAL |
| 29 | GitHub | 4 | 2 | 2 | PASS |
| 30 | Settings | 9 | 8 | 4 | PARTIAL |

## Что не покрыто

**1. Dashboard**
- нет скриншота раздела `command360`
- `POST /api/admin/v6/orchestrator/evaluate`
- `POST /api/admin/v6/provision`

**2. Users**
- нет скриншота раздела `customer360`
- `POST /api/admin/remnawave/shop/test`
- `POST /api/admin/remnawave/shop/plan-mapping/validate`
- `POST /api/admin/users/{user_id}/drop-connections`
- `POST /api/admin/remnawave/auto-update/check`
- `POST /api/admin/customer-operations/import/inspect`
- `POST /api/admin/remnawave/users/{user_id}/extend`

**5. Devices**
- `DELETE /api/admin/wg-pool/free`

**6. Payments**
- `POST /api/admin/gateways/probe`
- `POST /api/admin/gateways/auto-priority`
- `POST /api/admin/payments/{payment_id}/risk/recheck`
- `PATCH /api/admin/payments/chargebacks/{chargeback_id}`
- `POST /api/admin/payment/gift-cards`
- `PUT /api/admin/payments/pricing/experiments/{key}`
- `POST /api/admin/refunds/{refund_id}/approve`

**7. Finance**
- `DELETE /api/admin/pnl/costs/{cost_id}`
- `POST /api/admin/fiscal/test`
- `POST /api/admin/fiscal/receipts/{receipt_id}/retry`

**10. Referrals**
- `DELETE /api/admin/referral-contests/{contest_id}`
- `PUT /api/admin/referrals/program`
- `POST /api/admin/referrals/withdrawals/{withdrawal_id}/paid`

**11. Remnawave**
- `POST /api/admin/remnawave/shop/test`
- `POST /api/admin/remnawave/shop/plan-mapping/validate`
- `PUT /api/admin/panel/hosts/{host_uuid}`
- `POST /api/admin/panel/squads/{squad_uuid}/{action}`
- `POST /api/admin/panel/hosts`
- `PATCH /api/admin/panel/hosts/{host_uuid}`
- `DELETE /api/admin/panel/hosts/{host_uuid}`
- `POST /api/admin/panel/squads`
- `PATCH /api/admin/panel/squads/{squad_uuid}`
- `DELETE /api/admin/panel/squads/{squad_uuid}`
- `POST /api/admin/remnawave/auto-update/check`
- `POST /api/admin/remnawave/users/{user_id}/extend`

**12. Installation**
- `DELETE /api/admin/rw/domains/{domain_id}`
- `POST /api/admin/rw/certificates/check`
- `PATCH /api/admin/rw/extensions/subpage-configs/{config_uuid}`

**14. Nodes**
- `POST /api/admin/platform/torrents/threshold`
- `POST /api/admin/platform/plugins/{key}`
- `POST /api/admin/platform/agents`
- `POST /api/admin/platform/blacklist`
- `POST /api/admin/platform/api-keys`
- `DELETE /api/admin/platform/api-keys/{key_id}`
- `POST /api/admin/platform/webhooks`
- `PUT /api/admin/platform/mail`
- `POST /api/admin/platform/mail/test`
- `POST /api/admin/platform/dkim`

**15. Domains**
- `DELETE /api/admin/rw/domains/{domain_id}`

**16. Certificates**
- `POST /api/admin/rw/certificates/check`

**18. Subscription Portal**
- `POST /api/admin/sub-proxy/clients/refresh`

**19. Node Extensions**
- `PATCH /api/admin/rw/extensions/subpage-configs/{config_uuid}`

**20. Monitoring**
- `POST /api/admin/ops/summary/send`
- `POST /api/admin/status/components`
- `PUT /api/admin/status/components/{component_id}`
- `POST /api/admin/ops/withdrawals/{withdrawal_id}/approve`
- `POST /api/admin/ops/withdrawals/{withdrawal_id}/paid`

**21. Backups**
- `POST /api/admin/backups/telegram/send-now`
- `PUT /api/admin/backups/config`
- `POST /api/admin/backups/run`
- `POST /api/admin/backups/{backup_id}/validate`
- `POST /api/admin/backups/{backup_id}/restore/request`
- `POST /api/admin/backups/{backup_id}/restore/approve`
- `POST /api/admin/recovery/operations/{operation_id}/retry`

**22. Updates**
- `POST /api/admin/remnawave/auto-update/check`
- `POST /api/admin/deployments/{deployment_id}/rollback`

**23. Automation**
- `DELETE /api/admin/automation/campaigns/{campaign_id}`
- `POST /api/admin/jobs/{job_id}/retry`

**25. Integrations**
- нет скриншота раздела `integrations`
- `POST /api/admin/webhooks/tee/test`
- `POST /api/admin/geoip/update`
- `POST /api/admin/ripe-atlas/run`

**27. Security**
- `PUT /api/admin/fraud/payment-rules`
- `POST /api/admin/admins`
- `PUT /api/admin/admins/{admin_id}`
- `DELETE /api/admin/admins/{admin_id}`
- `POST /api/admin/security/incident`

**28. Logs**
- нет скриншота раздела `events`
- `POST /api/admin/errors/{error_id}/resolve`

**30. Settings**
- `POST /api/admin/runtime-settings/stage`
- `POST /api/admin/runtime-settings/changes/{change_id}/apply`
- `POST /api/admin/runtime-settings/changes/{change_id}/rollback`
- `DELETE /api/admin/runtime-settings/changes/{change_id}`
