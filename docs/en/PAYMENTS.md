> Актуальный дистрибутив: `v28.1.0`; runtime/API: `21.5.1`. Точные границы готовности указаны в текущей матрице покрытия.

# VPN Shop — v21.5.1

Current stable core: API, admin, cabinet/Mini App, bot, Support Pro and mobile sources. Shop migration: `0062_support_delivery_identity`; Support Pro: `0006`. New features: immutable multilevel referral rewards and a private network graph; authenticated coordinated CLI backups of both databases and files.

Production payments remain closed until application E2E v2 is completed. Full roadmap transfer and owner-signed APK/IPA are not complete. Stable is the release channel of the current core.

[Current operator documentation (Russian)](../../DOCUMENTATION.md), [SSH/Termius deployment](../ru/DEPLOYMENT_CURRENT.md), [update](../ru/WORKSPACE_UPGRADE.md), [backup](../ru/BACKUP_CURRENT.md), [referrals](../ru/REFERRALS_CURRENT.md), [mobile](../../MOBILE.md), [API](../API_ENDPOINTS.md), [license](../../LICENSE).

To test locally: clone tag `v21.5.1` and run `bash scripts/test-up.sh`. Loopback ports: API 18080, admin 18081, cabinet 18082, Mini App 18083. The sandbox subscription does not provide a VPN tunnel.

New server installation from a root SSH/Termius terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/v21.5.1/install.sh -o /root/shop-install.sh && BRANCH=v21.5.1 bash /root/shop-install.sh
```

Use the update procedure for an existing shop; preserve secrets and verify a consistent backup first.
