# Схема базы данных — v28.147.0

Сгенерировано из моделей `backend/app/models.py` командой `python scripts/generate-db-schema.py`. Head миграций: `0094_store_subscriptions`. Модели и миграции описывают одну схему: это проверяет `tests/test_schema_matches_migrations.py`.

## Сущности задания

| Сущность | Таблицы | Примечание |
| --- | --- | --- |
| Users | `users` | клиенты; администраторы — `admin_users` |
| Roles | `admin_users.role` | роль администратора: `viewer`, `operator` или `admin` |
| Permissions | — | словарь `PERMISSIONS` в `backend/app/security.py`; проверка — `require_permission` |
| Sessions | `user_sessions`, `admin_sessions` | отзываемые сессии по хэшу `jti` |
| Subscriptions | `subscriptions` | `remnawave_uuid` (в коде `remnawave_user_id`) — числовой id пользователя Remnawave 3.x |
| Tariffs | `plans`, `tariff_constructors`, `tariff_constructor_options`, `traffic_packages` |  |
| Devices | `user_devices`, `device_blacklist` | HWID-устройства подписки |
| Servers | — | серверы и ноды хранятся в Remnawave; магазин хранит агентов нод |
| Nodes | `node_agents`, `agent_actions` | агент на ноде: здоровье, команды, терминал |
| Domains | — | домены задаются в `.env` и `deploy/Caddyfile`; таблица — этап 11 |
| Certificates | — | сертификаты выпускает Caddy; учёт в базе — этап 11 |
| Payments | `payments`, `payment_provider_events`, `refund_requests`, `payment_chargebacks` |  |
| Transactions | `financial_ledger`, `referral_ledger`, `payout_transactions` | журнал денег, одна запись на операцию |
| Promo Codes | `promo_codes`, `promo_redemptions`, `promo_reservations` |  |
| Gifts | `gift_codes`, `gift_redemptions`, `gift_cards` |  |
| Referrals | `referral_rewards`, `referral_level_rewards`, `referral_contests`, `withdrawal_requests` |  |
| Notifications | `notifications`, `push_devices`, `push_campaigns`, `push_deliveries` |  |
| Support Tickets | `support_tickets`, `support_messages`, `support_attachments` | плюс отдельная база Support Pro |
| Integrations | `platform_plugins`, `plugin_installs`, `outbound_webhooks`, `shop_api_keys` |  |
| Background Jobs | `jobs`, `worker_states`, `backup_jobs` |  |
| Audit Logs | `audit_logs` | все изменения администраторов |

## Таблицы

Всего таблиц: 161, внешних ключей: 57. Связи без внешнего ключа держит код; записи без связи показывает «Аналитика → Запуск и оповещения → Целостность данных» (`GET /api/admin/integrity`).

