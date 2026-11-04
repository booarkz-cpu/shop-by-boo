# Domains and certificates

| Domain | Points to | Purpose |
| --- | --- | --- |
| `shop.` `api.` `admin.` `cabinet.` | shop server | cabinet, API, admin, Mini App |
| `panel.` | panel server | Remnawave panel |
| `sub.` | subscription page server | Remnawave subscription page |
| `link.` and others | shop server | the shop's subscription portal and mirrors |

- Turn the Cloudflare proxy off for Let's Encrypt domains: the check needs ports 80 and 443 directly.
- Check records and certificates in «Серверы → Домены и сертификаты».
- Certificates renew automatically; «Состояние системы» warns 14 days before expiry.

More: [owner setup guide](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/en/OWNER_SETUP_GUIDE.md#domains), [domain guide](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/DOMAIN_SETUP_GUIDE.md) (Russian).
