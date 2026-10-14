> Current distribution: `v28.3.0`; runtime/API: `21.5.1`. Exact readiness boundaries are documented in the current coverage matrix.

# VPN Shop — v28.3.0 (runtime 21.5.1)

Current stable core: API, admin, cabinet/Mini App, bot, Support Pro and mobile sources. Shop migration: `0064_runtime_settings`; Support Pro: `0006`. v28.3.0 adds 96 typed live settings with encrypted secrets, staged apply, audit, process convergence and rollback; all 46 restart-bound fields and 2 workflow-owned fields are classified explicitly.

Production payments remain closed until application E2E v2 is completed. Full roadmap transfer and owner-signed APK/IPA are not complete. Stable is the release channel of the current core.

[Current operator documentation (Russian)](../../DOCUMENTATION.md), [live settings](../ru/RUNTIME_SETTINGS_CURRENT.md), [SSH/Termius deployment](../ru/DEPLOYMENT_CURRENT.md), [update](../ru/WORKSPACE_UPGRADE.md), [backup](../ru/BACKUP_CURRENT.md), [referrals](../ru/REFERRALS_CURRENT.md), [mobile](../../MOBILE.md), [API](../API_ENDPOINTS.md), [license](../../LICENSE).

To test locally: clone tag `v28.3.0` and run `bash scripts/test-up.sh`. Loopback ports: API 18080, admin 18081, cabinet 18082, Mini App 18083. The sandbox subscription does not provide a VPN tunnel.

New server installation from a root SSH/Termius terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v28.3.0/install.sh -o /root/shop-install.sh && BRANCH=v28.3.0 bash /root/shop-install.sh
```

Use the update procedure for an existing shop; preserve secrets and verify a consistent backup first.
