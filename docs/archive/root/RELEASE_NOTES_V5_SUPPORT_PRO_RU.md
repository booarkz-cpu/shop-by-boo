# VPN Shop by Corgi — Support Pro Integration

## Release

Integrated Support Pro 3.4 into the VPN Shop by Corgi administration stack.

### Admin

- New **Клиенты → Support Pro** section.
- Live health check.
- One-click secure SSO launch.
- Embedded Support Pro workspace in the admin shell.
- SSO token is short-lived (60s) and single-use.

### Infrastructure

- Dedicated PostgreSQL database.
- Dedicated Redis.
- Dedicated uploads volume.
- Dedicated migration container.
- Dedicated worker.
- Optional separate Telegram bot process.
- Support service is not exposed directly to the Internet by Docker ports.
- Caddy publishes the configured support domain over HTTPS.

### Support Pro functionality preserved

Tickets, SLA, assignment, Telegram channel, realtime WebSocket, customer portal, knowledge base, macros/catalog, automation rules, webhooks, incidents, calls, reports, audit, operators, teams, attachments, notifications, backup/restore tooling and worker jobs.

### Security

The integration does not persist VPN Shop administrator passwords in Support Pro. SSO uses an HMAC-SHA256 signed token with an expiration and a one-time `jti` stored in Support Pro Redis. The browser receives only the generated SSO URL.
