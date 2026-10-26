# VPN Shop by Corgi — v3 feature map

## Реализовано

### Operations / Admin
- Control Center: KPI users, active subscriptions, devices, revenue, pending/failed payments, automation, campaigns.
- Smart Routing: persisted configuration with strategy, load ceiling, preferred countries, fallback and health window.
- Device Management: inventory of user devices with owner, platform, status, IP and last activity.
- Automation Center: existing AutomationRule engine exposed with enable/disable actions and campaign inventory.
- Command Palette: Ctrl/Cmd+K navigation across all admin sections.
- Existing modules remain available: nodes, monitoring, incidents, fraud, payments, financial ledger, CRM, customer 360, support, apps, backups, recovery, passkeys, releases, deployments, notifications and staging.

### Customer / Cabinet
- Device management section backed by `/api/me/devices`.
- Smart Routing recommendation backed by `/api/me/routing/recommendation`.
- Existing subscription, payment, referral, support, server and application flows preserved.

### Backend
- New `backend/app/v3_api.py` router.
- Routing configuration stored in `AppSetting` to avoid a new migration for the first release.
- Smart Routing fails closed/degraded: if Remnawave is unavailable, no unsafe node recommendation is returned.
- Admin actions use the existing permission system.
- No VPN node secrets are exposed to customer responses.

## Existing capabilities retained
- Payment providers and webhook verification.
- Remnawave provisioning.
- MFA/session security.
- Anti-fraud and abuse scoring.
- Node agents and queued agent actions.
- Campaigns and automation rules.
- Monitoring and health checks.
- Backup verification / isolated restore testing.
- Releases and deployment controls.
- Customer 360, support, referrals and promotions.
- WebAuthn credential inventory.

## Verification
- `python -m compileall -q backend` — PASS.
- `scripts/static_audit.py` — PASS.
- The current execution environment does not contain `asyncpg`, so importing the live FastAPI app against PostgreSQL cannot be completed here; this is an environment dependency limitation, not a syntax failure.
- npm dependencies are retained in the project lockfiles; production build should be executed in the deployment/staging environment after `npm ci`.