| Таблица | Модель | Колонок | Уникальные | Индексы | Внешние ключи |
| --- | --- | --- | --- | --- | --- |
| `abuse_violations` | `AbuseViolation` | 9 | — | status, user_id | — |
| `account_actions` | `AccountAction` | 9 | token_hash | user_id | user_id → users |
| `account_mail` | `AccountMail` | 7 | action_id | — | action_id → account_actions |
| `account_merge_aliases` | `AccountMergeAlias` | 11 | email, referral_code, source_user_id, telegram_id, vk_id, yandex_id | target_user_id | source_user_id → users, target_user_id → users |
| `account_merge_authorizations` | `AccountMergeAuthorization` | 7 | token_hash | expires_at, source_user_id, target_user_id | source_user_id → users, target_user_id → users |
| `account_merge_operations` | `AccountMergeOperation` | 7 | — | authorization_id, source_user_id, target_user_id | authorization_id → account_merge_authorizations, source_user_id → users, target_user_id → users |
| `admin_sessions` | `AdminSession` | 9 | jti_hash | admin_id | — |
| `admin_users` | `AdminUser` | 12 | email, passkey_user_handle, telegram_id | — | — |
| `advertisements` | `Advertisement` | 10 | — | — | — |
| `agent_actions` | `AgentAction` | 6 | — | agent_id, status | — |
| `app_events` | `AppEvent` | 8 | — | created_at, event, install_hash, user_id | — |
| `app_settings` | `AppSetting` | 2 | — | — | — |
| `audit_logs` | `AuditLog` | 7 | — | created_at, request_id | — |
| `auth_exchange_codes` | `AuthExchangeCode` | 6 | code_hash | user_id | — |
| `auto_renew_methods` | `AutoRenewMethod` | 12 | user_id | status+next_attempt_at | — |
| `automation_executions` | `AutomationExecution` | 5 | rule_id+anchor | created_at, rule_id, user_id | rule_id → automation_rules |
| `automation_rules` | `AutomationRule` | 11 | — | event+enabled | — |
| `backup_jobs` | `BackupJob` | 9 | — | — | — |
| `backup_verifications` | `BackupVerification` | 9 | — | backup_id | — |
| `bot_menu_items` | `BotMenuItem` | 10 | — | parent_id | parent_id → bot_menu_items |
| `broadcasts` | `Broadcast` | 11 | — | — | — |
| `cabinet_menu_items` | `CabinetMenuItem` | 7 | slug | — | — |
| `campaigns` | `Campaign` | 12 | — | status | — |
| `cancellation_feedback` | `CancellationFeedback` | 6 | — | created_at, user_id | — |
| `connection_observations` | `ConnectionObservation` | 15 | — | hwid, remnawave_uuid, user_id | — |
| `connection_reports` | `ConnectionReport` | 10 | — | carrier+server, created_at | — |
| `content_pages` | `ContentPage` | 10 | slug+locale | — | — |
| `content_revisions` | `ContentRevision` | 8 | page_id+version | page_id | page_id → content_pages |
| `corporate_accounts` | `CorporateAccount` | 18 | invite_code | owner_user_id | — |
| `corporate_invoices` | `CorporateInvoice` | 10 | number | account_id | account_id → corporate_accounts |
| `corporate_members` | `CorporateMember` | 12 | account_id+user_id | account_id, subscription_id, user_id | account_id → corporate_accounts |
| `custom_fields` | `CustomField` | 7 | key | — | — |
| `customer_batch_operations` | `CustomerBatchOperation` | 4 | — | — | — |
| `customer_import_identities` | `CustomerImportIdentity` | 4 | — | user_id | user_id → users |
| `customer_import_jobs` | `CustomerImportJob` | 10 | — | expires_at | — |
| `customer_passkey_challenges` | `CustomerPasskeyChallenge` | 7 | — | expires_at, user_id | user_id → users |
| `customer_passkeys` | `CustomerPasskey` | 9 | credential_id | user_id | user_id → users |
| `deployments` | `Deployment` | 11 | — | status, version | — |
| `device_blacklist` | `DeviceBlacklist` | 6 | hwid | — | — |
| `dmarc_intake_state` | `DmarcIntakeState` | 10 | — | — | — |
| `dmarc_records` | `DmarcRecord` | 12 | — | report_row_id, source_ip | report_row_id → dmarc_reports |
| `dmarc_reports` | `DmarcReport` | 15 | org_name+report_id | date_end | — |
| `e2e_cases` | `E2ECase` | 21 | run_id+provider | payment_id, run_id | run_id → e2e_runs |
| `e2e_runs` | `E2ERun` | 17 | active | — | — |
| `e2e_webhook_captures` | `E2EWebhookCapture` | 7 | case_id | — | case_id → e2e_cases |
| `entitlement_operations` | `EntitlementOperation` | 12 | payment_id, quote_id | subscription_id, user_id | — |
| `entitlement_quotes` | `EntitlementQuote` | 10 | — | user_id | — |
| `family_groups` | `FamilyGroup` | 5 | invite_code, owner_subscription_id | owner_user_id | — |
| `family_members` | `FamilyMember` | 9 | group_id+user_id | group_id, subscription_id, user_id | group_id → family_groups |
| `feature_flags` | `FeatureFlag` | 5 | key | — | — |
| `feedback_ratings` | `FeedbackRating` | 9 | kind+ticket_id, kind+user_id+period | created_at, user_id | — |
| `financial_ledger` | `FinancialLedger` | 11 | operation_key | created_at, payment_id, user_id | — |
| `first_connect_waits` | `FirstConnectWait` | 6 | subscription_id | deadline | — |
| `fiscal_receipts` | `FiscalReceipt` | 15 | payment_id+kind | next_attempt_at, payment_id, status | — |
| `fraud_signals` | `FraudSignal` | 10 | — | fingerprint, ip, kind, status, user_id | — |
| `gift_cards` | `GiftCard` | 9 | code_hash | code_prefix | — |
| `gift_codes` | `GiftCode` | 14 | code, idempotency_key | purchaser_user_id | — |
| `gift_redemptions` | `GiftRedemption` | 12 | gift_code_id+user_id, operation_key | gift_code_id, subscription_id, user_id | — |
| `giveaway_entries` | `GiveawayEntry` | 7 | giveaway_id+user_id | giveaway_id, user_id | giveaway_id → giveaways, user_id → users |
| `giveaways` | `Giveaway` | 17 | — | — | — |
| `grace_squads` | `GraceSquad` | 5 | subscription_id | — | — |
| `history_import_jobs` | `HistoryImportJob` | 14 | — | expires_at | — |
| `imported_payments` | `ImportedPayment` | 11 | source_key | job_id, user_id | job_id → history_import_jobs, user_id → users |
| `imported_subscription_links` | `ImportedSubscriptionLink` | 6 | subscription_id | job_id, user_id | job_id → history_import_jobs, subscription_id → subscriptions, user_id → users |
| `infra_costs` | `InfraCost` | 8 | — | month | — |
| `jobs` | `Job` | 13 | job_key | kind, status, worker_id | — |
| `loyalty_members` | `LoyaltyMember` | 3 | — | — | — |
| `menu_images` | `MenuImage` | 5 | — | — | — |
| `monitoring_checks` | `MonitoringCheck` | 13 | — | — | — |
| `network_intel` | `NetworkIntel` | 10 | ip+source | expires_at, ip | — |
| `network_intel_sources` | `NetworkIntelSourceState` | 5 | — | — | — |
| `node_agents` | `NodeAgent` | 12 | name, token_hash | — | — |
| `notifications` | `Notification` | 14 | user_id+dedupe_key | push_fanout_at, status, user_id | — |
| `outbound_webhooks` | `OutboundWebhook` | 8 | — | — | — |
| `panel_api_stats` | `PanelApiStat` | 8 | hour+source+method+path | hour | — |
| `panel_user_changes` | `PanelUserChange` | 8 | — | created_at, panel_user+created_at | — |
| `partner_commissions` | `PartnerCommission` | 10 | gift_code_id, payment_id | reseller_id | gift_code_id → gift_codes, payment_id → payments, reseller_id → resellers |
| `partner_withdrawals` | `PartnerWithdrawal` | 10 | reseller_id+idempotency_key | reseller_id | reseller_id → resellers |
| `payment_chargebacks` | `PaymentChargeback` | 11 | external_id | payment_id, status | — |
| `payment_invoices` | `PaymentInvoice` | 11 | invoice_number, payment_id | — | — |
| `payment_price_experiments` | `PaymentPriceExperiment` | 5 | key | — | — |
| `payment_provider_events` | `PaymentProviderEvent` | 9 | provider+event_id | event_id, payment_id, status | — |
| `payment_provider_health` | `PaymentProviderHealth` | 10 | provider | — | — |
| `payment_provider_metrics` | `PaymentProviderMetric` | 10 | — | day, provider | — |
| `payment_risk_assessments` | `PaymentRiskAssessment` | 6 | payment_id | — | — |
| `payment_tax_profiles` | `PaymentTaxProfile` | 9 | user_id | — | — |
| `payments` | `Payment` | 36 | order_id, provider_payment_id, user_id+idempotency_key | fulfillment_status, fulfillment_status+next_retry_at, idempotency_key, next_retry_at, referrer_id_snapshot, reseller_id, subscription_id, user_id | — |
| `payout_transactions` | `PayoutTransaction` | 11 | external_id, withdrawal_id | status | — |
| `plans` | `Plan` | 9 | — | — | — |
| `platform_plugins` | `PlatformPlugin` | 4 | key | — | — |
| `plugin_deliveries` | `PluginDelivery` | 11 | plugin_id+event_key | next_attempt_at, plugin_id, status | plugin_id → plugin_installs |
| `plugin_event_cursors` | `PluginEventCursor` | 2 | — | — | — |
| `plugin_installs` | `PluginInstall` | 15 | token_hash | — | — |
| `plugin_packages` | `PluginPackage` | 8 | plugin_id+version | plugin_id | — |
| `plugin_publishers` | `PluginPublisher` | 6 | fingerprint, public_key | — | — |
| `promo_audiences` | `PromoAudience` | 7 | — | group_id | group_id → promo_groups, promo_id → promo_codes |
| `promo_codes` | `PromoCode` | 15 | code | — | — |
| `promo_group_members` | `PromoGroupMember` | 2 | — | — | group_id → promo_groups, user_id → users |
| `promo_groups` | `PromoGroup` | 5 | — | — | — |
| `promo_redemptions` | `PromoRedemption` | 5 | payment_id | promo_code_id, user_id | — |
| `promo_reservations` | `PromoReservation` | 8 | order_id, payment_id | promo_code_id, user_id | — |
| `promotions` | `Promotion` | 11 | — | — | — |
| `provisioning_operations` | `ProvisioningOperation` | 14 | operation_key, payment_id | status, user_id | — |
| `push_campaign_recipients` | `PushCampaignRecipient` | 5 | campaign_id+user_id | campaign_id, user_id | campaign_id → push_campaigns |
| `push_campaigns` | `PushCampaign` | 16 | — | created_at, scheduled_at | — |
| `push_deliveries` | `PushDelivery` | 9 | notification_id+device_id | device_id, next_attempt_at, notification_id, status | device_id → push_devices, notification_id → notifications |
| `push_devices` | `PushDevice` | 14 | token_hash | revoked_at, session_id, user_id | session_id → user_sessions, user_id → users |
| `referral_contests` | `ReferralContest` | 9 | — | — | — |
| `referral_ledger` | `ReferralLedger` | 8 | payment_id | referral_level_reward_id, source_user_id, user_id | referral_level_reward_id → referral_level_rewards |
| `referral_level_rewards` | `ReferralLevelReward` | 8 | payment_id+level, payment_id+referrer_id | payment_id, referred_user_id, referrer_id | — |
| `referral_rewards` | `ReferralReward` | 7 | payment_id | referred_user_id, referrer_id | — |
| `refund_requests` | `RefundRequest` | 9 | payment_id | user_id | — |
| `release_records` | `ReleaseRecord` | 7 | — | — | — |
| `remnawave_deployment_steps` | `RemnawaveDeploymentStep` | 11 | — | installation_id | installation_id → remnawave_installations |
| `remnawave_domains` | `RemnawaveDomain` | 19 | domain | — | — |
| `remnawave_events` | `RemnawaveEvent` | 10 | event_key | created_at, event, subscription_id, user_id | — |
| `remnawave_installations` | `RemnawaveInstallation` | 20 | — | status | — |
| `remnawave_servers` | `RemnawaveServer` | 22 | name | — | — |
| `resellers` | `Reseller` | 13 | api_key_hash, owner_user_id, slug | — | owner_user_id → users |
| `runtime_setting_changes` | `RuntimeSettingChange` | 12 | fingerprint | source_change_id, status | source_change_id → runtime_setting_changes |
| `runtime_setting_state` | `RuntimeSettingState` | 3 | — | — | — |
| `security_incident_events` | `SecurityIncidentEvent` | 8 | — | — | — |
| `security_incidents` | `SecurityIncident` | 7 | — | — | — |
| `shop_api_keys` | `ShopApiKey` | 8 | secret_hash | — | — |
| `shop_carts` | `ShopCart` | 5 | — | — | — |
| `speed_tests` | `SpeedTest` | 9 | — | created_at, user_id | — |
| `stars_subscriptions` | `StarsSubscription` | 15 | order_id | subscription_id, user_id | — |
| `status_components` | `StatusComponent` | 8 | slug | — | — |
| `status_subscribers` | `StatusSubscriber` | 3 | user_id | — | — |
| `store_subscriptions` | `StoreSubscription` | 12 | provider+chain_key | user_id | — |
| `sub_requests` | `SubRequest` | 16 | — | created_at, short_uuid+created_at | — |
| `subscription_freezes` | `SubscriptionFreeze` | 8 | — | subscription_id, until, user_id | — |
| `subscriptions` | `Subscription` | 22 | user_id | user_id | — |
| `support_attachments` | `SupportAttachment` | 11 | ticket_id+actor+idempotency_key | message_id, ticket_id | message_id → support_messages, ticket_id → support_tickets |
| `support_import_links` | `SupportImportLink` | 3 | ticket_id | — | ticket_id → support_tickets |
| `support_messages` | `SupportMessage` | 7 | ticket_id+role+idempotency_key | ticket_id | ticket_id → support_tickets |
| `support_tickets` | `SupportTicket` | 10 | — | merged_into_id, updated_at+id, user_id | merged_into_id → support_tickets |
| `support_topology_operations` | `SupportTopologyOperation` | 4 | — | — | — |
| `survey_responses` | `SurveyResponse` | 8 | survey_id+user_id | survey_id, user_id | survey_id → surveys, user_id → users |
| `surveys` | `Survey` | 17 | — | — | — |
| `system_errors` | `SystemErrorLog` | 11 | fingerprint | last_seen | — |
| `tariff_constructor_options` | `TariffConstructorOption` | 8 | — | constructor_id | — |
| `tariff_constructors` | `TariffConstructor` | 8 | — | plan_id | — |
| `telegram_bot_state` | `TelegramBotState` | 15 | — | — | — |
| `terminal_chunks` | `TerminalChunk` | 6 | — | session_id | session_id → terminal_sessions |
| `terminal_sessions` | `TerminalSession` | 23 | — | admin_id, agent_id, created_at, status | — |
| `terminal_snippets` | `TerminalSnippet` | 5 | — | — | — |
| `torrent_detections` | `TorrentDetection` | 7 | hour+agent_id+client+kind | agent_id, hour, user_id | — |
| `traffic_packages` | `TrafficPackage` | 7 | — | — | — |
| `trial_grants` | `TrialGrant` | 14 | user_id | ip_hash, subscription_id | — |
| `user_activity` | `UserActivity` | 6 | — | created_at, user_id+created_at | — |
| `user_consents` | `UserConsent` | 6 | user_id+document+version | user_id | user_id → users |
| `user_devices` | `UserDevice` | 11 | device_key | subscription_id, user_id, user_id+status | — |
| `user_sessions` | `UserSession` | 9 | jti_hash | user_id | — |
| `users` | `User` | 20 | email, passkey_user_handle, referral_code, telegram_id, vk_id, yandex_id | acquisition_source, merged_into_user_id, referred_by_id | merged_into_user_id → users |
| `vpn_sessions` | `VpnSession` | 11 | — | last_seen, panel_user+last_seen | — |
| `webauthn_challenges` | `WebAuthnChallenge` | 7 | — | admin_id, expires_at | admin_id → admin_users |
| `webauthn_credentials` | `WebAuthnCredential` | 9 | credential_id | admin_id | — |
| `wg_configs` | `WgConfig` | 8 | — | subscription_id | — |
| `withdrawal_requests` | `WithdrawalRequest` | 9 | user_id+idempotency_key | user_id | — |
| `worker_states` | `WorkerState` | 6 | worker_id | — | — |
