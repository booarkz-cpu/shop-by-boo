> Current distribution: `v28.7.0`; runtime/API: `21.5.1`. Exact readiness boundaries are documented in the current coverage matrix.

# VPN Shop — v28.7.0 (runtime 21.5.1)

Current stable core: API, admin, cabinet/Mini App, bot, Support Pro and mobile sources. Shop migration: `0066_push_notifications`; Support Pro: `0007`. v28.7.0 adds an email support channel to Support Pro 3.7 (IMAP intake without duplicates, threaded SMTP replies, loop and bounce protection, erasure and retention). v28.6.0 added an opt-in Android home-screen subscription widget and multiple shop profiles in the Android and iOS admin apps. v28.5.0 added opt-in native push notifications for the Android and iOS apps (FCM HTTP v1 and APNs, token bound to the signed-in session and revoked on sign-out). v28.4.0 moved the admin panel, customer cabinet and Telegram Mini App to Next.js with the Remna dark design (collapsible sidebar, mobile drawer, metric dashboard, Telegram WebApp SDK integration) and added a reconciled historical import of subscriptions and payments with rollback and a customer profile API. v28.3.0 added 96 typed live settings with encrypted secrets, staged apply, audit, process convergence and rollback; all restart-bound fields and 2 workflow-owned fields are classified explicitly.

Production payments remain closed until application E2E v2 is completed. Full roadmap transfer and owner-signed APK/IPA are not complete. Stable is the release channel of the current core.

[Current operator documentation (Russian)](../../DOCUMENTATION.md), [live settings](../ru/RUNTIME_SETTINGS_CURRENT.md), [SSH/Termius deployment](../ru/DEPLOYMENT_CURRENT.md), [update](../ru/WORKSPACE_UPGRADE.md), [backup](../ru/BACKUP_CURRENT.md), [referrals](../ru/REFERRALS_CURRENT.md), [mobile](../../MOBILE.md), [API](../API_ENDPOINTS.md), [license](../../LICENSE).

To test locally: clone tag `v28.7.0` and run `bash scripts/test-up.sh`. Loopback ports: API 18080, admin 18081, cabinet 18082, Mini App 18083. The sandbox subscription does not provide a VPN tunnel.

New server installation from a root SSH/Termius terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v28.7.0/install.sh -o /root/shop-install.sh && BRANCH=v28.7.0 bash /root/shop-install.sh
```

Use the update procedure for an existing shop; preserve secrets and verify a consistent backup first.
