> Current v21.0.1: [operator documentation](../../DOCUMENTATION.md). Production payments are closed; this historical provider test does not certify application E2E v2.

# Staging E2E and payment gate — v20.0.8

## Scope of the current runner

The admin panel runs `scripts/staging-e2e.sh` in backend. It checks HTTPS health, staging Remnawave reachability, sandbox payment creation, provider status and amount/currency, a repeated read, and a refund. This is a **provider API check**, not a complete end-to-end test. It does not observe the incoming webhook, the resulting order state, subscription fulfillment in Remnawave, duplicate webhook delivery, or post-refund state. It cannot mark the run `passed` or enable live payments. Old v20.0.7 pass results and gate values are invalidated.

## Isolated staging setup

1. Back up PostgreSQL, media, and `.env`; test restoration on a separate host. Keep production payment credentials out of staging.
2. Use separate HTTPS domains, PostgreSQL, Redis, Remnawave, plan, and test user. Set `APP_ENV=staging`, `PAYMENTS_SANDBOX=true`, and `COOKIE_SECURE=true`. Use sandbox keys for every provider.
3. Generate unique runner and user tokens. In the admin panel enter the public API URL, staging Remnawave URL/token, plan, and provider list. Confirm that credentials are sandbox credentials.
4. Check `docker compose config --quiet`, `docker compose ps`, `/health`, migrations, DNS, and certificates. Do not expose database, Redis, or runner ports.
5. Configure each provider to deliver real signed webhooks to a separate staging URL. Record order, payment, and event IDs without secrets.

## Full manual E2E matrix

Run every step for each provider; record timestamps, IDs, expected and actual states. Never publish tokens or payment details.

| Step | Action | Pass criterion |
| --- | --- | --- |
| 1 | Create an order in the user UI and open checkout | One order, correct plan, amount and currency, HTTPS sandbox checkout |
| 2 | Complete sandbox payment | Provider confirms the same ID and amount; mismatched ID or amount is rejected |
| 3 | Wait for the authentic signed webhook | Event is applied once and order becomes paid; status polling alone does not count |
| 4 | Verify fulfillment | Exactly one Remnawave access exists; the buyer sees a usable subscription link and expiry |
| 5 | Redeliver the same webhook and poll status | No second order, charge, or access; replay is idempotent |
| 6 | Send invalid signature and mismatched payloads | Request is rejected and financial/subscription state stays unchanged |
| 7 | Request a full sandbox refund and await notification | Provider and shop agree on refund; no falsely paid order remains |
| 8 | Exercise a transient Remnawave failure | Controlled retry succeeds without duplicate fulfillment |

Also test checkout cancellation, expiry, concurrent requests, delayed webhooks, and services/backend/worker restart. Test backup restoration separately. An API `verify` response is not a substitute for a webhook.

## Running and interpreting the automated check

Save staging configuration in the admin panel and start the run. Open each `[CHECKOUT]` link from the log and finish the sandbox payment. After the provider and refund checks the runner reports `[INCOMPLETE]`: this is expected and **does not authorize** production. `failed` means that even the covered checks did not pass. A future v2 runner must verify webhook, fulfillment, and idempotency before the payment gate can open. Never manually edit `payments.production_gate.v20_0_8` in the database.

## Production readiness and rollback

Check audit logs, webhook/queue monitoring, restored backups, secrets, and HTTPS. Until a complete v2 E2E implementation exists, the admin panel must reject enabling live payments. The new gate key closes any v20.0.7 gate left open; existing orders still need separate reconciliation. On an incident, pause new payments, retain event IDs and logs, reconcile provider and database state, and use an approved operator process for fulfillment or refunds. Restore compatible code and database from a tested backup when rolling back. Rolling back to v20.0.7 reintroduces the old gate behavior and requires a manual payment hold.
