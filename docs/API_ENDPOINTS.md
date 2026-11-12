# Каталог API — v28.130.0 / API v21.5.1

Сгенерирован из OpenAPI текущих исходников. Миграция: `0094_store_subscriptions`.
Авторизация, права, CSRF и принадлежность записей проверяются сервером; схема маршрута не заменяет права роли.
Сценарии: [руководство](ru/WORKSPACE_USER_GUIDE.md), [рефералы](ru/REFERRALS_CURRENT.md), [HTTP API](../API_REFERENCE_RU.md).

Legacy callbacks прежних агентов служат историческим операциям. Новые покупки используют YooKassa/Platega/RollyPay;
production gate остаётся закрытым без полного application E2E. Mobile purchase verify закрыт ответом 410.

Обновление: `PYTHONPATH=backend python scripts/generate-api-docs.py`; проверка: добавьте `--check`.
Колонка «Доступ» берётся из зависимостей маршрута: для админки — право роли (RBAC, `backend/app/security.py`),
для остальных — кто вызывает маршрут. Правила общие для всех маршрутов — в [API.md](ru/new/API.md).

| Метод | Путь | Операция | Доступ |
| --- | --- | --- | --- |
| `GET` | `/.well-known/apple-app-site-association` | Apple App Site Association | открытый |
| `GET` | `/.well-known/assetlinks.json` | Assetlinks | открытый |
| `GET` | `/api/admin/admins` | List Admins | право `manage_admins` |
| `POST` | `/api/admin/admins` | Create Admin | право `manage_admins` |
| `DELETE` | `/api/admin/admins/{admin_id}` | Delete Admin | право `manage_admins` |
| `PUT` | `/api/admin/admins/{admin_id}` | Update Admin | право `manage_admins` |
| `GET` | `/api/admin/ads/postbacks` | Get Postbacks | право `analytics.read` |
| `PUT` | `/api/admin/ads/postbacks` | Put Postbacks | право `settings.runtime.write` |
| `POST` | `/api/admin/advertisements` | Create Ad | право `manage_marketing` |
| `DELETE` | `/api/admin/advertisements/{item_id}` | Delete Ad | право `manage_marketing` |
| `PUT` | `/api/admin/advertisements/{item_id}` | Update Ad | право `manage_marketing` |
| `GET` | `/api/admin/analytics` | Admin Analytics | право `analytics.read` |
| `GET` | `/api/admin/analytics/economics` | Economics | право `analytics.read` |
| `PUT` | `/api/admin/analytics/economics/spend` | Put Spend | право `settings.runtime.write` |
| `GET` | `/api/admin/analytics/retention` | Retention | право `read` |
| `GET` | `/api/admin/analytics/traffic` | Traffic | право `analytics.read` |
| `GET` | `/api/admin/anti-sharing` | Get Anti Sharing | право `security.manage` |
| `PUT` | `/api/admin/anti-sharing` | Put Anti Sharing | право `security.manage` |
| `GET` | `/api/admin/app-analytics` | Admin Analytics | право `analytics.read` |
| `DELETE` | `/api/admin/app-config` | Admin App Config Reset | право `manage_content` |
| `GET` | `/api/admin/app-config` | Admin App Config | право `read` |
| `PUT` | `/api/admin/app-config` | Admin App Config Save | право `manage_content` |
| `GET` | `/api/admin/app-config/themes` | Themes | право `read` |
| `GET` | `/api/admin/apps` | Admin Apps | право `read` |
| `PUT` | `/api/admin/apps` | Save Apps | право `manage_content` |
| `DELETE` | `/api/admin/apps/logo` | Delete Client Logo | право `manage_content` |
| `POST` | `/api/admin/apps/logo` | Upload Client Logo | право `manage_content` |
| `GET` | `/api/admin/apps/{app_id}/download` | Admin App Download | право `read` |
| `DELETE` | `/api/admin/apps/{app_id}/file` | Delete App File | право `manage_content` |
| `POST` | `/api/admin/apps/{app_id}/file` | Upload App File | право `manage_content` |
| `GET` | `/api/admin/audit` | Admin Audit | право `read` |
| `GET` | `/api/admin/audit-seal` | Get State | право `read` |
| `POST` | `/api/admin/audit-seal/verify` | Post Verify | право `read` |
| `POST` | `/api/admin/auth/login` | Admin Login | вход администратора |
| `POST` | `/api/admin/auth/logout` | Admin Logout | вход администратора |
| `POST` | `/api/admin/auth/mfa/disable` | Mfa Disable | право `manage_own_mfa` |
| `POST` | `/api/admin/auth/mfa/enable` | Mfa Enable | право `manage_own_mfa` |
| `POST` | `/api/admin/auth/mfa/setup` | Mfa Setup | право `manage_own_mfa` |
| `GET` | `/api/admin/auth/mfa/status` | Mfa Status | право `read` |
| `POST` | `/api/admin/auth/passkeys/login/options` | Login Options | вход администратора |
| `POST` | `/api/admin/auth/passkeys/login/verify` | Login Verify | вход администратора |
| `POST` | `/api/admin/auth/passkeys/registration/options` | Registration Options | право `security.passkeys` |
| `POST` | `/api/admin/auth/passkeys/registration/verify` | Registration Verify | право `security.passkeys` |
| `POST` | `/api/admin/auth/telegram` | Admin Telegram Login | вход администратора |
| `POST` | `/api/admin/auth/ticket` | Redeem Web Ticket | вход администратора |
| `POST` | `/api/admin/auth/web-ticket` | Issue Web Ticket | вход администратора |
| `GET` | `/api/admin/auto-update` | Get Auto Update | право `ops.releases` |
| `PUT` | `/api/admin/auto-update` | Put Auto Update | право `settings.runtime.write` |
| `POST` | `/api/admin/auto-update/run` | Run Auto Update | право `settings.runtime.write` |
| `GET` | `/api/admin/automation-center` | Automation Center | право `ops.diagnostics` |
| `DELETE` | `/api/admin/automation/campaigns/{campaign_id}` | Delete Campaign | право `manage_marketing` |
| `GET` | `/api/admin/automation/catalog` | Catalog | право `read` |
| `POST` | `/api/admin/automation/presets/{preset_id}` | Create Preset | право `feature_flags.manage` |
| `DELETE` | `/api/admin/automation/rules/{rule_id}` | Delete Rule | право `feature_flags.manage` |
| `GET` | `/api/admin/automation/rules/{rule_id}/preview` | Preview | право `read` |
| `GET` | `/api/admin/backups` | List Backups | право `read` |
| `GET` | `/api/admin/backups/config` | Backup Config | право `read` |
| `PUT` | `/api/admin/backups/config` | Update Backup Config | право `manage_admins` |
| `POST` | `/api/admin/backups/run` | Run Backup | право `manage_admins` |
| `GET` | `/api/admin/backups/telegram` | Get Telegram Backup | право `backups.read` |
| `PUT` | `/api/admin/backups/telegram` | Put Telegram Backup | право `backups.write` |
| `POST` | `/api/admin/backups/telegram/send-now` | Send Now | право `backups.write` |
| `DELETE` | `/api/admin/backups/{backup_id}` | Delete Backup | право `manage_admins` |
| `GET` | `/api/admin/backups/{backup_id}/download` | Download Backup | право `manage_admins` |
| `POST` | `/api/admin/backups/{backup_id}/restore` | Restore Backup | право `backups.restore` |
| `POST` | `/api/admin/backups/{backup_id}/restore/approve` | Approve Restore | право `backups.restore` |
| `POST` | `/api/admin/backups/{backup_id}/restore/request` | Request Restore | право `backups.restore` |
| `POST` | `/api/admin/backups/{backup_id}/validate` | Validate Backup Archive | право `backups.write` |
| `POST` | `/api/admin/backups/{backup_id}/verify` | Verify Backup | право `backups.write` |
| `GET` | `/api/admin/block-monitor` | Get Monitor | право `ops.diagnostics` |
| `PUT` | `/api/admin/block-monitor` | Put Monitor | право `settings.runtime.write` |
| `POST` | `/api/admin/block-monitor/probes` | Add Probe | право `settings.runtime.write` |
| `DELETE` | `/api/admin/block-monitor/probes/{probe_id}` | Delete Probe | право `settings.runtime.write` |
| `GET` | `/api/admin/bot/banners` | List Banners | право `read` |
| `PUT` | `/api/admin/bot/banners-enabled` | Banners Enabled | право `manage_content` |
| `DELETE` | `/api/admin/bot/banners/{key}` | Reset Banner | право `manage_content` |
| `POST` | `/api/admin/bot/banners/{key}` | Upload Banner | право `manage_content` |
| `PUT` | `/api/admin/bot/banners/{key}/visibility` | Banner Visibility | право `manage_content` |
| `DELETE` | `/api/admin/bot/start-image` | Admin Bot Start Image Delete | право `manage_content` |
| `POST` | `/api/admin/bot/start-image` | Admin Bot Start Image | право `manage_content` |
| `POST` | `/api/admin/branding/favicon` | Admin Branding Favicon | право `manage_content` |
| `POST` | `/api/admin/branding/logo` | Admin Branding Logo | право `manage_content` |
| `DELETE` | `/api/admin/branding/{kind}` | Admin Branding Delete | право `manage_content` |
| `POST` | `/api/admin/broadcasts` | Create Broadcast | право `manage_broadcasts` |
| `POST` | `/api/admin/broadcasts/{broadcast_id}/retry` | Retry Broadcast | право `manage_broadcasts` |
| `GET` | `/api/admin/cabinet-texts` | Admin Texts | право `read` |
| `PUT` | `/api/admin/cabinet-texts` | Put Texts | право `manage_content` |
| `GET` | `/api/admin/cabinet/guides` | Admin Cabinet Guides | право `manage_content` |
| `PUT` | `/api/admin/cabinet/guides/{platform}` | Admin Cabinet Guide | право `manage_content` |
| `GET` | `/api/admin/cabinet/menu` | Admin Cabinet Menu | право `manage_content` |
| `POST` | `/api/admin/cabinet/menu` | Admin Cabinet Menu Create | право `manage_content` |
| `DELETE` | `/api/admin/cabinet/menu/{item_id}` | Admin Cabinet Menu Delete | право `manage_content` |
| `PUT` | `/api/admin/cabinet/menu/{item_id}` | Admin Cabinet Menu Update | право `manage_content` |
| `GET` | `/api/admin/channels` | Get Gate | право `marketing.read` |
| `PUT` | `/api/admin/channels` | Put Gate | право `manage_marketing` |
| `GET` | `/api/admin/churn` | Churn | право `analytics.read` |
| `PUT` | `/api/admin/churn` | Put Churn | право `manage_marketing` |
| `POST` | `/api/admin/churn/{user_id}/offer` | Offer | право `manage_marketing` |
| `GET` | `/api/admin/cohorts` | Admin Cohorts | право `analytics.read` |
| `GET` | `/api/admin/connection-quality` | Admin Quality | право `ops.diagnostics` |
| `GET` | `/api/admin/content` | Admin Content | право `read` |
| `GET` | `/api/admin/control-center` | Control Center | право `read` |
| `GET` | `/api/admin/corporate` | Admin List | право `read` |
| `POST` | `/api/admin/corporate` | Admin Create | право `manage_users` |
| `GET` | `/api/admin/corporate-accounts` | List Corporate | право `read` |
| `POST` | `/api/admin/corporate-accounts` | Create Corporate | право `payments.reconcile` |
| `PUT` | `/api/admin/corporate-seller` | Admin Seller | право `manage_users` |
| `GET` | `/api/admin/corporate/invoices/{invoice_id}.html` | Admin Invoice Html | право `read` |
| `POST` | `/api/admin/corporate/invoices/{invoice_id}/cancel` | Admin Invoice Cancel | право `payments.reconcile` |
| `POST` | `/api/admin/corporate/invoices/{invoice_id}/paid` | Admin Invoice Paid | право `payments.reconcile` |
| `PUT` | `/api/admin/corporate/{company_id}` | Admin Update | право `manage_users` |
| `POST` | `/api/admin/corporate/{company_id}/invoices` | Admin Invoice | право `payments.reconcile` |
| `POST` | `/api/admin/customer-operations/bulk/apply` | Bulk Apply | право `users.bulk` |
| `POST` | `/api/admin/customer-operations/bulk/preview` | Bulk Preview | право `users.bulk` |
| `GET` | `/api/admin/customer-operations/history` | History Jobs | право `users.import` |
| `POST` | `/api/admin/customer-operations/history/inspect` | Inspect | право `users.import` |
| `POST` | `/api/admin/customer-operations/history/preview` | Preview | право `users.import` |
| `POST` | `/api/admin/customer-operations/history/{job_id}/apply` | Apply | право `users.import` |
| `POST` | `/api/admin/customer-operations/history/{job_id}/cancel` | Cancel | право `users.import` |
| `POST` | `/api/admin/customer-operations/history/{job_id}/rollback` | Rollback | право `users.import` |
| `GET` | `/api/admin/customer-operations/import/history` | Import History | право `users.import` |
| `POST` | `/api/admin/customer-operations/import/inspect` | Inspect | право `users.import` |
| `POST` | `/api/admin/customer-operations/import/preview` | Import Preview | право `users.import` |
| `POST` | `/api/admin/customer-operations/import/{job_id}/apply` | Import Apply | право `users.import` |
| `POST` | `/api/admin/customer-operations/import/{job_id}/cancel` | Cancel Import | право `users.import` |
| `GET` | `/api/admin/customers/{user_id}/360` | Customer 360 | право `users.read` |
| `GET` | `/api/admin/daily-billing` | Get Daily | право `read` |
| `PUT` | `/api/admin/daily-billing` | Put Daily | право `manage_plans` |
| `GET` | `/api/admin/deployments` | Deployment List | право `ops.releases` |
| `POST` | `/api/admin/deployments` | Deployment Create | право `ops.releases` |
| `POST` | `/api/admin/deployments/{deployment_id}/promote` | Deployment Promote | право `ops.releases` |
| `POST` | `/api/admin/deployments/{deployment_id}/rollback` | Deployment Rollback | право `ops.releases` |
| `GET` | `/api/admin/digest` | Get Digest | право `analytics.read` |
| `PUT` | `/api/admin/digest` | Put Digest | право `analytics.read` |
| `POST` | `/api/admin/digest/send` | Send Digest | право `analytics.read` |
| `GET` | `/api/admin/dns-filter` | Admin Filter | право `read` |
| `PUT` | `/api/admin/dns-filter` | Admin Filter Config | право `manage_plans` |
| `GET` | `/api/admin/dunning` | Get Dunning | право `read` |
| `PUT` | `/api/admin/dunning` | Put Dunning | право `manage_plans` |
| `POST` | `/api/admin/e2e-v2/admission/attestation` | Accept Attestation | право `staging_e2e.manage` |
| `PUT` | `/api/admin/e2e-v2/admission/config` | Save Admission Config | право `staging_e2e.manage` |
| `POST` | `/api/admin/e2e-v2/admission/nonce` | Issue Nonce | право `staging_e2e.manage` |
| `GET` | `/api/admin/e2e-v2/overview` | Overview | право `staging_e2e.manage` |
| `POST` | `/api/admin/e2e-v2/runs` | Start Run | право `staging_e2e.manage` |
| `POST` | `/api/admin/e2e-v2/runs/{run_id}/cancel` | Cancel Run | право `staging_e2e.manage` |
| `GET` | `/api/admin/ecosystem-updates` | Get Ecosystem | право `ops.releases` |
| `GET` | `/api/admin/email-templates` | Get Templates | право `manage_content` |
| `DELETE` | `/api/admin/email-templates/{purpose}` | Reset Template | право `manage_content` |
| `PUT` | `/api/admin/email-templates/{purpose}` | Put Template | право `manage_content` |
| `GET` | `/api/admin/enterprise/campaigns` | Enterprise Campaigns | право `marketing.read` |
| `POST` | `/api/admin/enterprise/campaigns` | Enterprise Campaign Create | право `manage_marketing` |
| `PUT` | `/api/admin/enterprise/campaigns/{campaign_id}` | Enterprise Campaign Update | право `manage_marketing` |
| `GET` | `/api/admin/enterprise/monitoring` | Enterprise Monitoring | право `read` |
| `POST` | `/api/admin/enterprise/monitoring` | Enterprise Monitoring Create | право `ops.diagnostics` |
| `DELETE` | `/api/admin/enterprise/monitoring/{check_id}` | Enterprise Monitoring Delete | право `ops.diagnostics` |
| `GET` | `/api/admin/enterprise/rules` | Enterprise Rules | право `read` |
| `POST` | `/api/admin/enterprise/rules` | Enterprise Rule Create | право `feature_flags.manage` |
| `PUT` | `/api/admin/enterprise/rules/{rule_id}` | Enterprise Rule Update | право `feature_flags.manage` |
| `GET` | `/api/admin/enterprise/summary` | Enterprise Summary | право `read` |
| `GET` | `/api/admin/errors` | List Errors | право `ops.diagnostics` |
| `POST` | `/api/admin/errors/resolve-all` | Resolve All | право `ops.diagnostics` |
| `POST` | `/api/admin/errors/{error_id}/resolve` | Resolve Error | право `ops.diagnostics` |
| `GET` | `/api/admin/family` | Admin Family | право `read` |
| `GET` | `/api/admin/feedback` | Admin Feedback | право `support.read` |
| `PUT` | `/api/admin/feedback` | Admin Feedback Config | право `support.write` |
| `POST` | `/api/admin/fields` | Admin Field | право `manage_content` |
| `DELETE` | `/api/admin/fields/{field_id}` | Admin Field Delete | право `manage_content` |
| `PUT` | `/api/admin/fields/{field_id}` | Admin Field Update | право `manage_content` |
| `GET` | `/api/admin/financial-ledger` | Admin Financial Ledger | право `payments.read` |
| `GET` | `/api/admin/first-connect` | Get Cfg | право `manage_plans` |
| `PUT` | `/api/admin/first-connect` | Put Cfg | право `manage_plans` |
| `GET` | `/api/admin/fiscal` | Admin Fiscal | право `payments.read` |
| `PUT` | `/api/admin/fiscal` | Admin Fiscal Save | право `payments.write` |
| `POST` | `/api/admin/fiscal/receipts/{receipt_id}/retry` | Admin Fiscal Retry | право `payments.write` |
| `POST` | `/api/admin/fiscal/test` | Admin Fiscal Test | право `payments.write` |
| `GET` | `/api/admin/fraud` | Admin Fraud | право `security.manage` |
| `GET` | `/api/admin/fraud/payment-reviews` | Reviews | право `read` |
| `GET` | `/api/admin/fraud/payment-rules` | Get Rules | право `read` |
| `PUT` | `/api/admin/fraud/payment-rules` | Put Rules | право `security.manage` |
| `POST` | `/api/admin/fraud/scan` | Fraud Scan | право `security.manage` |
| `POST` | `/api/admin/fraud/{signal_id}` | Fraud Decision | право `security.manage` |
| `GET` | `/api/admin/freeze` | Admin Freeze | право `read` |
| `PUT` | `/api/admin/freeze` | Admin Freeze Config | право `manage_plans` |
| `POST` | `/api/admin/freeze/{subscription_id}/thaw` | Admin Thaw | право `users.write` |
| `GET` | `/api/admin/gateways` | Gateways Table | право `payments.read` |
| `POST` | `/api/admin/gateways/auto-priority` | Auto Priority Now | право `ops.providers` |
| `PUT` | `/api/admin/gateways/config` | Put Config | право `ops.providers` |
| `GET` | `/api/admin/gateways/notifications` | Notifications | право `payments.read` |
| `POST` | `/api/admin/gateways/probe` | Probe Now | право `ops.providers` |
| `GET` | `/api/admin/geoip` | Get Geoip | право `analytics.read` |
| `PUT` | `/api/admin/geoip` | Put Geoip | право `settings.runtime.write` |
| `POST` | `/api/admin/geoip/update` | Update Geoip | право `settings.runtime.write` |
| `GET` | `/api/admin/gift-batches` | List Batches | право `marketing.read` |
| `POST` | `/api/admin/gift-batches` | Create Batch | право `manage_marketing` |
| `DELETE` | `/api/admin/gift-batches/{tag}` | Disable Batch | право `manage_marketing` |
| `GET` | `/api/admin/gift-batches/{tag}.csv` | Export Batch | право `marketing.read` |
| `GET` | `/api/admin/gifts` | Admin Gifts | право `marketing.read` |
| `POST` | `/api/admin/gifts` | Admin Gift Create | право `manage_marketing` |
| `GET` | `/api/admin/github-update` | Admin Github Update | право `ops.releases` |
| `GET` | `/api/admin/giveaways` | Admin List | право `marketing.read` |
| `POST` | `/api/admin/giveaways` | Create | право `manage_marketing` |
| `DELETE` | `/api/admin/giveaways/{giveaway_id}` | Delete Draft | право `manage_marketing` |
| `POST` | `/api/admin/giveaways/{giveaway_id}/close` | Close | право `manage_marketing` |
| `POST` | `/api/admin/giveaways/{giveaway_id}/draw` | Draw | право `manage_marketing` |
| `GET` | `/api/admin/giveaways/{giveaway_id}/entries` | Entries | право `manage_marketing` |
| `POST` | `/api/admin/giveaways/{giveaway_id}/publish` | Publish | право `manage_marketing` |
| `GET` | `/api/admin/grace` | Get Grace | право `read` |
| `PUT` | `/api/admin/grace` | Put Grace | право `manage_plans` |
| `POST` | `/api/admin/grace/{subscription_id}/restore-squads` | Restore | право `users.write` |
| `GET` | `/api/admin/guest-checkout` | Get Guest | право `read` |
| `PUT` | `/api/admin/guest-checkout` | Put Guest | право `settings.runtime.write` |
| `GET` | `/api/admin/health/summary` | Health Summary | право `ops.diagnostics` |
| `POST` | `/api/admin/images` | Admin Image | право `manage_content` |
| `DELETE` | `/api/admin/images/{image_id}` | Admin Image Delete | право `manage_content` |
| `GET` | `/api/admin/incident-mode` | Incident Mode Status | право `read` |
| `POST` | `/api/admin/incident-mode` | Incident Mode | право `manage_admins` |
| `GET` | `/api/admin/info-pages` | Admin List | право `read` |
| `PUT` | `/api/admin/info-pages/{kind}` | Admin Save | право `legal.write` |
| `GET` | `/api/admin/install/anti-censorship` | Anti Censorship | право `read` |
| `GET` | `/api/admin/install/catalogue` | Get Catalogue | право `read` |
| `GET` | `/api/admin/install/mtproto` | Mtproto Links | право `provision_nodes` |
| `GET` | `/api/admin/install/psiphon` | Psiphon Servers | право `provision_nodes` |
| `GET` | `/api/admin/install/snapshots` | Snapshots | право `backups.read` |
| `GET` | `/api/admin/install/snapshots-schedule` | Get Schedule | право `backups.read` |
| `PUT` | `/api/admin/install/snapshots-schedule` | Put Schedule | право `backups.write` |
| `GET` | `/api/admin/install/snapshots/{name}` | Download Snapshot | право `backups.write` |
| `GET` | `/api/admin/integrity` | Integrity | право `ops.diagnostics` |
| `GET` | `/api/admin/jobs` | Admin Jobs | право `read` |
| `POST` | `/api/admin/jobs/{job_id}/retry` | Retry Job | право `payments.retry` |
| `GET` | `/api/admin/legal` | Get Legal | право `read` |
| `PUT` | `/api/admin/legal` | Put Legal | право `legal.write` |
| `POST` | `/api/admin/legal/apply` | Apply Legal | право `legal.write` |
| `POST` | `/api/admin/logs/request` | Request Logs | право `ops.diagnostics` |
| `GET` | `/api/admin/logs/{service}` | Get Logs | право `ops.diagnostics` |
| `GET` | `/api/admin/loyalty` | Admin Loyalty | право `read` |
| `PUT` | `/api/admin/loyalty` | Admin Loyalty Config | право `manage_plans` |
| `GET` | `/api/admin/lucy-plans` | Lucy State | право `read` |
| `POST` | `/api/admin/lucy-plans` | Lucy Apply | право `manage_plans` |
| `DELETE` | `/api/admin/lucy-plans/trial` | Lucy Trial Off | право `manage_plans` |
| `POST` | `/api/admin/mail/dmarc/erase` | Admin Dmarc Erase | право `security.manage` |
| `GET` | `/api/admin/mail/dmarc/reports/{report_id}` | Admin Dmarc Report | право `ops.diagnostics` |
| `POST` | `/api/admin/mail/dmarc/sync` | Admin Dmarc Sync | право `ops.diagnostics` |
| `POST` | `/api/admin/mail/dmarc/upload` | Admin Dmarc Upload | право `ops.diagnostics` |
| `GET` | `/api/admin/mail/domain` | Admin Mail Domain | право `ops.diagnostics` |
| `POST` | `/api/admin/mail/domain/check` | Admin Mail Check | право `ops.diagnostics` |
| `GET` | `/api/admin/marketing` | Admin Marketing | право `read` |
| `GET` | `/api/admin/marketplace/resellers` | List Resellers | право `referrals.read` |
| `POST` | `/api/admin/marketplace/resellers` | Create Reseller | право `referrals.reconcile` |
| `PATCH` | `/api/admin/marketplace/resellers/{reseller_id}` | Update Reseller | право `referrals.reconcile` |
| `POST` | `/api/admin/marketplace/resellers/{reseller_id}/deposit` | Deposit | право `referrals.reconcile` |
| `POST` | `/api/admin/marketplace/resellers/{reseller_id}/rotate-key` | Rotate Reseller Key | право `referrals.reconcile` |
| `GET` | `/api/admin/marketplace/withdrawals` | Withdrawals | право `referrals.withdrawals.read` |
| `POST` | `/api/admin/marketplace/withdrawals/{withdrawal_id}/decision` | Decide | право `referrals.withdrawals.approve` |
| `GET` | `/api/admin/masque` | State | право `read` |
| `GET` | `/api/admin/masque/panel` | Panel | право `read` |
| `POST` | `/api/admin/masque/panel/nodes/{server_id}/install` | Install | право `provision_nodes` |
| `POST` | `/api/admin/masque/panel/nodes/{server_id}/remove` | Remove | право `provision_nodes` |
| `POST` | `/api/admin/masque/panel/nodes/{server_id}/status` | Status | право `read` |
| `PUT` | `/api/admin/masque/panel/settings` | Save Settings | право `provision_nodes` |
| `POST` | `/api/admin/masque/panel/sync` | Sync | право `provision_nodes` |
| `GET` | `/api/admin/masque/panel/users` | Users | право `provision_nodes` |
| `POST` | `/api/admin/menu` | Admin Menu | право `manage_content` |
| `DELETE` | `/api/admin/menu/{item_id}` | Admin Menu Delete | право `manage_content` |
| `PUT` | `/api/admin/menu/{item_id}` | Admin Menu Update | право `manage_content` |
| `DELETE` | `/api/admin/miniapp/background` | Admin Miniapp Background Delete | право `manage_content` |
| `POST` | `/api/admin/miniapp/background` | Admin Miniapp Background | право `manage_content` |
| `PUT` | `/api/admin/miniapp/config` | Admin Miniapp Config | право `manage_content` |
| `DELETE` | `/api/admin/miniapp/image` | Admin Miniapp Image Delete | право `manage_content` |
| `POST` | `/api/admin/miniapp/image` | Admin Miniapp Image | право `manage_content` |
| `PUT` | `/api/admin/miniapp/menu` | Save Mini Tree | право `manage_content` |
| `DELETE` | `/api/admin/mobile-layout` | Admin Mobile Layout Reset | право `manage_content` |
| `GET` | `/api/admin/mobile-layout` | Admin Mobile Layout | право `read` |
| `PUT` | `/api/admin/mobile-layout` | Admin Mobile Layout Save | право `manage_content` |
| `GET` | `/api/admin/mobile/mirrors` | Get Mirrors | право `settings.runtime.read` |
| `PUT` | `/api/admin/mobile/mirrors` | Put Mirrors | право `settings.runtime.write` |
| `POST` | `/api/admin/mobile/mirrors/publish` | Publish Now | право `settings.runtime.write` |
| `GET` | `/api/admin/mobile/ops` | Admin Mobile Ops | право `read` |
| `GET` | `/api/admin/mobile/panels` | Mobile Panels | право `ops.diagnostics` |
| `GET` | `/api/admin/moderation` | Get Moderation | право `users.read` |
| `PUT` | `/api/admin/moderation` | Put Moderation | право `users.write` |
| `POST` | `/api/admin/moderation/ban` | Bulk Ban | право `users.write` |
| `PUT` | `/api/admin/moderation/blacklist` | Put Blacklist | право `users.write` |
| `POST` | `/api/admin/moderation/blocked-cleanup` | Blocked Cleanup | право `users.write` |
| `POST` | `/api/admin/moderation/blocked-scan` | Start Scan | право `users.write` |
| `POST` | `/api/admin/moderation/invites` | Create Invite | право `users.write` |
| `DELETE` | `/api/admin/moderation/invites/{invite_id}` | Disable Invite | право `users.write` |
| `GET` | `/api/admin/monitoring` | Admin Monitoring | право `read` |
| `GET` | `/api/admin/network/intel` | Admin Network Intel | право `ops.diagnostics` |
| `POST` | `/api/admin/network/intel/refresh` | Admin Network Refresh | право `ops.diagnostics` |
| `GET` | `/api/admin/nodes/autoscale` | Get Autoscale | право `ops.diagnostics` |
| `PUT` | `/api/admin/nodes/autoscale` | Put Autoscale | право `provision_nodes` |
| `GET` | `/api/admin/nodes/forecast` | Get Forecast | право `ops.diagnostics` |
| `PUT` | `/api/admin/nodes/forecast` | Put Forecast | право `provision_nodes` |
| `GET` | `/api/admin/nodes/health` | Nodes Health | право `ops.diagnostics` |
| `PUT` | `/api/admin/nodes/health/config` | Nodes Health Config | право `settings.runtime.write` |
| `POST` | `/api/admin/nodes/update` | Update Nodes | право `provision_nodes` |
| `PATCH` | `/api/admin/nodes/{node_uuid}` | Node Patch | право `provision_nodes` |
| `POST` | `/api/admin/nodes/{node_uuid}/restart` | Restart Node | право `provision_nodes` |
| `POST` | `/api/admin/nodes/{node_uuid}/{action}` | Node Switch | право `provision_nodes` |
| `GET` | `/api/admin/notifications` | Admin Notifications | право `read` |
| `POST` | `/api/admin/notifications` | Admin Notification Create | право `manage_content` |
| `GET` | `/api/admin/openapi.json` | Admin Openapi | право `read` |
| `GET` | `/api/admin/ops/alerts` | Alerts Status | право `ops.diagnostics` |
| `POST` | `/api/admin/ops/alerts/test` | Alerts Test | право `ops.diagnostics` |
| `GET` | `/api/admin/ops/readiness` | Readiness | право `ops.diagnostics` |
| `GET` | `/api/admin/ops/summary` | Summary Preview | право `ops.diagnostics` |
| `POST` | `/api/admin/ops/summary/send` | Summary Send Now | право `ops.diagnostics` |
| `POST` | `/api/admin/ops/withdrawals/{withdrawal_id}/approve` | Admin Withdrawal Approve | право `referrals.withdrawals.approve` |
| `POST` | `/api/admin/ops/withdrawals/{withdrawal_id}/paid` | Admin Withdrawal Paid | право `referrals.withdrawals.pay` |
| `GET` | `/api/admin/overview` | Admin Overview | право `read` |
| `GET` | `/api/admin/pages` | Pages | право `manage_content` |
| `POST` | `/api/admin/pages` | Create | право `manage_content` |
| `GET` | `/api/admin/pages/{page_id}` | Get | право `manage_content` |
| `PUT` | `/api/admin/pages/{page_id}` | Save | право `manage_content` |
| `POST` | `/api/admin/pages/{page_id}/archive` | Archive | право `manage_content` |
| `POST` | `/api/admin/pages/{page_id}/publish` | Publish | право `manage_content` |
| `POST` | `/api/admin/pages/{page_id}/restore` | Restore | право `manage_content` |
| `GET` | `/api/admin/pages/{page_id}/revisions` | Revisions | право `manage_content` |
| `GET` | `/api/admin/panel-api-stats` | Get Stats | право `ops.diagnostics` |
| `GET` | `/api/admin/panel-changes` | Changes | право `users.read` |
| `GET` | `/api/admin/panel-changes.csv` | Changes Csv | право `users.read` |
| `GET` | `/api/admin/panel-guard` | Get Guard | право `ops.diagnostics` |
| `PUT` | `/api/admin/panel-guard` | Put Guard | право `settings.runtime.write` |
| `POST` | `/api/admin/panel/hosts` | Host Create | право `provision_nodes` |
| `DELETE` | `/api/admin/panel/hosts/{host_uuid}` | Host Delete | право `provision_nodes` |
| `PATCH` | `/api/admin/panel/hosts/{host_uuid}` | Host Update | право `provision_nodes` |
| `PUT` | `/api/admin/panel/hosts/{host_uuid}` | Set Host | право `provision_nodes` |
| `GET` | `/api/admin/panel/overview` | Panel Overview | право `ops.diagnostics` |
| `POST` | `/api/admin/panel/squads` | Squad Create | право `provision_nodes` |
| `DELETE` | `/api/admin/panel/squads/{squad_uuid}` | Squad Delete | право `provision_nodes` |
| `PATCH` | `/api/admin/panel/squads/{squad_uuid}` | Squad Update | право `provision_nodes` |
| `POST` | `/api/admin/panel/squads/{squad_uuid}/{action}` | Squad Bulk | право `provision_nodes` |
| `POST` | `/api/admin/payment/gift-cards` | Create Gift Card | право `payments.reconcile` |
| `GET` | `/api/admin/payments` | Admin Payments | право `read` |
| `GET` | `/api/admin/payments/analytics` | Payment Analytics | право `read` |
| `GET` | `/api/admin/payments/chargebacks` | Admin Chargebacks | право `read` |
| `PATCH` | `/api/admin/payments/chargebacks/{chargeback_id}` | Update Chargeback | право `payments.reconcile` |
| `GET` | `/api/admin/payments/events` | Payment Events | право `payments.read` |
| `GET` | `/api/admin/payments/gift-cards` | List Gift Cards | право `read` |
| `GET` | `/api/admin/payments/methods` | Get Routing | право `ops.diagnostics` |
| `PUT` | `/api/admin/payments/methods` | Put Routing | право `settings.runtime.write` |
| `GET` | `/api/admin/payments/platform/capabilities` | Admin Payment Platform Capabilities | право `read` |
| `GET` | `/api/admin/payments/pricing/experiments` | List Price Experiments | право `read` |
| `PUT` | `/api/admin/payments/pricing/experiments/{key}` | Upsert Price Experiment | право `payments.reconcile` |
| `POST` | `/api/admin/payments/production-gate` | Production Payment Gate | право `security.manage` |
| `GET` | `/api/admin/payments/providers-report` | Providers Report | право `payments.read` |
| `POST` | `/api/admin/payments/reconcile` | Reconcile Payments | право `payments.reconcile` |
| `GET` | `/api/admin/payments/{payment_id}` | Admin Payment Detail | право `read` |
| `POST` | `/api/admin/payments/{payment_id}/refund-request` | Request Refund | право `payments.reconcile` |
| `POST` | `/api/admin/payments/{payment_id}/retry` | Retry Payment | право `payments.retry` |
| `POST` | `/api/admin/payments/{payment_id}/risk/recheck` | Payment Risk Recheck | право `payments.reconcile` |
| `GET` | `/api/admin/payouts` | Admin Payouts | право `referrals.withdrawals.read` |
| `POST` | `/api/admin/personal-offers` | Create Offer | право `manage_marketing` |
| `DELETE` | `/api/admin/pinned-message` | Remove | право `manage_broadcasts` |
| `GET` | `/api/admin/pinned-message` | Get Pinned | право `marketing.read` |
| `POST` | `/api/admin/pinned-message` | Publish | право `manage_broadcasts` |
| `GET` | `/api/admin/plans` | Admin List Plans | право `read` |
| `POST` | `/api/admin/plans` | Create Plan | право `manage_plans` |
| `DELETE` | `/api/admin/plans/{plan_id}` | Admin Delete Plan | право `manage_plans` |
| `PUT` | `/api/admin/plans/{plan_id}` | Admin Update Plan | право `manage_plans` |
| `POST` | `/api/admin/plans/{plan_id}/enabled` | Admin Set Plan Enabled | право `manage_plans` |
| `POST` | `/api/admin/platform/agents` | Create Agent | право `manage_users` |
| `POST` | `/api/admin/platform/api-keys` | Create Api Key | право `security.manage` |
| `DELETE` | `/api/admin/platform/api-keys/{key_id}` | Disable Api Key | право `security.manage` |
| `POST` | `/api/admin/platform/blacklist` | Add Blacklist | право `manage_users` |
| `POST` | `/api/admin/platform/dkim` | Create Dkim | право `security.manage` |
| `PUT` | `/api/admin/platform/mail` | Save Mail | право `security.manage` |
| `POST` | `/api/admin/platform/mail/test` | Test Mail | право `security.manage` |
| `POST` | `/api/admin/platform/plugins/{key}` | Toggle Plugin | право `manage_users` |
| `PUT` | `/api/admin/platform/policy` | Save Policy | право `manage_users` |
| `GET` | `/api/admin/platform/summary` | Platform Summary | право `read` |
| `GET` | `/api/admin/platform/torrents` | Admin Torrents | право `ops.diagnostics` |
| `POST` | `/api/admin/platform/torrents/notify` | Admin Torrents Notify | право `security.manage` |
| `POST` | `/api/admin/platform/torrents/threshold` | Admin Torrents Threshold | право `security.manage` |
| `POST` | `/api/admin/platform/violations/{violation_id}/review` | Review Violation | право `manage_users` |
| `POST` | `/api/admin/platform/webhooks` | Create Webhook | право `security.manage` |
| `GET` | `/api/admin/plugins` | Admin Plugins | право `ops.diagnostics` |
| `GET` | `/api/admin/plugins/catalog` | Catalog | право `ops.diagnostics` |
| `POST` | `/api/admin/plugins/catalog/install` | Catalog Install | право `security.manage` |
| `GET` | `/api/admin/plugins/catalogs` | Catalog Settings | право `ops.diagnostics` |
| `PUT` | `/api/admin/plugins/catalogs` | Save Catalogs | право `security.manage` |
| `POST` | `/api/admin/plugins/publishers` | Add Publisher | право `security.manage` |
| `POST` | `/api/admin/plugins/publishers/{publisher_id}/revoke` | Revoke Publisher | право `security.manage` |
| `POST` | `/api/admin/plugins/upload` | Upload | право `security.manage` |
| `DELETE` | `/api/admin/plugins/{plugin_id}` | Uninstall | право `security.manage` |
| `POST` | `/api/admin/plugins/{plugin_id}/disable` | Disable | право `security.manage` |
| `POST` | `/api/admin/plugins/{plugin_id}/enable` | Enable | право `security.manage` |
| `POST` | `/api/admin/plugins/{plugin_id}/rollback` | Rollback | право `security.manage` |
| `POST` | `/api/admin/plugins/{plugin_id}/rotate` | Rotate | право `security.manage` |
| `POST` | `/api/admin/plugins/{plugin_id}/settings` | Save Settings | право `security.manage` |
| `GET` | `/api/admin/pnl` | Pnl | право `analytics.read` |
| `GET` | `/api/admin/pnl/costs` | List Costs | право `analytics.read` |
| `POST` | `/api/admin/pnl/costs` | Add Cost | право `payments.reconcile` |
| `DELETE` | `/api/admin/pnl/costs/{cost_id}` | Delete Cost | право `payments.reconcile` |
| `PUT` | `/api/admin/pnl/fees` | Put Fees | право `payments.reconcile` |
| `GET` | `/api/admin/pricing/regions` | Get Regions | право `read` |
| `PUT` | `/api/admin/pricing/regions` | Put Regions | право `manage_plans` |
| `GET` | `/api/admin/pricing/regions/preview` | Preview | право `read` |
| `GET` | `/api/admin/promo-audiences` | Audiences | право `manage_marketing` |
| `PUT` | `/api/admin/promo-audiences/{promo_id}` | Set Audience | право `manage_marketing` |
| `POST` | `/api/admin/promo-codes` | Create Promo Code | право `manage_marketing` |
| `GET` | `/api/admin/promo-codes/export.csv` | Export Promo Codes | право `marketing.read` |
| `POST` | `/api/admin/promo-codes/generate` | Generate Promo Codes | право `manage_marketing` |
| `DELETE` | `/api/admin/promo-codes/{item_id}` | Delete Promo Code | право `manage_marketing` |
| `PUT` | `/api/admin/promo-codes/{item_id}` | Update Promo Code | право `manage_marketing` |
| `GET` | `/api/admin/promo-groups` | Groups | право `manage_marketing` |
| `POST` | `/api/admin/promo-groups` | Create Group | право `manage_marketing` |
| `PUT` | `/api/admin/promo-groups/{group_id}` | Update Group | право `manage_marketing` |
| `POST` | `/api/admin/promotions` | Create Promotion | право `manage_marketing` |
| `DELETE` | `/api/admin/promotions/{item_id}` | Delete Promotion | право `manage_marketing` |
| `PUT` | `/api/admin/promotions/{item_id}` | Update Promotion | право `manage_marketing` |
| `POST` | `/api/admin/provision-node` | Provision Node | право `provision_nodes` |
| `GET` | `/api/admin/push-campaigns` | List Campaigns | право `marketing.read` |
| `POST` | `/api/admin/push-campaigns` | Create Campaign | право `manage_broadcasts` |
| `POST` | `/api/admin/push-campaigns/preview` | Preview Campaign | право `marketing.read` |
| `POST` | `/api/admin/push-campaigns/{campaign_id}/cancel` | Cancel | право `manage_broadcasts` |
| `GET` | `/api/admin/push-campaigns/{campaign_id}/results` | Results | право `marketing.read` |
| `DELETE` | `/api/admin/push-style` | Admin Push Style Reset | право `manage_content` |
| `GET` | `/api/admin/push-style` | Admin Push Style | право `marketing.read` |
| `PUT` | `/api/admin/push-style` | Admin Push Style Save | право `manage_content` |
| `GET` | `/api/admin/push/status` | Admin Push Status | право `ops.diagnostics` |
| `GET` | `/api/admin/recovery` | Admin Recovery | право `read` |
| `GET` | `/api/admin/recovery/operations` | Recovery Operations | право `read` |
| `POST` | `/api/admin/recovery/operations/{operation_id}/retry` | Retry Operation | право `payments.retry` |
| `GET` | `/api/admin/referral-contests` | List Contests | право `referrals.read` |
| `POST` | `/api/admin/referral-contests` | Create Contest | право `referrals.reconcile` |
| `DELETE` | `/api/admin/referral-contests/{contest_id}` | Cancel Contest | право `referrals.reconcile` |
| `GET` | `/api/admin/referrals/bonus` | Get Bonus | право `referrals.read` |
| `PUT` | `/api/admin/referrals/bonus` | Set Bonus | право `referrals.reconcile` |
| `GET` | `/api/admin/referrals/program` | Get Program | право `referrals.reconcile` |
| `PUT` | `/api/admin/referrals/program` | Set Program | право `referrals.reconcile` |
| `POST` | `/api/admin/referrals/reconcile` | Reconcile Referrals | право `referrals.reconcile` |
| `GET` | `/api/admin/referrals/withdrawals` | Admin Withdrawals | право `referrals.withdrawals.read` |
| `POST` | `/api/admin/referrals/withdrawals/{withdrawal_id}/approve` | Approve Withdrawal | право `referrals.withdrawals.approve` |
| `POST` | `/api/admin/referrals/withdrawals/{withdrawal_id}/paid` | Paid Withdrawal | право `referrals.withdrawals.pay` |
| `POST` | `/api/admin/referrals/withdrawals/{withdrawal_id}/reject` | Reject Withdrawal | право `referrals.withdrawals.approve` |
| `GET` | `/api/admin/refunds` | Admin Refunds | право `read` |
| `POST` | `/api/admin/refunds/{refund_id}/approve` | Approve Refund | право `payments.reconcile` |
| `GET` | `/api/admin/refunds/{refund_id}/dry-run` | Refund Dry Run | право `payments.refund` |
| `POST` | `/api/admin/refunds/{refund_id}/execute` | Execute Refund | право `payments.refund` |
| `POST` | `/api/admin/refunds/{refund_id}/mark-refunded` | Mark Refunded | право `payments.refund` |
| `POST` | `/api/admin/refunds/{refund_id}/reconcile` | Reconcile Refund | право `payments.reconcile` |
| `POST` | `/api/admin/refunds/{refund_id}/retry-revoke` | Retry Refund Revoke | право `payments.refund` |
| `GET` | `/api/admin/releases` | Admin Releases | право `read` |
| `POST` | `/api/admin/releases/check` | Check Release | право `read` |
| `GET` | `/api/admin/remnawave/auto-update` | Get Auto Update | право `ops.releases` |
| `PUT` | `/api/admin/remnawave/auto-update` | Put Auto Update | право `provision_nodes` |
| `POST` | `/api/admin/remnawave/auto-update/check` | Check Releases | право `ops.releases` |
| `GET` | `/api/admin/remnawave/auto-update/panel-copies/{name}` | Download Panel Copy | право `backups.write` |
| `POST` | `/api/admin/remnawave/auto-update/run` | Run Now | право `provision_nodes` |
| `GET` | `/api/admin/remnawave/health` | Remnawave Health | право `read` |
| `GET` | `/api/admin/remnawave/internal-squads` | Remnawave Internal Squads | право `read` |
| `GET` | `/api/admin/remnawave/monitoring` | Admin Monitoring | право `read` |
| `GET` | `/api/admin/remnawave/nodes` | Rw Nodes | право `read` |
| `GET` | `/api/admin/remnawave/shop` | Remnawave Shop Overview | право `read` |
| `POST` | `/api/admin/remnawave/shop/plan-mapping/validate` | Validate Plan Mapping | право `read` |
| `POST` | `/api/admin/remnawave/shop/test` | Remnawave Shop Test | право `read` |
| `GET` | `/api/admin/remnawave/users` | Rw Users | право `read` |
| `GET` | `/api/admin/remnawave/users/stream` | Rw User Stream | право `read` |
| `GET` | `/api/admin/remnawave/users/{user_id}` | Rw User | право `read` |
| `POST` | `/api/admin/remnawave/users/{user_id}/extend` | Rw Extend | право `manage_users` |
| `GET` | `/api/admin/remnawave/users/{user_id}/keys` | Rw Keys | право `users.keys` |
| `GET` | `/api/admin/remnawave/users/{user_id}/subscription` | Rw Subscription | право `users.keys` |
| `GET` | `/api/admin/ripe-atlas` | Get Ripe | право `ops.diagnostics` |
| `PUT` | `/api/admin/ripe-atlas` | Put Ripe | право `settings.runtime.write` |
| `POST` | `/api/admin/ripe-atlas/run` | Run Ripe | право `ops.diagnostics` |
| `GET` | `/api/admin/roles` | Roles | право `read` |
| `GET` | `/api/admin/runtime-settings` | Admin Runtime Settings | право `settings.runtime.read` |
| `DELETE` | `/api/admin/runtime-settings/changes/{change_id}` | Admin Discard Runtime Settings | право `settings.runtime.write` |
| `POST` | `/api/admin/runtime-settings/changes/{change_id}/apply` | Admin Apply Runtime Settings | право `settings.runtime.write` |
| `POST` | `/api/admin/runtime-settings/changes/{change_id}/rollback` | Admin Rollback Runtime Settings | право `settings.runtime.write` |
| `POST` | `/api/admin/runtime-settings/stage` | Admin Stage Runtime Settings | право `settings.runtime.write` |
| `DELETE` | `/api/admin/rw/autoselect` | Delete Pool | право `provision_nodes` |
| `GET` | `/api/admin/rw/autoselect` | Get Pool | право `read` |
| `PUT` | `/api/admin/rw/autoselect` | Put Pool | право `provision_nodes` |
| `GET` | `/api/admin/rw/autoselect/meta` | Meta | право `read` |
| `POST` | `/api/admin/rw/autoselect/refresh` | Refresh Pool | право `provision_nodes` |
| `GET` | `/api/admin/rw/certificates` | Certificates | право `read` |
| `POST` | `/api/admin/rw/certificates/check` | Check All | право `read` |
| `GET` | `/api/admin/rw/domains` | List Domains | право `read` |
| `POST` | `/api/admin/rw/domains` | Add Domain | право `settings.runtime.write` |
| `DELETE` | `/api/admin/rw/domains/{domain_id}` | Delete Domain | право `settings.runtime.write` |
| `PATCH` | `/api/admin/rw/domains/{domain_id}` | Patch Domain | право `settings.runtime.write` |
| `POST` | `/api/admin/rw/domains/{domain_id}/check` | Check Domain | право `read` |
| `POST` | `/api/admin/rw/domains/{domain_id}/dns-record` | Upsert Dns Record | право `settings.runtime.write` |
| `POST` | `/api/admin/rw/domains/{domain_id}/primary` | Make Primary | право `settings.runtime.write` |
| `POST` | `/api/admin/rw/drift/check` | Check | право `read` |
| `GET` | `/api/admin/rw/drift/meta` | Meta | право `read` |
| `GET` | `/api/admin/rw/extensions` | Overview | право `read` |
| `POST` | `/api/admin/rw/extensions/nodes/{node_uuid}/plugin` | Node Plugin | право `provision_nodes` |
| `POST` | `/api/admin/rw/extensions/nodes/{node_uuid}/profile` | Node Profile | право `provision_nodes` |
| `POST` | `/api/admin/rw/extensions/plugins` | Create Plugin | право `provision_nodes` |
| `DELETE` | `/api/admin/rw/extensions/plugins/{plugin_uuid}` | Delete Plugin | право `provision_nodes` |
| `PATCH` | `/api/admin/rw/extensions/plugins/{plugin_uuid}` | Patch Plugin | право `provision_nodes` |
| `GET` | `/api/admin/rw/extensions/presets` | Presets | право `read` |
| `POST` | `/api/admin/rw/extensions/profiles` | Create Profile | право `provision_nodes` |
| `POST` | `/api/admin/rw/extensions/profiles/reality` | Create Reality | право `provision_nodes` |
| `DELETE` | `/api/admin/rw/extensions/profiles/{profile_uuid}` | Delete Profile | право `provision_nodes` |
| `GET` | `/api/admin/rw/extensions/profiles/{profile_uuid}` | Get Profile | право `read` |
| `PATCH` | `/api/admin/rw/extensions/profiles/{profile_uuid}` | Patch Profile | право `provision_nodes` |
| `POST` | `/api/admin/rw/extensions/profiles/{profile_uuid}/adblock` | Profile Adblock | право `provision_nodes` |
| `POST` | `/api/admin/rw/extensions/profiles/{profile_uuid}/host` | Profile Host | право `provision_nodes` |
| `POST` | `/api/admin/rw/extensions/profiles/{profile_uuid}/warp` | Profile Warp | право `provision_nodes` |
| `GET` | `/api/admin/rw/extensions/routing` | List Routing | право `read` |
| `POST` | `/api/admin/rw/extensions/routing` | Create Routing | право `provision_nodes` |
| `DELETE` | `/api/admin/rw/extensions/routing/{profile_uuid}` | Delete Routing | право `provision_nodes` |
| `POST` | `/api/admin/rw/extensions/srr-test` | Srr Test | право `read` |
| `GET` | `/api/admin/rw/extensions/subpage-configs` | Subpage Configs | право `read` |
| `POST` | `/api/admin/rw/extensions/subpage-configs` | Create Subpage Config | право `settings.runtime.write` |
| `DELETE` | `/api/admin/rw/extensions/subpage-configs/{config_uuid}` | Delete Subpage Config | право `settings.runtime.write` |
| `GET` | `/api/admin/rw/extensions/subpage-configs/{config_uuid}` | Subpage Config | право `read` |
| `PATCH` | `/api/admin/rw/extensions/subpage-configs/{config_uuid}` | Patch Subpage Config | право `settings.runtime.write` |
| `GET` | `/api/admin/rw/extensions/subscription-settings` | Subscription Settings | право `read` |
| `PATCH` | `/api/admin/rw/extensions/subscription-settings` | Patch Subscription Settings | право `settings.runtime.write` |
| `GET` | `/api/admin/rw/extensions/templates` | Templates | право `read` |
| `POST` | `/api/admin/rw/extensions/templates` | Create Template | право `settings.runtime.write` |
| `DELETE` | `/api/admin/rw/extensions/templates/{template_uuid}` | Delete Template | право `settings.runtime.write` |
| `GET` | `/api/admin/rw/extensions/templates/{template_uuid}` | Template | право `read` |
| `PATCH` | `/api/admin/rw/extensions/templates/{template_uuid}` | Patch Template | право `settings.runtime.write` |
| `GET` | `/api/admin/rw/extensions/x25519` | X25519 | право `provision_nodes` |
| `GET` | `/api/admin/rw/installations` | List Installations | право `read` |
| `POST` | `/api/admin/rw/installations/plan` | Plan Installation | право `provision_nodes` |
| `GET` | `/api/admin/rw/installations/{installation_id}` | Get Installation | право `read` |
| `POST` | `/api/admin/rw/installations/{installation_id}/actions` | Action | право `provision_nodes` |
| `POST` | `/api/admin/rw/installations/{installation_id}/approve` | Approve | право `provision_nodes` |
| `POST` | `/api/admin/rw/installations/{installation_id}/cancel` | Cancel | право `provision_nodes` |
| `POST` | `/api/admin/rw/installations/{installation_id}/connect-shop` | Connect Shop | право `provision_nodes`, право `settings.runtime.write` |
| `POST` | `/api/admin/rw/installations/{installation_id}/credentials` | Credentials | право `provision_nodes` |
| `POST` | `/api/admin/rw/installations/{installation_id}/panel-gate` | Open Panel | право `provision_nodes` |
| `GET` | `/api/admin/rw/installations/{installation_id}/xray-checker` | Xray Checker | право `read` |
| `GET` | `/api/admin/rw/meta` | Meta | право `read` |
| `GET` | `/api/admin/rw/protocol-switch` | Overview | право `read` |
| `POST` | `/api/admin/rw/protocol-switch` | Start | право `provision_nodes` |
| `GET` | `/api/admin/rw/protocol-switch/meta` | Meta | право `read` |
| `POST` | `/api/admin/rw/protocol-switch/{job_id}/check` | Check | право `provision_nodes` |
| `POST` | `/api/admin/rw/protocol-switch/{job_id}/rollback` | Rollback | право `provision_nodes` |
| `GET` | `/api/admin/rw/proxy-routes` | Proxy Routes | право `read` |
| `GET` | `/api/admin/rw/selfsteal/catalogue` | Catalogue | право `read` |
| `POST` | `/api/admin/rw/selfsteal/check` | Check | право `provision_nodes` |
| `GET` | `/api/admin/rw/selfsteal/overview` | Overview | право `read` |
| `GET` | `/api/admin/rw/selfsteal/preview/{template}` | Preview | право `read` |
| `GET` | `/api/admin/rw/selfsteal/sites` | List Sites | право `read` |
| `POST` | `/api/admin/rw/selfsteal/sites` | Upload Site | право `provision_nodes` |
| `DELETE` | `/api/admin/rw/selfsteal/sites/{site_id}` | Delete Site | право `provision_nodes` |
| `GET` | `/api/admin/rw/servers` | List Servers | право `read` |
| `POST` | `/api/admin/rw/servers` | Create Server | право `provision_nodes` |
| `POST` | `/api/admin/rw/servers/scan` | Scan | право `provision_nodes` |
| `DELETE` | `/api/admin/rw/servers/{server_id}` | Delete Server | право `provision_nodes` |
| `PATCH` | `/api/admin/rw/servers/{server_id}` | Patch Server | право `provision_nodes` |
| `POST` | `/api/admin/rw/servers/{server_id}/check` | Check Server | право `provision_nodes` |
| `POST` | `/api/admin/rw/servers/{server_id}/rotate-key` | Rotate Key | право `provision_nodes` |
| `GET` | `/api/admin/rw/torrent-ban` | Get State | право `read` |
| `PUT` | `/api/admin/rw/torrent-ban` | Apply | право `provision_nodes` |
| `GET` | `/api/admin/security` | Admin Security | право `read` |
| `GET` | `/api/admin/security/history` | Security History | право `sessions.manage` |
| `POST` | `/api/admin/security/incident` | Security Incident | право `manage_admins` |
| `GET` | `/api/admin/security/incidents` | Security Incidents | право `read` |
| `GET` | `/api/admin/security/risk-summary` | Risk Summary | право `security.manage` |
| `GET` | `/api/admin/security/secrets/status` | Secret Status | право `manage_admins` |
| `GET` | `/api/admin/security/step-up` | Step Up State | право `security.stepup` |
| `POST` | `/api/admin/security/step-up` | Step Up | право `security.stepup` |
| `GET` | `/api/admin/sessions` | Admin Sessions | право `sessions.manage` |
| `GET` | `/api/admin/sessions/anomalies` | Get Anomalies | право `users.read` |
| `GET` | `/api/admin/sessions/config` | Get Config | право `ops.diagnostics` |
| `PUT` | `/api/admin/sessions/config` | Put Config | право `settings.runtime.write` |
| `GET` | `/api/admin/sessions/geo` | Geography | право `analytics.read` |
| `GET` | `/api/admin/sessions/mine` | My Sessions | право `sessions.self` |
| `DELETE` | `/api/admin/sessions/mine/{session_id}` | Revoke My Session | право `sessions.self` |
| `POST` | `/api/admin/sessions/revoke-all` | Revoke All Sessions | право `sessions.manage` |
| `DELETE` | `/api/admin/sessions/{session_id}` | Revoke Admin Session | право `sessions.manage` |
| `PUT` | `/api/admin/settings/{key}` | Admin Setting | право `manage_content` |
| `GET` | `/api/admin/speedtest` | Admin Speed | право `ops.diagnostics` |
| `PUT` | `/api/admin/speedtest` | Admin Speed Config | право `ops.diagnostics` |
| `GET` | `/api/admin/staging-e2e/config` | Staging E2E Config | право `staging_e2e.manage` |
| `PUT` | `/api/admin/staging-e2e/config` | Update Staging E2E Config | право `staging_e2e.manage` |
| `POST` | `/api/admin/staging-e2e/run` | Run Staging E2E | право `staging_e2e.manage` |
| `GET` | `/api/admin/staging-e2e/status` | Staging E2E Status | право `staging_e2e.manage` |
| `GET` | `/api/admin/standby` | Get Standby | право `ops.diagnostics` |
| `PUT` | `/api/admin/standby` | Put Standby | право `settings.runtime.write` |
| `POST` | `/api/admin/standby/token` | New Token | право `settings.runtime.write` |
| `GET` | `/api/admin/status-page` | Admin View | право `ops.diagnostics` |
| `PUT` | `/api/admin/status-page/config` | Admin Config | право `ops.incidents` |
| `GET` | `/api/admin/status/components` | Admin Status Components | право `ops.diagnostics` |
| `POST` | `/api/admin/status/components` | Admin Status Component Create | право `ops.diagnostics` |
| `PUT` | `/api/admin/status/components/{component_id}` | Admin Status Component Update | право `ops.diagnostics` |
| `GET` | `/api/admin/sub-proxy` | Get Proxy | право `ops.diagnostics` |
| `PUT` | `/api/admin/sub-proxy` | Put Proxy | право `settings.runtime.write` |
| `GET` | `/api/admin/sub-proxy/apps` | Apps Seen | право `ops.diagnostics` |
| `POST` | `/api/admin/sub-proxy/blocked` | Block Device | право `users.write` |
| `DELETE` | `/api/admin/sub-proxy/blocked/{hwid}` | Unblock Device | право `users.write` |
| `GET` | `/api/admin/sub-proxy/clients` | Get Clients | право `ops.diagnostics` |
| `PUT` | `/api/admin/sub-proxy/clients` | Put Clients | право `settings.runtime.write` |
| `POST` | `/api/admin/sub-proxy/clients/refresh` | Refresh Clients | право `settings.runtime.write` |
| `GET` | `/api/admin/sub-proxy/log` | Request Log | право `ops.diagnostics` |
| `POST` | `/api/admin/sub-proxy/portal-preview` | Portal Preview | право `ops.diagnostics` |
| `GET` | `/api/admin/sub-proxy/portal-texts` | Portal Texts | право `ops.diagnostics` |
| `POST` | `/api/admin/sub-proxy/reset-link/{subscription_id}` | Reset Link | право `users.write` |
| `GET` | `/api/admin/subscription-feed` | Subscription Feed | право `read` |
| `GET` | `/api/admin/subscription-operations` | Admin Operations | право `payments.read` |
| `POST` | `/api/admin/subscription-operations/{operation_id}/refund` | Refund Change | право `payments.refund` |
| `POST` | `/api/admin/support-pro/sso` | Support Pro Sso | право `support.read` |
| `GET` | `/api/admin/support-pro/status` | Support Pro Status | право `support.read` |
| `GET` | `/api/admin/support/ai` | Support Ai Settings | право `support.read` |
| `PUT` | `/api/admin/support/ai` | Save Support Ai | право `support.write` |
| `DELETE` | `/api/admin/support/attachments/{attachment_id}` | Admin Remove | право `support.write` |
| `GET` | `/api/admin/support/attachments/{attachment_id}` | Admin Download | право `support.read` |
| `GET` | `/api/admin/support/autoreply` | Get Autoreply | право `support.read` |
| `PUT` | `/api/admin/support/autoreply` | Put Autoreply | право `support.write` |
| `GET` | `/api/admin/support/tickets` | Admin Tickets | право `support.read` |
| `POST` | `/api/admin/support/tickets/{ticket_id}/attachments` | Admin Upload | право `support.write` |
| `GET` | `/api/admin/support/tickets/{ticket_id}/attachments/drafts` | Admin Drafts | право `support.write` |
| `POST` | `/api/admin/support/tickets/{ticket_id}/draft` | Support Draft | право `support.write` |
| `GET` | `/api/admin/support/tickets/{ticket_id}/messages` | Admin Support Messages | право `support.read` |
| `POST` | `/api/admin/support/tickets/{ticket_id}/reply` | Admin Ticket Reply | право `support.write` |
| `POST` | `/api/admin/support/topology/apply` | Apply | право `support.write` |
| `POST` | `/api/admin/support/topology/preview` | Preview | право `support.write` |
| `GET` | `/api/admin/surveys` | Admin List | право `marketing.read` |
| `POST` | `/api/admin/surveys` | Create | право `manage_marketing` |
| `DELETE` | `/api/admin/surveys/{survey_id}` | Delete Draft | право `manage_marketing` |
| `PUT` | `/api/admin/surveys/{survey_id}` | Edit | право `manage_marketing` |
| `POST` | `/api/admin/surveys/{survey_id}/close` | Close | право `manage_marketing` |
| `POST` | `/api/admin/surveys/{survey_id}/publish` | Publish | право `manage_marketing` |
| `GET` | `/api/admin/surveys/{survey_id}/responses` | Responses | право `manage_marketing` |
| `GET` | `/api/admin/system/health` | System Health | право `read` |
| `GET` | `/api/admin/tariff-constructors` | Admin Constructors | право `manage_plans` |
| `POST` | `/api/admin/tariff-constructors` | Admin Constructor Create | право `manage_plans` |
| `DELETE` | `/api/admin/tariff-constructors/{constructor_id}` | Admin Constructor Delete | право `manage_plans` |
| `PUT` | `/api/admin/tariff-constructors/{constructor_id}` | Admin Constructor Update | право `manage_plans` |
| `POST` | `/api/admin/telegram/check` | Check | право `settings.runtime.read` |
| `GET` | `/api/admin/telegram/commands` | Get Commands | право `settings.runtime.read` |
| `PUT` | `/api/admin/telegram/commands` | Put Commands | право `manage_content` |
| `GET` | `/api/admin/telegram/errors` | Errors | право `ops.diagnostics` |
| `GET` | `/api/admin/telegram/status` | Status | право `settings.runtime.read` |
| `POST` | `/api/admin/telegram/test-message` | Test Message | право `manage_broadcasts` |
| `GET` | `/api/admin/telegram/texts` | Get Texts | право `settings.runtime.read` |
| `PUT` | `/api/admin/telegram/texts` | Put Texts | право `manage_content` |
| `POST` | `/api/admin/telegram/webhook/delete` | Delete Webhook | право `manage_content` |
| `GET` | `/api/admin/terminal` | Admin Terminal | право `nodes.terminal` |
| `POST` | `/api/admin/terminal/sessions` | Admin Terminal Start | право `nodes.terminal` |
| `POST` | `/api/admin/terminal/sessions/{sid}/close` | Admin Terminal Close | право `nodes.terminal` |
| `POST` | `/api/admin/terminal/sessions/{sid}/input` | Admin Terminal Input | право `nodes.terminal` |
| `GET` | `/api/admin/terminal/sessions/{sid}/output` | Admin Terminal Output | право (проверяет обработчик) |
| `GET` | `/api/admin/terminal/sessions/{sid}/transcript` | Admin Terminal Transcript | право `nodes.terminal` |
| `POST` | `/api/admin/terminal/snippets` | Admin Snippet Create | право `nodes.terminal` |
| `POST` | `/api/admin/terminal/snippets/{snippet_id}/delete` | Admin Snippet Delete | право `nodes.terminal` |
| `GET` | `/api/admin/traffic-packages` | Admin Packages | право `read` |
| `POST` | `/api/admin/traffic-packages` | Create Package | право `manage_plans` |
| `PUT` | `/api/admin/traffic-packages/{package_id}` | Edit Package | право `manage_plans` |
| `GET` | `/api/admin/users/{user_id}/activity` | User Activity | право `users.read` |
| `POST` | `/api/admin/users/{user_id}/drop-connections` | Drop Connections | право `users.write` |
| `GET` | `/api/admin/users/{user_id}/online` | Online Now | право `users.read` |
| `GET` | `/api/admin/users/{user_id}/sessions` | User Sessions | право `users.read` |
| `GET` | `/api/admin/users/{user_id}/traffic` | Admin Traffic | право `users.read` |
| `POST` | `/api/admin/v15/deployments/{deployment_id}/rollback` | Rollback | право `security.manage` |
| `GET` | `/api/admin/v15/operations` | Operations | право `read` |
| `POST` | `/api/admin/v16/nodes/register` | Register Node | право `provision_nodes` |
| `POST` | `/api/admin/v16/nodes/{node_name}/failover` | Node Failover | право `provision_nodes` |
| `GET` | `/api/admin/v3/automation` | Admin Automation | право `read` |
| `POST` | `/api/admin/v3/automation/{rule_id}/toggle` | Toggle Automation | право `manage_users` |
| `GET` | `/api/admin/v3/control-center` | Control Center | право `read` |
| `GET` | `/api/admin/v3/devices` | Admin Devices | право `read` |
| `GET` | `/api/admin/v3/routing` | Get Routing | право `read` |
| `PUT` | `/api/admin/v3/routing` | Put Routing | право `manage_users` |
| `GET` | `/api/admin/v41/analytics` | V41 Analytics | право `analytics.read` |
| `GET` | `/api/admin/v41/backups/verification` | V41 Backup Verification List | право `ops.backups.verify` |
| `POST` | `/api/admin/v41/backups/{backup_id}/test-restore` | V41 Backup Test Restore | право `ops.backups.verify` |
| `GET` | `/api/admin/v41/crm/users` | V41 Crm Users | право `users.read` |
| `GET` | `/api/admin/v41/diagnostics` | V41 Diagnostics | право `ops.diagnostics` |
| `GET` | `/api/admin/v41/features` | V41 Features | право `read` |
| `PUT` | `/api/admin/v41/features/{key}` | V41 Feature Update | право `feature_flags.manage` |
| `GET` | `/api/admin/v41/incidents` | V41 Incidents | право `ops.incidents` |
| `POST` | `/api/admin/v41/incidents` | V41 Incident Create | право `ops.incidents` |
| `POST` | `/api/admin/v41/incidents/{incident_id}/resolve` | V41 Incident Resolve | право `ops.incidents` |
| `GET` | `/api/admin/v41/passkeys` | V41 Passkeys | право `security.passkeys` |
| `DELETE` | `/api/admin/v41/passkeys/{credential_id}` | V41 Passkey Delete | право `security.passkeys` |
| `GET` | `/api/admin/v41/promotions` | V41 Promotions | право `marketing.read` |
| `GET` | `/api/admin/v41/providers` | V41 Providers | право `ops.providers` |
| `PUT` | `/api/admin/v41/providers/{provider}` | V41 Provider Update | право `ops.providers` |
| `POST` | `/api/admin/v41/providers/{provider}/reset` | V41 Provider Reset | право `ops.providers` |
| `GET` | `/api/admin/v41/referrals` | V41 Referrals | право `referrals.read` |
| `GET` | `/api/admin/v6/capacity` | Capacity | право `read` |
| `GET` | `/api/admin/v6/command-center` | Command Center | право `read` |
| `GET` | `/api/admin/v6/commercial` | Commercial | право `read` |
| `GET` | `/api/admin/v6/config/{section}` | Get Config | право `read` |
| `PUT` | `/api/admin/v6/config/{section}` | Put Config | право `security.manage` |
| `GET` | `/api/admin/v6/events` | Events | право `read` |
| `GET` | `/api/admin/v6/integrations` | Integrations | право `read` |
| `GET` | `/api/admin/v6/intelligence` | Intelligence | право `read` |
| `POST` | `/api/admin/v6/orchestrator/evaluate` | Orchestrate | право `provision_nodes` |
| `POST` | `/api/admin/v6/provision` | Provision | право `provision_nodes` |
| `GET` | `/api/admin/v6/security-center` | Security Center | право `read` |
| `GET` | `/api/admin/webhooks/tee` | Get Tee | право `ops.diagnostics` |
| `PUT` | `/api/admin/webhooks/tee` | Put Tee | право `settings.runtime.write` |
| `POST` | `/api/admin/webhooks/tee/test` | Test Tee | право `settings.runtime.write` |
| `GET` | `/api/admin/wg-pool` | Get Pool | право `provision_nodes` |
| `PUT` | `/api/admin/wg-pool` | Put Pool | право `provision_nodes` |
| `DELETE` | `/api/admin/wg-pool/free` | Drop Free | право `provision_nodes` |
| `POST` | `/api/admin/wg-pool/upload` | Upload | право `provision_nodes` |
| `GET` | `/api/admin/workers` | Admin Workers | право `read` |
| `POST` | `/api/agent/heartbeat` | Agent Heartbeat | токен агента ноды |
| `POST` | `/api/agent/observations` | Agent Observations | токен агента ноды |
| `GET` | `/api/agent/terminal/pending` | Agent Terminal Pending | токен агента ноды |
| `GET` | `/api/agent/terminal/{sid}/input` | Agent Terminal Input | токен агента ноды |
| `POST` | `/api/agent/terminal/{sid}/output` | Agent Terminal Output | токен агента ноды |
| `POST` | `/api/agent/torrent` | Agent Torrent | токен агента ноды |
| `GET` | `/api/app-config` | App Config | открытый |
| `GET` | `/api/app/open` | Open App | открытый |
| `GET` | `/api/app/paid` | Paid Return | открытый |
| `POST` | `/api/auth/email/verification/confirm` | Confirm Verification | вход клиента |
| `POST` | `/api/auth/exchange` | Auth Exchange | вход клиента |
| `GET` | `/api/auth/google` | Google Login | вход клиента |
| `GET` | `/api/auth/google/callback` | Google Callback | вход клиента |
| `POST` | `/api/auth/guest` | Guest Start | вход клиента |
| `POST` | `/api/auth/guest/setup` | Guest Setup | вход клиента |
| `POST` | `/api/auth/login` | Auth Login | вход клиента |
| `POST` | `/api/auth/logout` | User Logout | вход клиента |
| `POST` | `/api/auth/mobile/code` | Redeem App Code | вход клиента |
| `POST` | `/api/auth/mobile/token` | Mobile Token | вход клиента |
| `GET` | `/api/auth/passkeys` | Inventory | вход клиента |
| `POST` | `/api/auth/passkeys/login/options` | Login Options | вход клиента |
| `POST` | `/api/auth/passkeys/login/verify` | Login Verify | вход клиента |
| `POST` | `/api/auth/passkeys/registration/options` | Registration Options | вход клиента |
| `POST` | `/api/auth/passkeys/registration/verify` | Registration Verify | вход клиента |
| `POST` | `/api/auth/passkeys/{credential_id}/delete` | Remove | вход клиента |
| `POST` | `/api/auth/password/reset/confirm` | Confirm Reset | вход клиента |
| `POST` | `/api/auth/password/reset/request` | Request Reset | вход клиента |
| `POST` | `/api/auth/register` | Auth Register | вход клиента |
| `POST` | `/api/auth/telegram` | Telegram Auth | вход клиента |
| `GET` | `/api/auth/vk` | Vk Login | вход клиента |
| `GET` | `/api/auth/vk/callback` | Vk Callback | вход клиента |
| `GET` | `/api/auth/yandex` | Yandex Login | вход клиента |
| `GET` | `/api/auth/yandex/callback` | Yandex Callback | вход клиента |
| `GET` | `/api/bot/banners/default/{name}` | Default Banner | открытый |
| `POST` | `/api/internal/staging-e2e/payment` | Internal Staging Payment | служебный токен |
| `POST` | `/api/internal/staging-e2e/refund` | Internal Staging Refund | служебный токен |
| `POST` | `/api/internal/staging-e2e/refund-status` | Internal Staging Refund Status | служебный токен |
| `POST` | `/api/internal/staging-e2e/remnawave` | Internal Staging Remnawave | служебный токен |
| `POST` | `/api/internal/staging-e2e/verify` | Internal Staging Verify | служебный токен |
| `GET` | `/api/internal/support-bridge/attachments/{attachment_id}` | Attachment | служебный токен |
| `POST` | `/api/internal/support-bridge/imports/{source_id}` | Import Ticket | служебный токен |
| `POST` | `/api/internal/support-bridge/imports/{source_id}/attachments` | Import Attachment | служебный токен |
| `POST` | `/api/internal/support-bridge/imports/{source_id}/complete` | Complete Import | служебный токен |
| `POST` | `/api/internal/support-bridge/imports/{source_id}/messages` | Import Message | служебный токен |
| `GET` | `/api/internal/support-bridge/tickets` | Tickets | служебный токен |
| `GET` | `/api/internal/support-bridge/tickets/recent` | Recent | служебный токен |
| `POST` | `/api/internal/support-bridge/tickets/{ticket_id}/attachments` | Add Attachment | служебный токен |
| `POST` | `/api/internal/support-bridge/tickets/{ticket_id}/customer-message` | Customer Message | служебный токен |
| `GET` | `/api/internal/support-bridge/tickets/{ticket_id}/messages` | Messages | служебный токен |
| `POST` | `/api/internal/support-bridge/tickets/{ticket_id}/reply` | Reply | служебный токен |
| `POST` | `/api/internal/support-bridge/tickets/{ticket_id}/status` | Status | служебный токен |
| `GET` | `/api/masque/sub/{value}` | Subscription | открытый |
| `GET` | `/api/me` | Api Me | сессия клиента |
| `POST` | `/api/me/account-merge/authorization` | Create Authorization | сессия клиента |
| `POST` | `/api/me/account-merge/confirm` | Confirm Merge | сессия клиента |
| `POST` | `/api/me/account-merge/preview` | Preview Merge | сессия клиента |
| `POST` | `/api/me/activity` | My Activity | сессия клиента |
| `POST` | `/api/me/app-login` | Create App Login | сессия клиента |
| `GET` | `/api/me/auto-renew` | Auto Renew Status | сессия клиента |
| `PUT` | `/api/me/auto-renew` | Set Auto Renew | сессия клиента |
| `DELETE` | `/api/me/auto-renew/method` | Remove Auto Renew Method | сессия клиента |
| `GET` | `/api/me/avatar` | My Avatar | сессия клиента |
| `GET` | `/api/me/billing-center` | Billing Center | сессия клиента |
| `DELETE` | `/api/me/cart` | Delete Cart | сессия клиента |
| `GET` | `/api/me/cart` | Get Cart | сессия клиента |
| `POST` | `/api/me/cart` | Put Cart | сессия клиента |
| `GET` | `/api/me/channels` | My Channels | сессия клиента |
| `GET` | `/api/me/company` | My Company | сессия клиента |
| `POST` | `/api/me/company/invite` | Rotate Invite | сессия клиента |
| `GET` | `/api/me/company/invoices/{invoice_id}.html` | My Invoice | сессия клиента |
| `POST` | `/api/me/company/join` | Join | сессия клиента |
| `DELETE` | `/api/me/company/members/{member_id}` | Remove | сессия клиента |
| `PUT` | `/api/me/company/members/{member_id}` | Set Devices | сессия клиента |
| `GET` | `/api/me/connection-info` | Connection Info | сессия клиента |
| `GET` | `/api/me/connection-qr` | Connection Qr | сессия клиента |
| `POST` | `/api/me/connection-reports` | Report | сессия клиента |
| `GET` | `/api/me/consent` | My Consent | сессия клиента |
| `POST` | `/api/me/consent` | Accept Consent | сессия клиента |
| `GET` | `/api/me/dashboard` | Customer Dashboard | сессия клиента |
| `GET` | `/api/me/devices` | My Devices | сессия клиента |
| `POST` | `/api/me/devices` | Register Device | сессия клиента |
| `POST` | `/api/me/devices/transfer` | Device Transfer | сессия клиента |
| `POST` | `/api/me/devices/{device_id}/revoke` | Revoke Device | сессия клиента |
| `POST` | `/api/me/diagnostics` | My Diagnostics | сессия клиента |
| `GET` | `/api/me/email` | Email Status | сессия клиента |
| `POST` | `/api/me/email/verification/request` | Request Verification | сессия клиента |
| `GET` | `/api/me/family` | My Family | сессия клиента |
| `POST` | `/api/me/family/join` | Family Join | сессия клиента |
| `DELETE` | `/api/me/family/members/{member_id}` | Family Remove | сессия клиента |
| `PUT` | `/api/me/family/members/{member_id}/filter` | Put Member Filter | сессия клиента |
| `POST` | `/api/me/family/{subscription_id}/invite` | Family Invite | сессия клиента |
| `GET` | `/api/me/feedback` | My Feedback | сессия клиента |
| `POST` | `/api/me/feedback/csat` | Rate Ticket | сессия клиента |
| `POST` | `/api/me/feedback/nps` | Rate Shop | сессия клиента |
| `GET` | `/api/me/filter` | My Filter | сессия клиента |
| `PUT` | `/api/me/filter` | Put My Filter | сессия клиента |
| `GET` | `/api/me/freeze` | My Freeze | сессия клиента |
| `POST` | `/api/me/freeze` | Freeze Mine | сессия клиента |
| `POST` | `/api/me/freeze/thaw` | Thaw Mine | сессия клиента |
| `GET` | `/api/me/gifts` | Purchased Gifts | сессия клиента |
| `POST` | `/api/me/gifts/purchase` | Purchase Gift | сессия клиента |
| `POST` | `/api/me/gifts/redeem` | Redeem Gift | сессия клиента |
| `GET` | `/api/me/giveaways` | Customer List | сессия клиента |
| `POST` | `/api/me/giveaways/{giveaway_id}/enter` | Enter | сессия клиента |
| `GET` | `/api/me/hwid-devices` | My Hwid Devices | сессия клиента |
| `POST` | `/api/me/hwid-devices/reset` | Reset My Hwid Devices | сессия клиента |
| `POST` | `/api/me/hwid-devices/{dev}/delete` | Delete My Hwid Device | сессия клиента |
| `GET` | `/api/me/identity` | Identity | сессия клиента |
| `GET` | `/api/me/loyalty` | My Loyalty | сессия клиента |
| `POST` | `/api/me/lusi/action` | Lusi Action | сессия клиента |
| `GET` | `/api/me/masque` | My Masque | сессия клиента |
| `GET` | `/api/me/mobile/alerts` | Mobile Alerts | сессия клиента |
| `GET` | `/api/me/mobile/bootstrap` | Mobile Bootstrap | сессия клиента |
| `GET` | `/api/me/mobile/connection` | Mobile Connection | сессия клиента |
| `GET` | `/api/me/mobile/diagnostics` | Mobile Diagnostics | сессия клиента |
| `GET` | `/api/me/mobile/features` | Mobile Features | сессия клиента |
| `GET` | `/api/me/mobile/notifications` | Mobile Notifications | сессия клиента |
| `POST` | `/api/me/mobile/notifications/{notification_id}/read` | Mobile Notification Read | сессия клиента |
| `GET` | `/api/me/mobile/privacy` | Mobile Privacy | сессия клиента |
| `GET` | `/api/me/notifications` | My Notifications | сессия клиента |
| `POST` | `/api/me/notifications/{notification_id}/read` | Read Notification | сессия клиента |
| `GET` | `/api/me/offers` | Offers | сессия клиента |
| `GET` | `/api/me/partner` | Portal | сессия клиента |
| `POST` | `/api/me/partner/withdrawals` | Withdraw | сессия клиента |
| `POST` | `/api/me/password/change` | Change Password | сессия клиента |
| `POST` | `/api/me/payment/gift-card/redeem` | Redeem Gift Card | сессия клиента |
| `PUT` | `/api/me/payment/tax-profile` | Set Tax Profile | сессия клиента |
| `GET` | `/api/me/payments` | My Payments | сессия клиента |
| `GET` | `/api/me/payments/order/{order_id}` | My Payment By Order | сессия клиента |
| `GET` | `/api/me/payments/{payment_id}/invoice` | Payment Invoice | сессия клиента |
| `PUT` | `/api/me/preferences/language` | Set Language | сессия клиента |
| `DELETE` | `/api/me/privacy/account` | Privacy Delete | сессия клиента |
| `GET` | `/api/me/privacy/export` | Privacy Export | сессия клиента |
| `GET` | `/api/me/profile` | My Profile | сессия клиента |
| `PATCH` | `/api/me/profile` | Update Profile | сессия клиента |
| `GET` | `/api/me/push/devices` | List Devices | сессия клиента |
| `POST` | `/api/me/push/devices` | Register Device | сессия клиента |
| `POST` | `/api/me/push/devices/unregister` | Unregister Device | сессия клиента |
| `DELETE` | `/api/me/push/devices/{device_id}` | Delete Device | сессия клиента |
| `POST` | `/api/me/push/test` | Test Push | сессия клиента |
| `GET` | `/api/me/receipts` | My Receipts | сессия клиента |
| `GET` | `/api/me/recommended-server` | Recommended | сессия клиента |
| `GET` | `/api/me/referral` | My Referral | сессия клиента |
| `GET` | `/api/me/referral-contest` | My Contest | сессия клиента |
| `POST` | `/api/me/referral/apply` | Apply Referral | сессия клиента |
| `GET` | `/api/me/referral/ledger` | My Referral Ledger | сессия клиента |
| `GET` | `/api/me/referral/network` | My Network | сессия клиента |
| `GET` | `/api/me/referral/withdrawals` | My Withdrawals | сессия клиента |
| `POST` | `/api/me/referral/withdrawals` | Request Withdrawal | сессия клиента |
| `GET` | `/api/me/region` | My Region | сессия клиента |
| `GET` | `/api/me/remnawave/subscription` | My Remnawave Subscription | сессия клиента |
| `POST` | `/api/me/remnawave/subscription/refresh` | Refresh My Remnawave Subscription | сессия клиента |
| `GET` | `/api/me/routing/recommendation` | Routing Recommendation | сессия клиента |
| `GET` | `/api/me/security-center` | Security Center | сессия клиента |
| `POST` | `/api/me/security/revoke-all` | Revoke All User Sessions | сессия клиента |
| `GET` | `/api/me/servers` | My Servers | сессия клиента |
| `GET` | `/api/me/sessions` | My Sessions | сессия клиента |
| `POST` | `/api/me/sessions/{session_id}/revoke` | Revoke Session | сессия клиента |
| `POST` | `/api/me/source` | My Source | сессия клиента |
| `POST` | `/api/me/speedtest` | Speed Report | сессия клиента |
| `GET` | `/api/me/speedtest/blob` | Speed Blob | сессия клиента |
| `GET` | `/api/me/speedtest/ping` | Speed Ping | сессия клиента |
| `GET` | `/api/me/stars-subscriptions` | My Stars Subscriptions | сессия клиента |
| `POST` | `/api/me/stars-subscriptions` | Create Stars Subscription | сессия клиента |
| `POST` | `/api/me/stars-subscriptions/{row_id}/cancel` | Cancel Stars Subscription | сессия клиента |
| `GET` | `/api/me/stats` | My Stats | сессия клиента |
| `DELETE` | `/api/me/status/subscription` | Unsubscribe | сессия клиента |
| `GET` | `/api/me/status/subscription` | My Subscription | сессия клиента |
| `POST` | `/api/me/status/subscription` | Subscribe | сессия клиента |
| `GET` | `/api/me/subscription` | My Subscription | сессия клиента |
| `GET` | `/api/me/subscription-file` | Subscription File | сессия клиента |
| `GET` | `/api/me/subscription/commerce` | Commerce Catalog | сессия клиента |
| `GET` | `/api/me/subscription/keys` | My Keys | сессия клиента |
| `GET` | `/api/me/subscription/keys/{index}/qr` | My Key Qr | сессия клиента |
| `POST` | `/api/me/subscription/lifecycle` | Subscription Lifecycle | сессия клиента |
| `GET` | `/api/me/subscription/operations` | Commerce History | сессия клиента |
| `POST` | `/api/me/subscription/purchase` | Purchase Change | сессия клиента |
| `POST` | `/api/me/subscription/quote` | Quote Change | сессия клиента |
| `POST` | `/api/me/subscription/reset-link` | Reset My Subscription Link | сессия клиента |
| `GET` | `/api/me/subscriptions` | List Subscriptions | сессия клиента |
| `PUT` | `/api/me/subscriptions/{subscription_id}` | Rename Subscription | сессия клиента |
| `POST` | `/api/me/subscriptions/{subscription_id}/select` | Select Subscription | сессия клиента |
| `DELETE` | `/api/me/support/attachments/{attachment_id}` | Customer Remove | сессия клиента |
| `GET` | `/api/me/support/attachments/{attachment_id}` | Customer Download | сессия клиента |
| `GET` | `/api/me/support/tickets` | My Support Tickets | сессия клиента |
| `POST` | `/api/me/support/tickets` | Create Support Ticket | сессия клиента |
| `POST` | `/api/me/support/tickets/{ticket_id}/attachments` | Customer Upload | сессия клиента |
| `GET` | `/api/me/support/tickets/{ticket_id}/attachments/drafts` | Customer Drafts | сессия клиента |
| `GET` | `/api/me/support/tickets/{ticket_id}/messages` | Customer Support Messages | сессия клиента |
| `POST` | `/api/me/support/tickets/{ticket_id}/messages` | Customer Support Reply | сессия клиента |
| `GET` | `/api/me/surveys` | Customer List | сессия клиента |
| `GET` | `/api/me/surveys/{survey_id}` | Customer Detail | сессия клиента |
| `POST` | `/api/me/surveys/{survey_id}/submit` | Submit | сессия клиента |
| `GET` | `/api/me/sync` | My Sync | сессия клиента |
| `GET` | `/api/me/traffic` | My Traffic | сессия клиента |
| `POST` | `/api/me/trial` | Claim Trial | сессия клиента |
| `GET` | `/api/me/upsell` | My Upsell | сессия клиента |
| `GET` | `/api/me/v15/bootstrap` | V15 Bootstrap | сессия клиента |
| `POST` | `/api/me/v16/roaming` | Roaming | сессия клиента |
| `POST` | `/api/me/v16/tunnel-profile` | Tunnel Profile | сессия клиента |
| `GET` | `/api/me/wallet/history` | Wallet History | сессия клиента |
| `POST` | `/api/me/wallet/spend` | Wallet Spend | сессия клиента |
| `POST` | `/api/me/wallet/stars-invoice` | Stars Invoice | сессия клиента |
| `POST` | `/api/me/wallet/topup` | Wallet Topup | сессия клиента |
| `GET` | `/api/me/wallet/tribute` | My Tribute Link | сессия клиента |
| `GET` | `/api/me/wg-config` | My Wg | сессия клиента |
| `GET` | `/api/me/wg-config/qr` | My Wg Qr | сессия клиента |
| `GET` | `/api/me/wg-configs` | My Wg List | сессия клиента |
| `DELETE` | `/api/me/wg-configs/{config_id}` | My Wg Release | сессия клиента |
| `GET` | `/api/me/widget` | Widget Summary | сессия клиента |
| `POST` | `/api/mobile/events` | Collect Events | сессия клиента |
| `POST` | `/api/mobile/integrity/challenge` | Integrity Challenge | открытый |
| `GET` | `/api/mobile/layout` | Mobile Layout | открытый |
| `GET` | `/api/mobile/push-style` | Public Push Style | открытый |
| `GET` | `/api/panel-gate/redeem` | Redeem | открытый |
| `GET` | `/api/panel-gate/verify` | Verify | открытый |
| `POST` | `/api/payments/create` | Create Payment | сессия клиента |
| `POST` | `/api/payments/mobile/verify` | Verify Mobile Purchase | сессия клиента |
| `GET` | `/api/payments/providers` | Payment Providers | открытый |
| `POST` | `/api/payments/sandbox/complete` | Sandbox Complete | сессия клиента |
| `POST` | `/api/payments/webhooks/paypal` | Paypal Webhook | подпись провайдера |
| `POST` | `/api/payments/webhooks/stripe` | Stripe Webhook | подпись провайдера |
| `GET` | `/api/plans` | Plans | открытый |
| `GET` | `/api/plugin/v1/me` | Plugin Me | ключ плагина |
| `POST` | `/api/plugin/v1/notifications` | Plugin Notify | ключ плагина |
| `GET` | `/api/plugin/v1/payments/{payment_id}` | Plugin Payment | ключ плагина |
| `GET` | `/api/plugin/v1/users/{user_id}` | Plugin User | ключ плагина |
| `GET` | `/api/plugin/v1/users/{user_id}/subscriptions` | Plugin Subscriptions | ключ плагина |
| `POST` | `/api/probe/report` | Probe Report | токен пробы |
| `GET` | `/api/probe/targets` | Probe Targets | токен пробы |
| `GET` | `/api/promo/validate` | Validate Promo | сессия клиента |
| `GET` | `/api/public/app-login/methods` | Public Login Methods | открытый |
| `GET` | `/api/public/apps` | Public Apps | открытый |
| `GET` | `/api/public/apps/install` | Public Install Guide | открытый |
| `GET` | `/api/public/apps/{app_id}/download` | Public App Download | открытый |
| `GET` | `/api/public/branding` | Public Branding | открытый |
| `GET` | `/api/public/cabinet-menu` | Public Cabinet Menu | открытый |
| `GET` | `/api/public/cabinet-texts` | Public Texts | открытый |
| `GET` | `/api/public/config` | Public Config | открытый |
| `GET` | `/api/public/guest-checkout` | Public Guest | открытый |
| `GET` | `/api/public/info-pages` | Public List | открытый |
| `GET` | `/api/public/info-pages/{kind}` | Public Page | открытый |
| `GET` | `/api/public/menu-emoji/{emoji_id}` | Menu Emoji | открытый |
| `GET` | `/api/public/mirrors` | Public Mirrors | открытый |
| `GET` | `/api/public/pages` | Catalog | открытый |
| `GET` | `/api/public/pages/{slug}` | Public Page | открытый |
| `GET` | `/api/public/servers` | Public Servers | открытый |
| `GET` | `/api/public/service-status` | Public Status | открытый |
| `GET` | `/api/public/status` | Public Status | открытый |
| `GET` | `/api/public/status-page` | Public Status Page | открытый |
| `GET` | `/api/public/trial` | Public Trial | открытый |
| `GET` | `/api/public/v15/privacy` | Public Privacy | открытый |
| `GET` | `/api/public/v16/release` | Release | открытый |
| `GET` | `/api/public/v6/status` | Public Status | открытый |
| `GET` | `/api/reseller/branding` | Reseller Branding | ключ партнёра |
| `GET` | `/api/reseller/catalog` | Reseller Catalog | ключ партнёра |
| `POST` | `/api/reseller/orders` | Create Order | ключ партнёра |
| `GET` | `/api/reseller/orders/{order_id}` | Get Order | ключ партнёра |
| `GET` | `/api/reseller/stats` | Reseller Stats | ключ партнёра |
| `POST` | `/api/standby/heartbeat` | Heartbeat | токен резерва |
| `GET` | `/api/tariff-constructors` | Public Constructors | открытый |
| `GET` | `/api/v3/status` | V3 Status | открытый |
| `POST` | `/api/webhooks/anore` | Anore Webhook | подпись провайдера |
| `POST` | `/api/webhooks/antilopay` | Antilopay Webhook | подпись провайдера |
| `POST` | `/api/webhooks/app-store` | App Store Notification | подпись провайдера |
| `POST` | `/api/webhooks/aurapay` | Aurapay Webhook | подпись провайдера |
| `POST` | `/api/webhooks/cashera` | Cashera Webhook | подпись провайдера |
| `POST` | `/api/webhooks/cloudpayments` | Cloudpayments Webhook | подпись провайдера |
| `POST` | `/api/webhooks/crypto` | Crypto Webhook | подпись провайдера |
| `POST` | `/api/webhooks/cryptobot` | Cryptobot Webhook | подпись провайдера |
| `GET` | `/api/webhooks/freekassa` | Freekassa Webhook | подпись провайдера |
| `POST` | `/api/webhooks/freekassa` | Freekassa Webhook | подпись провайдера |
| `POST` | `/api/webhooks/google-play` | Google Play Notification | подпись провайдера |
| `POST` | `/api/webhooks/lava` | Lava Webhook | подпись провайдера |
| `POST` | `/api/webhooks/mulenpay` | Mulenpay Webhook | подпись провайдера |
| `POST` | `/api/webhooks/pal24` | Pal24 Webhook | подпись провайдера |
| `POST` | `/api/webhooks/paritypay` | Paritypay Webhook | подпись провайдера |
| `POST` | `/api/webhooks/platega` | Platega Webhook | подпись провайдера |
| `POST` | `/api/webhooks/remnawave` | Remnawave Webhook | подпись провайдера |
| `POST` | `/api/webhooks/rollypay` | Rollypay Webhook | подпись провайдера |
| `POST` | `/api/webhooks/tribute` | Tribute Webhook | подпись провайдера |
| `POST` | `/api/webhooks/wata` | Wata Webhook | подпись провайдера |
| `POST` | `/api/webhooks/yookassa` | Yookassa Webhook | подпись провайдера |
| `GET` | `/health` | Health | открытый |
| `GET` | `/health/live` | Health Live | открытый |
| `GET` | `/health/ready` | Health Ready | открытый |
| `GET` | `/metrics` | Metrics | токен `X-Metrics-Token` |
| `GET` | `/status` | Status Html | открытый |
