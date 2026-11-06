# Remnawave from scratch: the owner's step-by-step guide

From an empty VPS to a shop selling subscriptions on your own nodes. Everything happens in the shop's admin panel, without commands on the servers.

Russian original: [REMNAWAVE_INSTALLATION_GUIDE](../../ru/new/REMNAWAVE_INSTALLATION_GUIDE.md). Other guides: [index](README.md).

## 0. What to prepare

- **VPS:** one (panel and node together) or several (panel on one, nodes on others). Debian 12–13 or Ubuntu 22.04–26.04, x86_64 or arm64.
- **Login:** root, or a user with password-less `sudo`; an Ed25519 key or a password.
- **Domains:** for the panel and, optionally, for the subscription page — see [DOMAIN_SETUP_GUIDE](../../ru/new/DOMAIN_SETUP_GUIDE.md).
- **Confirmation of dangerous actions.** Turn on 2FA in «Protection and 2FA»: running a plan on servers is confirmed with a code ([RBAC](../../ru/new/RBAC.md)).

## 1. Add the servers

«Servers → Remnawave installation → Servers for Remnawave»:
1. Enter the address, port, user and key or password.
2. Compare the server's host key fingerprint with your hosting console and save.
3. Press «Check». The report shows the OS, resources, Docker, busy ports and DNS.

Details: [installation wizard](../../ru/new/REMNAWAVE_INSTALLATION_WIZARD.md).

## 2. Switch to the shop's own key

«Change key» in the server's row. The shop creates its own key for this server and checks that it can log in with it. After that the shop no longer keeps your password or key.

## 3. Install

1. **Mode:** «Panel and node», «Panel only», «Node only», with a separate subscription page, or distributed.
2. **Domains and certificate:** Let's Encrypt for real domains, or an internal one for testing.
3. **Plan:** «Make a plan», read what will change, «Run this plan», confirm with your code. The step log shows at once; on an error the changes are rolled back.

Optional at install time with SelfSteal: the node transports xHTTP + REALITY (TCP 4443), gRPC + REALITY (TCP 8443) and Hysteria2 (UDP 443) next to TCP + REALITY.

## 4. Connect the shop

«Connect the shop to this panel» → «Apply». The shop starts creating users in this panel without a restart. The panel administrator's password: «Show panel login», with confirmation.

## 5. Add nodes

The «Add nodes» mode on a connected panel: the shop registers the node in the panel, opens its port only for the panel's address and checks the connection. Node modules — IPv6, Xray core, WARP, NetBird, Xray Checker, node transports, server protection (fail2ban, security updates, BBR, SSH only from your addresses) and self-healing — are in «Remnawave extensions» and the wizard ([REMNAWAVE_EXTENSIONS](../../ru/new/REMNAWAVE_EXTENSIONS.md)).

## 6. Maintenance

| What | Where |
| --- | --- |
| Updating the panel and nodes | «Updates → Remnawave auto-update» — at night or with a button ([AUTO_UPDATE](../../ru/new/AUTO_UPDATE.md)) |
| Panel database copies | automatically on every update; kept on the panel server and, encrypted, in the shop |
| Diagnostics, database restore, reinstall, removal | the installation's buttons in «Remnawave installation» |
| Turning a node off/on, renaming it, moving it | «Servers → Servers» |
| Status | «System status», «Automation Center», monitoring |

**Verified:** installation in CI on a real panel and node (live tests in `remnawave-live.yml`). On your VPS with your domains — BLOCKED_EXTERNAL until test servers are available.
