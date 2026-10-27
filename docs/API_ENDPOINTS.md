# Каталог API — v28.36.0 / API v21.5.1

Сгенерирован из OpenAPI текущих исходников. Миграция: `0079_acquisition`.
Авторизация, права, CSRF и принадлежность записей проверяются сервером; схема маршрута не заменяет права роли.
Сценарии: [руководство](ru/WORKSPACE_USER_GUIDE.md), [рефералы](ru/REFERRALS_CURRENT.md), [HTTP API](../API_REFERENCE_RU.md).

Legacy callbacks прежних агентов служат историческим операциям. Новые покупки используют YooKassa/Platega/RollyPay;
production gate остаётся закрытым без полного application E2E. Mobile purchase verify закрыт ответом 410.

Обновление: `PYTHONPATH=backend python scripts/generate-api-docs.py`; проверка: добавьте `--check`.

| Метод | Путь | Операция |
| --- | --- | --- |
| `GET` | `/.well-known/apple-app-site-association` | Apple App Site Association |
| `GET` | `/.well-known/assetlinks.json` | Assetlinks |
| `GET` | `/api/admin/admins` | List Admins |
| `POST` | `/api/admin/admins` | Create Admin |
| `DELETE` | `/api/admin/admins/{admin_id}` | Delete Admin |
| `PUT` | `/api/admin/admins/{admin_id}` | Update Admin |
| `POST` | `/api/admin/advertisements` | Create Ad |
| `DELETE` | `/api/admin/advertisements/{item_id}` | Delete Ad |
| `PUT` | `/api/admin/advertisements/{item_id}` | Update Ad |
| `GET` | `/api/admin/analytics` | Admin Analytics |
| `GET` | `/api/admin/analytics/economics` | Economics |
| `PUT` | `/api/admin/analytics/economics/spend` | Put Spend |
| `GET` | `/api/admin/analytics/retention` | Retention |
| `GET` | `/api/admin/anti-sharing` | Get Anti Sharing |
| `PUT` | `/api/admin/anti-sharing` | Put Anti Sharing |
| `GET` | `/api/admin/app-analytics` | Admin Analytics |
| `DELETE` | `/api/admin/app-config` | Admin App Config Reset |
| `GET` | `/api/admin/app-config` | Admin App Config |
| `PUT` | `/api/admin/app-config` | Admin App Config Save |
| `GET` | `/api/admin/apps` | Admin Apps |
| `PUT` | `/api/admin/apps` | Save Apps |
| `DELETE` | `/api/admin/apps/logo` | Delete Client Logo |
| `POST` | `/api/admin/apps/logo` | Upload Client Logo |
| `GET` | `/api/admin/apps/{app_id}/download` | Admin App Download |
| `DELETE` | `/api/admin/apps/{app_id}/file` | Delete App File |
| `POST` | `/api/admin/apps/{app_id}/file` | Upload App File |
| `GET` | `/api/admin/audit` | Admin Audit |
| `POST` | `/api/admin/auth/login` | Admin Login |
| `POST` | `/api/admin/auth/logout` | Admin Logout |
| `POST` | `/api/admin/auth/mfa/disable` | Mfa Disable |
| `POST` | `/api/admin/auth/mfa/enable` | Mfa Enable |
| `POST` | `/api/admin/auth/mfa/setup` | Mfa Setup |
| `GET` | `/api/admin/auth/mfa/status` | Mfa Status |
| `POST` | `/api/admin/auth/passkeys/login/options` | Login Options |
| `POST` | `/api/admin/auth/passkeys/login/verify` | Login Verify |
| `POST` | `/api/admin/auth/passkeys/registration/options` | Registration Options |
| `POST` | `/api/admin/auth/passkeys/registration/verify` | Registration Verify |
| `POST` | `/api/admin/auth/telegram` | Admin Telegram Login |
| `POST` | `/api/admin/auth/ticket` | Redeem Web Ticket |
| `POST` | `/api/admin/auth/web-ticket` | Issue Web Ticket |
| `GET` | `/api/admin/auto-update` | Get Auto Update |
| `PUT` | `/api/admin/auto-update` | Put Auto Update |
| `POST` | `/api/admin/auto-update/run` | Run Auto Update |
| `DELETE` | `/api/admin/automation/campaigns/{campaign_id}` | Delete Campaign |
| `GET` | `/api/admin/automation/catalog` | Catalog |
| `POST` | `/api/admin/automation/presets/{preset_id}` | Create Preset |
| `DELETE` | `/api/admin/automation/rules/{rule_id}` | Delete Rule |
| `GET` | `/api/admin/automation/rules/{rule_id}/preview` | Preview |
| `GET` | `/api/admin/backups` | List Backups |
| `GET` | `/api/admin/backups/config` | Backup Config |
| `PUT` | `/api/admin/backups/config` | Update Backup Config |
| `POST` | `/api/admin/backups/run` | Run Backup |
| `GET` | `/api/admin/backups/telegram` | Get Telegram Backup |
| `PUT` | `/api/admin/backups/telegram` | Put Telegram Backup |
| `POST` | `/api/admin/backups/telegram/send-now` | Send Now |
| `DELETE` | `/api/admin/backups/{backup_id}` | Delete Backup |
| `GET` | `/api/admin/backups/{backup_id}/download` | Download Backup |
| `POST` | `/api/admin/backups/{backup_id}/restore` | Restore Backup |
| `POST` | `/api/admin/backups/{backup_id}/restore/approve` | Approve Restore |
| `POST` | `/api/admin/backups/{backup_id}/restore/request` | Request Restore |
| `POST` | `/api/admin/backups/{backup_id}/validate` | Validate Backup Archive |
| `POST` | `/api/admin/backups/{backup_id}/verify` | Verify Backup |
| `GET` | `/api/admin/block-monitor` | Get Monitor |
| `PUT` | `/api/admin/block-monitor` | Put Monitor |
| `POST` | `/api/admin/block-monitor/probes` | Add Probe |
| `DELETE` | `/api/admin/block-monitor/probes/{probe_id}` | Delete Probe |
| `GET` | `/api/admin/bot/banners` | List Banners |
| `PUT` | `/api/admin/bot/banners-enabled` | Banners Enabled |
| `DELETE` | `/api/admin/bot/banners/{key}` | Reset Banner |
| `POST` | `/api/admin/bot/banners/{key}` | Upload Banner |
| `PUT` | `/api/admin/bot/banners/{key}/visibility` | Banner Visibility |
| `DELETE` | `/api/admin/bot/start-image` | Admin Bot Start Image Delete |
| `POST` | `/api/admin/bot/start-image` | Admin Bot Start Image |
| `POST` | `/api/admin/branding/favicon` | Admin Branding Favicon |
| `POST` | `/api/admin/branding/logo` | Admin Branding Logo |
| `DELETE` | `/api/admin/branding/{kind}` | Admin Branding Delete |
| `POST` | `/api/admin/broadcasts` | Create Broadcast |
| `POST` | `/api/admin/broadcasts/{broadcast_id}/retry` | Retry Broadcast |
| `GET` | `/api/admin/cabinet/guides` | Admin Cabinet Guides |
| `PUT` | `/api/admin/cabinet/guides/{platform}` | Admin Cabinet Guide |
| `GET` | `/api/admin/cabinet/menu` | Admin Cabinet Menu |
| `POST` | `/api/admin/cabinet/menu` | Admin Cabinet Menu Create |
| `DELETE` | `/api/admin/cabinet/menu/{item_id}` | Admin Cabinet Menu Delete |
| `PUT` | `/api/admin/cabinet/menu/{item_id}` | Admin Cabinet Menu Update |
| `GET` | `/api/admin/content` | Admin Content |
| `GET` | `/api/admin/corporate-accounts` | List Corporate |
| `POST` | `/api/admin/corporate-accounts` | Create Corporate |
| `POST` | `/api/admin/customer-operations/bulk/apply` | Bulk Apply |
| `POST` | `/api/admin/customer-operations/bulk/preview` | Bulk Preview |
| `GET` | `/api/admin/customer-operations/history` | History Jobs |
| `POST` | `/api/admin/customer-operations/history/inspect` | Inspect |
| `POST` | `/api/admin/customer-operations/history/preview` | Preview |
| `POST` | `/api/admin/customer-operations/history/{job_id}/apply` | Apply |
| `POST` | `/api/admin/customer-operations/history/{job_id}/cancel` | Cancel |
| `POST` | `/api/admin/customer-operations/history/{job_id}/rollback` | Rollback |
| `GET` | `/api/admin/customer-operations/import/history` | Import History |
| `POST` | `/api/admin/customer-operations/import/inspect` | Inspect |
| `POST` | `/api/admin/customer-operations/import/preview` | Import Preview |
| `POST` | `/api/admin/customer-operations/import/{job_id}/apply` | Import Apply |
| `POST` | `/api/admin/customer-operations/import/{job_id}/cancel` | Cancel Import |
| `GET` | `/api/admin/customers/{user_id}/360` | Customer 360 |
| `GET` | `/api/admin/deployments` | Deployment List |
| `POST` | `/api/admin/deployments` | Deployment Create |
| `POST` | `/api/admin/deployments/{deployment_id}/promote` | Deployment Promote |
| `POST` | `/api/admin/deployments/{deployment_id}/rollback` | Deployment Rollback |
| `POST` | `/api/admin/e2e-v2/admission/attestation` | Accept Attestation |
| `PUT` | `/api/admin/e2e-v2/admission/config` | Save Admission Config |
| `POST` | `/api/admin/e2e-v2/admission/nonce` | Issue Nonce |
| `GET` | `/api/admin/e2e-v2/overview` | Overview |
| `POST` | `/api/admin/e2e-v2/runs` | Start Run |
| `POST` | `/api/admin/e2e-v2/runs/{run_id}/cancel` | Cancel Run |
| `GET` | `/api/admin/enterprise/campaigns` | Enterprise Campaigns |
| `POST` | `/api/admin/enterprise/campaigns` | Enterprise Campaign Create |
| `PUT` | `/api/admin/enterprise/campaigns/{campaign_id}` | Enterprise Campaign Update |
| `GET` | `/api/admin/enterprise/monitoring` | Enterprise Monitoring |
| `POST` | `/api/admin/enterprise/monitoring` | Enterprise Monitoring Create |
| `DELETE` | `/api/admin/enterprise/monitoring/{check_id}` | Enterprise Monitoring Delete |
| `GET` | `/api/admin/enterprise/rules` | Enterprise Rules |
| `POST` | `/api/admin/enterprise/rules` | Enterprise Rule Create |
| `PUT` | `/api/admin/enterprise/rules/{rule_id}` | Enterprise Rule Update |
| `GET` | `/api/admin/enterprise/summary` | Enterprise Summary |
| `GET` | `/api/admin/family` | Admin Family |
| `POST` | `/api/admin/fields` | Admin Field |
| `DELETE` | `/api/admin/fields/{field_id}` | Admin Field Delete |
| `PUT` | `/api/admin/fields/{field_id}` | Admin Field Update |
| `GET` | `/api/admin/financial-ledger` | Admin Financial Ledger |
| `GET` | `/api/admin/fiscal` | Admin Fiscal |
| `PUT` | `/api/admin/fiscal` | Admin Fiscal Save |
| `POST` | `/api/admin/fiscal/receipts/{receipt_id}/retry` | Admin Fiscal Retry |
| `POST` | `/api/admin/fiscal/test` | Admin Fiscal Test |
| `GET` | `/api/admin/fraud` | Admin Fraud |
| `POST` | `/api/admin/fraud/scan` | Fraud Scan |
| `POST` | `/api/admin/fraud/{signal_id}` | Fraud Decision |
| `GET` | `/api/admin/gifts` | Admin Gifts |
| `POST` | `/api/admin/gifts` | Admin Gift Create |
| `GET` | `/api/admin/github-update` | Admin Github Update |
| `GET` | `/api/admin/giveaways` | Admin List |
| `POST` | `/api/admin/giveaways` | Create |
| `DELETE` | `/api/admin/giveaways/{giveaway_id}` | Delete Draft |
| `POST` | `/api/admin/giveaways/{giveaway_id}/close` | Close |
| `POST` | `/api/admin/giveaways/{giveaway_id}/draw` | Draw |
| `GET` | `/api/admin/giveaways/{giveaway_id}/entries` | Entries |
| `POST` | `/api/admin/giveaways/{giveaway_id}/publish` | Publish |
| `GET` | `/api/admin/health/summary` | Health Summary |
| `POST` | `/api/admin/images` | Admin Image |
| `DELETE` | `/api/admin/images/{image_id}` | Admin Image Delete |
| `GET` | `/api/admin/incident-mode` | Incident Mode Status |
| `POST` | `/api/admin/incident-mode` | Incident Mode |
| `GET` | `/api/admin/info-pages` | Admin List |
| `PUT` | `/api/admin/info-pages/{kind}` | Admin Save |
| `GET` | `/api/admin/jobs` | Admin Jobs |
| `POST` | `/api/admin/jobs/{job_id}/retry` | Retry Job |
| `POST` | `/api/admin/mail/dmarc/erase` | Admin Dmarc Erase |
| `GET` | `/api/admin/mail/dmarc/reports/{report_id}` | Admin Dmarc Report |
| `POST` | `/api/admin/mail/dmarc/sync` | Admin Dmarc Sync |
| `POST` | `/api/admin/mail/dmarc/upload` | Admin Dmarc Upload |
| `GET` | `/api/admin/mail/domain` | Admin Mail Domain |
| `POST` | `/api/admin/mail/domain/check` | Admin Mail Check |
| `GET` | `/api/admin/marketing` | Admin Marketing |
| `GET` | `/api/admin/marketplace/resellers` | List Resellers |
| `POST` | `/api/admin/marketplace/resellers` | Create Reseller |
| `PATCH` | `/api/admin/marketplace/resellers/{reseller_id}` | Update Reseller |
| `POST` | `/api/admin/marketplace/resellers/{reseller_id}/rotate-key` | Rotate Reseller Key |
| `GET` | `/api/admin/marketplace/withdrawals` | Withdrawals |
| `POST` | `/api/admin/marketplace/withdrawals/{withdrawal_id}/decision` | Decide |
| `POST` | `/api/admin/menu` | Admin Menu |
| `DELETE` | `/api/admin/menu/{item_id}` | Admin Menu Delete |
| `PUT` | `/api/admin/menu/{item_id}` | Admin Menu Update |
| `DELETE` | `/api/admin/miniapp/background` | Admin Miniapp Background Delete |
| `POST` | `/api/admin/miniapp/background` | Admin Miniapp Background |
| `PUT` | `/api/admin/miniapp/config` | Admin Miniapp Config |
| `DELETE` | `/api/admin/miniapp/image` | Admin Miniapp Image Delete |
| `POST` | `/api/admin/miniapp/image` | Admin Miniapp Image |
| `PUT` | `/api/admin/miniapp/menu` | Save Mini Tree |
| `DELETE` | `/api/admin/mobile-layout` | Admin Mobile Layout Reset |
| `GET` | `/api/admin/mobile-layout` | Admin Mobile Layout |
| `PUT` | `/api/admin/mobile-layout` | Admin Mobile Layout Save |
| `GET` | `/api/admin/mobile/mirrors` | Get Mirrors |
| `PUT` | `/api/admin/mobile/mirrors` | Put Mirrors |
| `POST` | `/api/admin/mobile/mirrors/publish` | Publish Now |
| `GET` | `/api/admin/mobile/ops` | Admin Mobile Ops |
| `GET` | `/api/admin/monitoring` | Admin Monitoring |
| `GET` | `/api/admin/network/intel` | Admin Network Intel |
| `POST` | `/api/admin/network/intel/refresh` | Admin Network Refresh |
| `GET` | `/api/admin/nodes/health` | Nodes Health |
| `PUT` | `/api/admin/nodes/health/config` | Nodes Health Config |
| `POST` | `/api/admin/nodes/update` | Update Nodes |
| `POST` | `/api/admin/nodes/{node_uuid}/restart` | Restart Node |
| `GET` | `/api/admin/notifications` | Admin Notifications |
| `POST` | `/api/admin/notifications` | Admin Notification Create |
| `GET` | `/api/admin/openapi.json` | Admin Openapi |
| `GET` | `/api/admin/ops/alerts` | Alerts Status |
| `POST` | `/api/admin/ops/alerts/test` | Alerts Test |
| `GET` | `/api/admin/ops/readiness` | Readiness |
| `GET` | `/api/admin/ops/summary` | Summary Preview |
| `POST` | `/api/admin/ops/summary/send` | Summary Send Now |
| `POST` | `/api/admin/ops/withdrawals/{withdrawal_id}/approve` | Admin Withdrawal Approve |
| `POST` | `/api/admin/ops/withdrawals/{withdrawal_id}/paid` | Admin Withdrawal Paid |
| `GET` | `/api/admin/overview` | Admin Overview |
| `GET` | `/api/admin/pages` | Pages |
| `POST` | `/api/admin/pages` | Create |
| `GET` | `/api/admin/pages/{page_id}` | Get |
| `PUT` | `/api/admin/pages/{page_id}` | Save |
| `POST` | `/api/admin/pages/{page_id}/archive` | Archive |
| `POST` | `/api/admin/pages/{page_id}/publish` | Publish |
| `POST` | `/api/admin/pages/{page_id}/restore` | Restore |
| `GET` | `/api/admin/pages/{page_id}/revisions` | Revisions |
| `POST` | `/api/admin/payment/gift-cards` | Create Gift Card |
| `GET` | `/api/admin/payments` | Admin Payments |
| `GET` | `/api/admin/payments/analytics` | Payment Analytics |
| `GET` | `/api/admin/payments/chargebacks` | Admin Chargebacks |
| `PATCH` | `/api/admin/payments/chargebacks/{chargeback_id}` | Update Chargeback |
| `GET` | `/api/admin/payments/gift-cards` | List Gift Cards |
| `GET` | `/api/admin/payments/platform/capabilities` | Admin Payment Platform Capabilities |
| `GET` | `/api/admin/payments/pricing/experiments` | List Price Experiments |
| `PUT` | `/api/admin/payments/pricing/experiments/{key}` | Upsert Price Experiment |
| `POST` | `/api/admin/payments/production-gate` | Production Payment Gate |
| `GET` | `/api/admin/payments/providers-report` | Providers Report |
| `POST` | `/api/admin/payments/reconcile` | Reconcile Payments |
| `GET` | `/api/admin/payments/{payment_id}` | Admin Payment Detail |
| `POST` | `/api/admin/payments/{payment_id}/refund-request` | Request Refund |
| `POST` | `/api/admin/payments/{payment_id}/retry` | Retry Payment |
| `POST` | `/api/admin/payments/{payment_id}/risk/recheck` | Payment Risk Recheck |
| `GET` | `/api/admin/payouts` | Admin Payouts |
| `POST` | `/api/admin/personal-offers` | Create Offer |
| `GET` | `/api/admin/plans` | Admin List Plans |
| `POST` | `/api/admin/plans` | Create Plan |
| `DELETE` | `/api/admin/plans/{plan_id}` | Admin Delete Plan |
| `PUT` | `/api/admin/plans/{plan_id}` | Admin Update Plan |
| `POST` | `/api/admin/plans/{plan_id}/enabled` | Admin Set Plan Enabled |
| `POST` | `/api/admin/platform/agents` | Create Agent |
| `POST` | `/api/admin/platform/api-keys` | Create Api Key |
| `DELETE` | `/api/admin/platform/api-keys/{key_id}` | Disable Api Key |
| `POST` | `/api/admin/platform/blacklist` | Add Blacklist |
| `POST` | `/api/admin/platform/dkim` | Create Dkim |
| `PUT` | `/api/admin/platform/mail` | Save Mail |
| `POST` | `/api/admin/platform/mail/test` | Test Mail |
| `POST` | `/api/admin/platform/plugins/{key}` | Toggle Plugin |
| `PUT` | `/api/admin/platform/policy` | Save Policy |
| `GET` | `/api/admin/platform/summary` | Platform Summary |
| `GET` | `/api/admin/platform/torrents` | Admin Torrents |
| `POST` | `/api/admin/platform/torrents/notify` | Admin Torrents Notify |
| `POST` | `/api/admin/platform/violations/{violation_id}/review` | Review Violation |
| `POST` | `/api/admin/platform/webhooks` | Create Webhook |
| `GET` | `/api/admin/plugins` | Admin Plugins |
| `GET` | `/api/admin/plugins/catalog` | Catalog |
| `POST` | `/api/admin/plugins/catalog/install` | Catalog Install |
| `GET` | `/api/admin/plugins/catalogs` | Catalog Settings |
| `PUT` | `/api/admin/plugins/catalogs` | Save Catalogs |
| `POST` | `/api/admin/plugins/publishers` | Add Publisher |
| `POST` | `/api/admin/plugins/publishers/{publisher_id}/revoke` | Revoke Publisher |
| `POST` | `/api/admin/plugins/upload` | Upload |
| `DELETE` | `/api/admin/plugins/{plugin_id}` | Uninstall |
| `POST` | `/api/admin/plugins/{plugin_id}/disable` | Disable |
| `POST` | `/api/admin/plugins/{plugin_id}/enable` | Enable |
| `POST` | `/api/admin/plugins/{plugin_id}/rollback` | Rollback |
| `POST` | `/api/admin/plugins/{plugin_id}/rotate` | Rotate |
| `POST` | `/api/admin/plugins/{plugin_id}/settings` | Save Settings |
| `GET` | `/api/admin/promo-audiences` | Audiences |
| `PUT` | `/api/admin/promo-audiences/{promo_id}` | Set Audience |
| `POST` | `/api/admin/promo-codes` | Create Promo Code |
| `GET` | `/api/admin/promo-codes/export.csv` | Export Promo Codes |
| `POST` | `/api/admin/promo-codes/generate` | Generate Promo Codes |
| `DELETE` | `/api/admin/promo-codes/{item_id}` | Delete Promo Code |
| `PUT` | `/api/admin/promo-codes/{item_id}` | Update Promo Code |
| `GET` | `/api/admin/promo-groups` | Groups |
| `POST` | `/api/admin/promo-groups` | Create Group |
| `PUT` | `/api/admin/promo-groups/{group_id}` | Update Group |
| `POST` | `/api/admin/promotions` | Create Promotion |
| `DELETE` | `/api/admin/promotions/{item_id}` | Delete Promotion |
| `PUT` | `/api/admin/promotions/{item_id}` | Update Promotion |
| `POST` | `/api/admin/provision-node` | Provision Node |
| `GET` | `/api/admin/push-campaigns` | List Campaigns |
| `POST` | `/api/admin/push-campaigns` | Create Campaign |
| `POST` | `/api/admin/push-campaigns/preview` | Preview Campaign |
| `POST` | `/api/admin/push-campaigns/{campaign_id}/cancel` | Cancel |
| `GET` | `/api/admin/push-campaigns/{campaign_id}/results` | Results |
| `DELETE` | `/api/admin/push-style` | Admin Push Style Reset |
| `GET` | `/api/admin/push-style` | Admin Push Style |
| `PUT` | `/api/admin/push-style` | Admin Push Style Save |
| `GET` | `/api/admin/push/status` | Admin Push Status |
| `GET` | `/api/admin/recovery` | Admin Recovery |
| `GET` | `/api/admin/recovery/operations` | Recovery Operations |
| `POST` | `/api/admin/recovery/operations/{operation_id}/retry` | Retry Operation |
| `GET` | `/api/admin/referrals/bonus` | Get Bonus |
| `PUT` | `/api/admin/referrals/bonus` | Set Bonus |
| `GET` | `/api/admin/referrals/program` | Get Program |
| `PUT` | `/api/admin/referrals/program` | Set Program |
| `POST` | `/api/admin/referrals/reconcile` | Reconcile Referrals |
| `GET` | `/api/admin/referrals/withdrawals` | Admin Withdrawals |
| `POST` | `/api/admin/referrals/withdrawals/{withdrawal_id}/approve` | Approve Withdrawal |
| `POST` | `/api/admin/referrals/withdrawals/{withdrawal_id}/paid` | Paid Withdrawal |
| `POST` | `/api/admin/referrals/withdrawals/{withdrawal_id}/reject` | Reject Withdrawal |
| `GET` | `/api/admin/refunds` | Admin Refunds |
| `POST` | `/api/admin/refunds/{refund_id}/approve` | Approve Refund |
| `GET` | `/api/admin/refunds/{refund_id}/dry-run` | Refund Dry Run |
| `POST` | `/api/admin/refunds/{refund_id}/execute` | Execute Refund |
| `POST` | `/api/admin/refunds/{refund_id}/mark-refunded` | Mark Refunded |
| `POST` | `/api/admin/refunds/{refund_id}/reconcile` | Reconcile Refund |
| `POST` | `/api/admin/refunds/{refund_id}/retry-revoke` | Retry Refund Revoke |
| `GET` | `/api/admin/releases` | Admin Releases |
| `POST` | `/api/admin/releases/check` | Check Release |
| `GET` | `/api/admin/remnawave/health` | Remnawave Health |
| `GET` | `/api/admin/remnawave/internal-squads` | Remnawave Internal Squads |
| `GET` | `/api/admin/remnawave/monitoring` | Admin Monitoring |
| `GET` | `/api/admin/remnawave/nodes` | Rw Nodes |
| `GET` | `/api/admin/remnawave/shop` | Remnawave Shop Overview |
| `POST` | `/api/admin/remnawave/shop/plan-mapping/validate` | Validate Plan Mapping |
| `POST` | `/api/admin/remnawave/shop/test` | Remnawave Shop Test |
| `GET` | `/api/admin/remnawave/users` | Rw Users |
| `GET` | `/api/admin/remnawave/users/stream` | Rw User Stream |
| `GET` | `/api/admin/remnawave/users/{user_id}` | Rw User |
| `POST` | `/api/admin/remnawave/users/{user_id}/extend` | Rw Extend |
| `GET` | `/api/admin/remnawave/users/{user_id}/keys` | Rw Keys |
| `GET` | `/api/admin/remnawave/users/{user_id}/subscription` | Rw Subscription |
| `GET` | `/api/admin/runtime-settings` | Admin Runtime Settings |
| `DELETE` | `/api/admin/runtime-settings/changes/{change_id}` | Admin Discard Runtime Settings |
| `POST` | `/api/admin/runtime-settings/changes/{change_id}/apply` | Admin Apply Runtime Settings |
| `POST` | `/api/admin/runtime-settings/changes/{change_id}/rollback` | Admin Rollback Runtime Settings |
| `POST` | `/api/admin/runtime-settings/stage` | Admin Stage Runtime Settings |
| `GET` | `/api/admin/security` | Admin Security |
| `POST` | `/api/admin/security/incident` | Security Incident |
| `GET` | `/api/admin/security/incidents` | Security Incidents |
| `GET` | `/api/admin/security/risk-summary` | Risk Summary |
| `GET` | `/api/admin/security/secrets/status` | Secret Status |
| `GET` | `/api/admin/sessions` | Admin Sessions |
| `POST` | `/api/admin/sessions/revoke-all` | Revoke All Sessions |
| `DELETE` | `/api/admin/sessions/{session_id}` | Revoke Admin Session |
| `PUT` | `/api/admin/settings/{key}` | Admin Setting |
| `GET` | `/api/admin/staging-e2e/config` | Staging E2E Config |
| `PUT` | `/api/admin/staging-e2e/config` | Update Staging E2E Config |
| `POST` | `/api/admin/staging-e2e/run` | Run Staging E2E |
| `GET` | `/api/admin/staging-e2e/status` | Staging E2E Status |
| `GET` | `/api/admin/status/components` | Admin Status Components |
| `POST` | `/api/admin/status/components` | Admin Status Component Create |
| `PUT` | `/api/admin/status/components/{component_id}` | Admin Status Component Update |
| `GET` | `/api/admin/subscription-operations` | Admin Operations |
| `POST` | `/api/admin/subscription-operations/{operation_id}/refund` | Refund Change |
| `POST` | `/api/admin/support-pro/sso` | Support Pro Sso |
| `GET` | `/api/admin/support-pro/status` | Support Pro Status |
| `GET` | `/api/admin/support/ai` | Support Ai Settings |
| `PUT` | `/api/admin/support/ai` | Save Support Ai |
| `DELETE` | `/api/admin/support/attachments/{attachment_id}` | Admin Remove |
| `GET` | `/api/admin/support/attachments/{attachment_id}` | Admin Download |
| `GET` | `/api/admin/support/tickets` | Admin Tickets |
| `POST` | `/api/admin/support/tickets/{ticket_id}/attachments` | Admin Upload |
| `GET` | `/api/admin/support/tickets/{ticket_id}/attachments/drafts` | Admin Drafts |
| `POST` | `/api/admin/support/tickets/{ticket_id}/draft` | Support Draft |
| `GET` | `/api/admin/support/tickets/{ticket_id}/messages` | Admin Support Messages |
| `POST` | `/api/admin/support/tickets/{ticket_id}/reply` | Admin Ticket Reply |
| `POST` | `/api/admin/support/topology/apply` | Apply |
| `POST` | `/api/admin/support/topology/preview` | Preview |
| `GET` | `/api/admin/surveys` | Admin List |
| `POST` | `/api/admin/surveys` | Create |
| `DELETE` | `/api/admin/surveys/{survey_id}` | Delete Draft |
| `PUT` | `/api/admin/surveys/{survey_id}` | Edit |
| `POST` | `/api/admin/surveys/{survey_id}/close` | Close |
| `POST` | `/api/admin/surveys/{survey_id}/publish` | Publish |
| `GET` | `/api/admin/surveys/{survey_id}/responses` | Responses |
| `GET` | `/api/admin/system/health` | System Health |
| `GET` | `/api/admin/tariff-constructors` | Admin Constructors |
| `POST` | `/api/admin/tariff-constructors` | Admin Constructor Create |
| `DELETE` | `/api/admin/tariff-constructors/{constructor_id}` | Admin Constructor Delete |
| `PUT` | `/api/admin/tariff-constructors/{constructor_id}` | Admin Constructor Update |
| `GET` | `/api/admin/terminal` | Admin Terminal |
| `POST` | `/api/admin/terminal/sessions` | Admin Terminal Start |
| `POST` | `/api/admin/terminal/sessions/{sid}/close` | Admin Terminal Close |
| `POST` | `/api/admin/terminal/sessions/{sid}/input` | Admin Terminal Input |
| `GET` | `/api/admin/terminal/sessions/{sid}/output` | Admin Terminal Output |
| `GET` | `/api/admin/terminal/sessions/{sid}/transcript` | Admin Terminal Transcript |
| `POST` | `/api/admin/terminal/snippets` | Admin Snippet Create |
| `POST` | `/api/admin/terminal/snippets/{snippet_id}/delete` | Admin Snippet Delete |
| `GET` | `/api/admin/traffic-packages` | Admin Packages |
| `POST` | `/api/admin/traffic-packages` | Create Package |
| `PUT` | `/api/admin/traffic-packages/{package_id}` | Edit Package |
| `POST` | `/api/admin/v15/deployments/{deployment_id}/rollback` | Rollback |
| `GET` | `/api/admin/v15/operations` | Operations |
| `POST` | `/api/admin/v16/nodes/register` | Register Node |
| `POST` | `/api/admin/v16/nodes/{node_name}/failover` | Node Failover |
| `GET` | `/api/admin/v3/automation` | Admin Automation |
| `POST` | `/api/admin/v3/automation/{rule_id}/toggle` | Toggle Automation |
| `GET` | `/api/admin/v3/control-center` | Control Center |
| `GET` | `/api/admin/v3/devices` | Admin Devices |
| `GET` | `/api/admin/v3/routing` | Get Routing |
| `PUT` | `/api/admin/v3/routing` | Put Routing |
| `GET` | `/api/admin/v41/analytics` | V41 Analytics |
| `GET` | `/api/admin/v41/backups/verification` | V41 Backup Verification List |
| `POST` | `/api/admin/v41/backups/{backup_id}/test-restore` | V41 Backup Test Restore |
| `GET` | `/api/admin/v41/crm/users` | V41 Crm Users |
| `GET` | `/api/admin/v41/diagnostics` | V41 Diagnostics |
| `GET` | `/api/admin/v41/features` | V41 Features |
| `PUT` | `/api/admin/v41/features/{key}` | V41 Feature Update |
| `GET` | `/api/admin/v41/incidents` | V41 Incidents |
| `POST` | `/api/admin/v41/incidents` | V41 Incident Create |
| `POST` | `/api/admin/v41/incidents/{incident_id}/resolve` | V41 Incident Resolve |
| `GET` | `/api/admin/v41/passkeys` | V41 Passkeys |
| `DELETE` | `/api/admin/v41/passkeys/{credential_id}` | V41 Passkey Delete |
| `GET` | `/api/admin/v41/promotions` | V41 Promotions |
| `GET` | `/api/admin/v41/providers` | V41 Providers |
| `PUT` | `/api/admin/v41/providers/{provider}` | V41 Provider Update |
| `POST` | `/api/admin/v41/providers/{provider}/reset` | V41 Provider Reset |
| `GET` | `/api/admin/v41/referrals` | V41 Referrals |
| `GET` | `/api/admin/v6/capacity` | Capacity |
| `GET` | `/api/admin/v6/command-center` | Command Center |
| `GET` | `/api/admin/v6/commercial` | Commercial |
| `GET` | `/api/admin/v6/config/{section}` | Get Config |
| `PUT` | `/api/admin/v6/config/{section}` | Put Config |
| `GET` | `/api/admin/v6/events` | Events |
| `GET` | `/api/admin/v6/integrations` | Integrations |
| `GET` | `/api/admin/v6/intelligence` | Intelligence |
| `POST` | `/api/admin/v6/orchestrator/evaluate` | Orchestrate |
| `POST` | `/api/admin/v6/provision` | Provision |
| `GET` | `/api/admin/v6/security-center` | Security Center |
| `GET` | `/api/admin/workers` | Admin Workers |
| `POST` | `/api/agent/heartbeat` | Agent Heartbeat |
| `POST` | `/api/agent/observations` | Agent Observations |
| `GET` | `/api/agent/terminal/pending` | Agent Terminal Pending |
| `GET` | `/api/agent/terminal/{sid}/input` | Agent Terminal Input |
| `POST` | `/api/agent/terminal/{sid}/output` | Agent Terminal Output |
| `POST` | `/api/agent/torrent` | Agent Torrent |
| `GET` | `/api/app-config` | App Config |
| `GET` | `/api/app/open` | Open App |
| `GET` | `/api/app/paid` | Paid Return |
| `POST` | `/api/auth/email/verification/confirm` | Confirm Verification |
| `POST` | `/api/auth/exchange` | Auth Exchange |
| `GET` | `/api/auth/google` | Google Login |
| `GET` | `/api/auth/google/callback` | Google Callback |
| `POST` | `/api/auth/login` | Auth Login |
| `POST` | `/api/auth/logout` | User Logout |
| `POST` | `/api/auth/mobile/code` | Redeem App Code |
| `POST` | `/api/auth/mobile/token` | Mobile Token |
| `GET` | `/api/auth/passkeys` | Inventory |
| `POST` | `/api/auth/passkeys/login/options` | Login Options |
| `POST` | `/api/auth/passkeys/login/verify` | Login Verify |
| `POST` | `/api/auth/passkeys/registration/options` | Registration Options |
| `POST` | `/api/auth/passkeys/registration/verify` | Registration Verify |
| `POST` | `/api/auth/passkeys/{credential_id}/delete` | Remove |
| `POST` | `/api/auth/password/reset/confirm` | Confirm Reset |
| `POST` | `/api/auth/password/reset/request` | Request Reset |
| `POST` | `/api/auth/register` | Auth Register |
| `POST` | `/api/auth/telegram` | Telegram Auth |
| `GET` | `/api/auth/vk` | Vk Login |
| `GET` | `/api/auth/vk/callback` | Vk Callback |
| `GET` | `/api/auth/yandex` | Yandex Login |
| `GET` | `/api/auth/yandex/callback` | Yandex Callback |
| `GET` | `/api/bot/banners/default/{name}` | Default Banner |
| `POST` | `/api/internal/staging-e2e/payment` | Internal Staging Payment |
| `POST` | `/api/internal/staging-e2e/refund` | Internal Staging Refund |
| `POST` | `/api/internal/staging-e2e/refund-status` | Internal Staging Refund Status |
| `POST` | `/api/internal/staging-e2e/remnawave` | Internal Staging Remnawave |
| `POST` | `/api/internal/staging-e2e/verify` | Internal Staging Verify |
| `GET` | `/api/internal/support-bridge/attachments/{attachment_id}` | Attachment |
| `POST` | `/api/internal/support-bridge/imports/{source_id}` | Import Ticket |
| `POST` | `/api/internal/support-bridge/imports/{source_id}/attachments` | Import Attachment |
| `POST` | `/api/internal/support-bridge/imports/{source_id}/complete` | Complete Import |
| `POST` | `/api/internal/support-bridge/imports/{source_id}/messages` | Import Message |
| `GET` | `/api/internal/support-bridge/tickets` | Tickets |
| `GET` | `/api/internal/support-bridge/tickets/recent` | Recent |
| `POST` | `/api/internal/support-bridge/tickets/{ticket_id}/attachments` | Add Attachment |
| `POST` | `/api/internal/support-bridge/tickets/{ticket_id}/customer-message` | Customer Message |
| `GET` | `/api/internal/support-bridge/tickets/{ticket_id}/messages` | Messages |
| `POST` | `/api/internal/support-bridge/tickets/{ticket_id}/reply` | Reply |
| `POST` | `/api/internal/support-bridge/tickets/{ticket_id}/status` | Status |
| `GET` | `/api/me` | Api Me |
| `POST` | `/api/me/account-merge/authorization` | Create Authorization |
| `POST` | `/api/me/account-merge/confirm` | Confirm Merge |
| `POST` | `/api/me/account-merge/preview` | Preview Merge |
| `POST` | `/api/me/app-login` | Create App Login |
| `GET` | `/api/me/auto-renew` | Auto Renew Status |
| `PUT` | `/api/me/auto-renew` | Set Auto Renew |
| `DELETE` | `/api/me/auto-renew/method` | Remove Auto Renew Method |
| `GET` | `/api/me/billing-center` | Billing Center |
| `GET` | `/api/me/connection-info` | Connection Info |
| `GET` | `/api/me/connection-qr` | Connection Qr |
| `GET` | `/api/me/consent` | My Consent |
| `POST` | `/api/me/consent` | Accept Consent |
| `GET` | `/api/me/dashboard` | Customer Dashboard |
| `GET` | `/api/me/devices` | My Devices |
| `POST` | `/api/me/devices` | Register Device |
| `POST` | `/api/me/devices/transfer` | Device Transfer |
| `POST` | `/api/me/devices/{device_id}/revoke` | Revoke Device |
| `POST` | `/api/me/diagnostics` | My Diagnostics |
| `GET` | `/api/me/email` | Email Status |
| `POST` | `/api/me/email/verification/request` | Request Verification |
| `GET` | `/api/me/family` | My Family |
| `POST` | `/api/me/family/join` | Family Join |
| `DELETE` | `/api/me/family/members/{member_id}` | Family Remove |
| `POST` | `/api/me/family/{subscription_id}/invite` | Family Invite |
| `GET` | `/api/me/gifts` | Purchased Gifts |
| `POST` | `/api/me/gifts/purchase` | Purchase Gift |
| `POST` | `/api/me/gifts/redeem` | Redeem Gift |
| `GET` | `/api/me/giveaways` | Customer List |
| `POST` | `/api/me/giveaways/{giveaway_id}/enter` | Enter |
| `GET` | `/api/me/identity` | Identity |
| `POST` | `/api/me/lusi/action` | Lusi Action |
| `GET` | `/api/me/mobile/alerts` | Mobile Alerts |
| `GET` | `/api/me/mobile/bootstrap` | Mobile Bootstrap |
| `GET` | `/api/me/mobile/connection` | Mobile Connection |
| `GET` | `/api/me/mobile/diagnostics` | Mobile Diagnostics |
| `GET` | `/api/me/mobile/features` | Mobile Features |
| `GET` | `/api/me/mobile/notifications` | Mobile Notifications |
| `POST` | `/api/me/mobile/notifications/{notification_id}/read` | Mobile Notification Read |
| `GET` | `/api/me/mobile/privacy` | Mobile Privacy |
| `GET` | `/api/me/notifications` | My Notifications |
| `POST` | `/api/me/notifications/{notification_id}/read` | Read Notification |
| `GET` | `/api/me/offers` | Offers |
| `GET` | `/api/me/partner` | Portal |
| `POST` | `/api/me/partner/withdrawals` | Withdraw |
| `POST` | `/api/me/password/change` | Change Password |
| `POST` | `/api/me/payment/gift-card/redeem` | Redeem Gift Card |
| `PUT` | `/api/me/payment/tax-profile` | Set Tax Profile |
| `GET` | `/api/me/payments` | My Payments |
| `GET` | `/api/me/payments/order/{order_id}` | My Payment By Order |
| `GET` | `/api/me/payments/{payment_id}/invoice` | Payment Invoice |
| `PUT` | `/api/me/preferences/language` | Set Language |
| `DELETE` | `/api/me/privacy/account` | Privacy Delete |
| `GET` | `/api/me/privacy/export` | Privacy Export |
| `GET` | `/api/me/profile` | My Profile |
| `PATCH` | `/api/me/profile` | Update Profile |
| `GET` | `/api/me/push/devices` | List Devices |
| `POST` | `/api/me/push/devices` | Register Device |
| `POST` | `/api/me/push/devices/unregister` | Unregister Device |
| `DELETE` | `/api/me/push/devices/{device_id}` | Delete Device |
| `POST` | `/api/me/push/test` | Test Push |
| `GET` | `/api/me/receipts` | My Receipts |
| `GET` | `/api/me/referral` | My Referral |
| `POST` | `/api/me/referral/apply` | Apply Referral |
| `GET` | `/api/me/referral/ledger` | My Referral Ledger |
| `GET` | `/api/me/referral/network` | My Network |
| `GET` | `/api/me/referral/withdrawals` | My Withdrawals |
| `POST` | `/api/me/referral/withdrawals` | Request Withdrawal |
| `GET` | `/api/me/remnawave/subscription` | My Remnawave Subscription |
| `POST` | `/api/me/remnawave/subscription/refresh` | Refresh My Remnawave Subscription |
| `GET` | `/api/me/routing/recommendation` | Routing Recommendation |
| `GET` | `/api/me/security-center` | Security Center |
| `POST` | `/api/me/security/revoke-all` | Revoke All User Sessions |
| `GET` | `/api/me/servers` | My Servers |
| `POST` | `/api/me/source` | My Source |
| `GET` | `/api/me/stars-subscriptions` | My Stars Subscriptions |
| `POST` | `/api/me/stars-subscriptions` | Create Stars Subscription |
| `POST` | `/api/me/stars-subscriptions/{row_id}/cancel` | Cancel Stars Subscription |
| `GET` | `/api/me/subscription` | My Subscription |
| `GET` | `/api/me/subscription-file` | Subscription File |
| `GET` | `/api/me/subscription/commerce` | Commerce Catalog |
| `POST` | `/api/me/subscription/lifecycle` | Subscription Lifecycle |
| `GET` | `/api/me/subscription/operations` | Commerce History |
| `POST` | `/api/me/subscription/purchase` | Purchase Change |
| `POST` | `/api/me/subscription/quote` | Quote Change |
| `GET` | `/api/me/subscriptions` | List Subscriptions |
| `PUT` | `/api/me/subscriptions/{subscription_id}` | Rename Subscription |
| `POST` | `/api/me/subscriptions/{subscription_id}/select` | Select Subscription |
| `DELETE` | `/api/me/support/attachments/{attachment_id}` | Customer Remove |
| `GET` | `/api/me/support/attachments/{attachment_id}` | Customer Download |
| `GET` | `/api/me/support/tickets` | My Support Tickets |
| `POST` | `/api/me/support/tickets` | Create Support Ticket |
| `POST` | `/api/me/support/tickets/{ticket_id}/attachments` | Customer Upload |
| `GET` | `/api/me/support/tickets/{ticket_id}/attachments/drafts` | Customer Drafts |
| `GET` | `/api/me/support/tickets/{ticket_id}/messages` | Customer Support Messages |
| `POST` | `/api/me/support/tickets/{ticket_id}/messages` | Customer Support Reply |
| `GET` | `/api/me/surveys` | Customer List |
| `GET` | `/api/me/surveys/{survey_id}` | Customer Detail |
| `POST` | `/api/me/surveys/{survey_id}/submit` | Submit |
| `GET` | `/api/me/sync` | My Sync |
| `GET` | `/api/me/traffic` | My Traffic |
| `POST` | `/api/me/trial` | Claim Trial |
| `GET` | `/api/me/v15/bootstrap` | V15 Bootstrap |
| `POST` | `/api/me/v16/roaming` | Roaming |
| `POST` | `/api/me/v16/tunnel-profile` | Tunnel Profile |
| `GET` | `/api/me/wallet/history` | Wallet History |
| `POST` | `/api/me/wallet/spend` | Wallet Spend |
| `POST` | `/api/me/wallet/stars-invoice` | Stars Invoice |
| `POST` | `/api/me/wallet/topup` | Wallet Topup |
| `GET` | `/api/me/widget` | Widget Summary |
| `POST` | `/api/mobile/events` | Collect Events |
| `POST` | `/api/mobile/integrity/challenge` | Integrity Challenge |
| `GET` | `/api/mobile/layout` | Mobile Layout |
| `GET` | `/api/mobile/push-style` | Public Push Style |
| `POST` | `/api/payments/create` | Create Payment |
| `POST` | `/api/payments/mobile/verify` | Verify Mobile Purchase |
| `GET` | `/api/payments/providers` | Payment Providers |
| `POST` | `/api/payments/sandbox/complete` | Sandbox Complete |
| `POST` | `/api/payments/webhooks/paypal` | Paypal Webhook |
| `POST` | `/api/payments/webhooks/stripe` | Stripe Webhook |
| `GET` | `/api/plans` | Plans |
| `GET` | `/api/plugin/v1/me` | Plugin Me |
| `POST` | `/api/plugin/v1/notifications` | Plugin Notify |
| `GET` | `/api/plugin/v1/payments/{payment_id}` | Plugin Payment |
| `GET` | `/api/plugin/v1/users/{user_id}` | Plugin User |
| `GET` | `/api/plugin/v1/users/{user_id}/subscriptions` | Plugin Subscriptions |
| `POST` | `/api/probe/report` | Probe Report |
| `GET` | `/api/probe/targets` | Probe Targets |
| `GET` | `/api/promo/validate` | Validate Promo |
| `GET` | `/api/public/app-login/methods` | Public Login Methods |
| `GET` | `/api/public/apps` | Public Apps |
| `GET` | `/api/public/apps/install` | Public Install Guide |
| `GET` | `/api/public/apps/{app_id}/download` | Public App Download |
| `GET` | `/api/public/branding` | Public Branding |
| `GET` | `/api/public/cabinet-menu` | Public Cabinet Menu |
| `GET` | `/api/public/config` | Public Config |
| `GET` | `/api/public/info-pages` | Public List |
| `GET` | `/api/public/info-pages/{kind}` | Public Page |
| `GET` | `/api/public/menu-emoji/{emoji_id}` | Menu Emoji |
| `GET` | `/api/public/mirrors` | Public Mirrors |
| `GET` | `/api/public/pages` | Catalog |
| `GET` | `/api/public/pages/{slug}` | Public Page |
| `GET` | `/api/public/servers` | Public Servers |
| `GET` | `/api/public/service-status` | Public Status |
| `GET` | `/api/public/status` | Public Status |
| `GET` | `/api/public/v15/privacy` | Public Privacy |
| `GET` | `/api/public/v16/release` | Release |
| `GET` | `/api/public/v6/status` | Public Status |
| `GET` | `/api/reseller/branding` | Reseller Branding |
| `GET` | `/api/reseller/catalog` | Reseller Catalog |
| `GET` | `/api/reseller/stats` | Reseller Stats |
| `GET` | `/api/tariff-constructors` | Public Constructors |
| `GET` | `/api/v3/status` | V3 Status |
| `POST` | `/api/webhooks/crypto` | Crypto Webhook |
| `POST` | `/api/webhooks/cryptobot` | Cryptobot Webhook |
| `GET` | `/api/webhooks/freekassa` | Freekassa Webhook |
| `POST` | `/api/webhooks/freekassa` | Freekassa Webhook |
| `POST` | `/api/webhooks/platega` | Platega Webhook |
| `POST` | `/api/webhooks/remnawave` | Remnawave Webhook |
| `POST` | `/api/webhooks/rollypay` | Rollypay Webhook |
| `POST` | `/api/webhooks/yookassa` | Yookassa Webhook |
| `GET` | `/health` | Health |
| `GET` | `/health/live` | Health Live |
| `GET` | `/health/ready` | Health Ready |
| `GET` | `/metrics` | Metrics |
