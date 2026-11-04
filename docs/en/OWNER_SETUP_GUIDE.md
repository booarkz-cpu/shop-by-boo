# Owner setup: Remnawave from scratch and domains

A short English version of [REMNAWAVE_INSTALLATION_GUIDE](../ru/new/REMNAWAVE_INSTALLATION_GUIDE.md) and [DOMAIN_SETUP_GUIDE](../ru/new/DOMAIN_SETUP_GUIDE.md) (Russian, more detail). Everything is done in the shop's admin panel; no commands on the servers.

## Remnawave from scratch

1. **Prepare.**
   - One VPS (panel and node together) or several. Debian 12–13 or Ubuntu 22.04–26.04, x86_64 or arm64.
   - Root or passwordless `sudo`.
   - Domains (below).
   - Turn on 2FA in «Защита и 2FA»: launching a plan on servers asks for a fresh code.
2. **Add servers.** «Серверы → Установка Remnawave → Серверы для Remnawave»:
   - enter the address, port, user and key or password;
   - check the host key fingerprint against your hosting console;
   - press «Проверить» (OS, resources, Docker, busy ports, DNS).
3. **Rotate the key.** «Сменить ключ» creates the shop's own key for the server and stops storing your password or key.
4. **Install.**
   - Pick a mode: panel and node, panel only, node only, separate subscription page, or distributed.
   - Pick the domains and certificate.
   - Make the plan, read it, run it and confirm with a code. On a failure the changes are rolled back.
5. **Connect the shop.** «Подключить магазин к этой панели» → «Применить». No restart.
6. **Add nodes.** Use the «Добавить ноды» mode. Node modules (IPv6, Xray core, WARP, NetBird, Xray Checker) are in «Расширения Remnawave».
7. **Maintain.**
   - Updates: «Обновления → Автообновление Remnawave».
   - Panel database copies are made before every update.
   - Diagnostics, restore, reinstall and removal: in the installer.

Verified in CI against a real panel and node. On your own VPS and domains: BLOCKED_EXTERNAL until test servers exist.

## Domains

| Domain (example) | Record | Points to | Purpose |
| --- | --- | --- | --- |
| `shop.`, `api.`, `admin.`, `cabinet.` | A/AAAA | shop server | cabinet, API, admin, Mini App |
| `panel.example.com` | A | Remnawave panel server | panel (Let's Encrypt via Caddy) |
| `sub.example.com` | A | subscription page server | Remnawave subscription page, optional |
| `link.example.com` and others | A | **shop server** | the shop's subscription portal, added without a restart |
| SelfSteal / REALITY domain | A | node server | node camouflage |

Turn the Cloudflare proxy off for domains that get a Let's Encrypt certificate: the HTTP-01 check needs ports 80 and 443 directly. Check the records in «Серверы → Домены и сертификаты → Проверить». Certificates renew automatically. «Состояние системы» warns 14 days before one expires.
