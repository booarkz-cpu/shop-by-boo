# Security

- **2FA and confirmation of dangerous actions.** Restoring backups, administrators, refunds, the node terminal, applying settings and other dangerous actions need a fresh 2FA code (or the password) — 10 minutes, one session.
- **Security history** — «Сессии → История безопасности»: sign-ins, failed attempts with IP, confirmations, key rotations.
- **Secrets** are never shown after saving; the shop creates the servers' SSH keys itself and rotates them with a button.
- **Container logs** in the browser — secrets from `.env` replaced by `***`.
- **Monitoring:** security metrics on `/metrics` and Prometheus rules.

More (Russian): [security audit](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/SECURITY_AUDIT.md), [secrets](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/SECRETS_MANAGEMENT.md), [incident response](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/INCIDENT_RESPONSE.md), [roles](https://github.com/booarkz-cpu/shop-by-boo/blob/main/docs/ru/new/RBAC.md).
