# VPN Shop by Corgi Lucy guides

[Русский](../ru/README.md) · **English** · [Українська](../uk/README.md)

Use these guides to set up a new VPS or operate an existing shop.

## Download the mobile apps

[Choose an app and download it](../../README.en.md#download-the-mobile-apps). Android has separate apps for the shop, the standalone VPN client and Lucy Admin. The shop and Lucy Admin each have an unsigned IPA for an iOS device and a ZIP for the simulator. Every download has a SHA-256 checksum.

## Operator guides

| Task | Start here |
| --- | --- |
| Install the shop and connect a domain | [VPS installation](guides/INSTALLATION.md) · [DNS and HTTPS](../wiki/en/Domains.md) |
| Set up a plan and issue access | [Admin panel](guides/ADMIN_PANEL.md) · [Remnawave and nodes](guides/REMNAWAVE.md) |
| Accept payments | [Payment providers, Telegram Stars and Tribute](../wiki/en/Payments.md) |
| Update or restore a shop | [Update and rollback](../wiki/en/Updates.md) · [Backups](../wiki/en/Backup.md) · [Recovery commands in Russian](../ru/BACKUP_CURRENT.md) |
| Investigate a failure | [Troubleshooting](../wiki/en/Troubleshooting.md) · [Security](../wiki/en/Security.md) |

To try the shop locally, run `bash scripts/test-up.sh` from a checkout of the published tag with Docker and Compose installed. The services listen on `127.0.0.1`. The API uses port `18080`, Lucy Admin `18081`, the cabinet `18082` and the Mini App `18083`. The script starts the shop with sandbox payments.

## Release and reference

Distribution `v28.161.0` uses runtime/API `21.5.1`. The database migrations are `0094_store_subscriptions` for the shop and `0008` for Support Pro. [Release assets](https://github.com/booarkz-cpu/shop-by-boo/releases/tag/v28.161.0) · [Current readiness matrix in Russian](../ru/MATRIX_COMPLETION_21_5_1.md).

[All English guides](guides/README.md) · [API catalogue](../API_ENDPOINTS.md) · [License](../../LICENSE) · [Changelog](../../CHANGELOG.md) · [Previous guide index](https://github.com/booarkz-cpu/shop-by-boo/blob/9d7bd45c41380d47726bf7448111475210282a50/docs/en/README.md).
