# VPN Shop by Corgi — V2 Architecture

## Product surfaces

- `admin/` — Control Center for operations, sales, customers, infrastructure and security.
- `cabinet/` — customer self-service cabinet focused on subscription, connection, billing and support.
- `miniapp/` — compact Telegram Mini App surface.
- `backend/` — FastAPI application, payment orchestration, Remnawave provisioning and operational APIs.

## UX principles

1. Business-critical information first: revenue, active VPNs, incidents and system health.
2. Destructive operations require explicit actions and server-side permissions.
3. Loading, empty, error and success states are part of every workflow.
4. Admin navigation is grouped by business domain rather than backend endpoint names.
5. Customer navigation is limited to tasks a customer actually performs.

## Security baseline

- Production startup rejects shipped default secrets/passwords.
- Admin endpoints remain permission-gated server-side.
- CSRF is enforced for cookie-authenticated state changes.
- Rate limiting, trusted-host checks and security headers remain enabled.
- Payment webhooks stay outside the browser CSRF flow.
- Remnawave credentials are never exposed to customer responses.

## Release validation

Run:

```bash
python -m compileall -q backend/app
python scripts/static_audit.py
```

Frontend builds require the project package dependencies to be installed in the build environment:

```bash
npm ci
npm run build
```

The repository contains an extensive pytest suite; CI should run it with PostgreSQL/Redis/asyncpg available rather than relying on a source-only environment.
