> Current distribution: `v28.15.0`; runtime/API: `21.5.1`. Exact readiness boundaries are documented in the current coverage matrix.

> v21.5.1: API 18080, admin 18081, cabinet 18082, Mini App 18083. [Current testing guide](../ru/TESTING.md).

# Trying the shop without payment gateways

This stack runs the API, admin panel, cabinet and Mini App on your computer. YooKassa, Platega, RollyPay, Stripe, PayPal, the crypto gateway, Telegram and Remnawave are not required.

Sandbox does not pretend to be a production VPN. The subscription link is `sandbox://local/...`. Happ will not import it. The point is to test registration, the storefront, checkout and the subscription row.

`bash scripts/test-up.sh` passes `.env.test` to Compose and binds test ports to `127.0.0.1`. For remote access use an SSH tunnel, for example `ssh -L 18081:127.0.0.1:18081 user@server`, then open `http://127.0.0.1:18081`. `COOKIE_SECURE=false` applies only to this local test. Production installation is in [DEPLOYMENT.md](DEPLOYMENT.md).

## Requirements

- Docker Engine and the Compose plugin.
- Free ports 18080, 18081, 18082 and 18083.
- This repository.

## 1. Start

From the repository root:

```bash
bash scripts/test-up.sh
```

The script:

1. Creates `.env.test` from `.env.test.example` when it is missing, with random `APP_SECRET`, database password and admin password.
2. Passes `.env.test` to Compose and starts `docker-compose.test.yml`.
3. Waits for `http://127.0.0.1:18080/health`.
4. Runs `scripts/sandbox-e2e.sh`: register, buy the plan "Тестовый месяц" through the `sandbox` provider, and finish fulfillment.

It prints `ADMIN_EMAIL` and, on the first run, `ADMIN_PASSWORD`. The password is also in `.env.test`. Do not commit that file.

| Surface | URL |
| --- | --- |
| API | http://127.0.0.1:18080 |
| Admin | http://127.0.0.1:18081 |
| Cabinet | http://127.0.0.1:18082 |
| Mini App | http://127.0.0.1:18083 |

Stop:

```bash
docker compose --env-file .env.test -f docker-compose.test.yml down
```

Database files stay in Compose volumes. Add `-v` to drop them.

## 2. Check health

```bash
curl -fsS http://127.0.0.1:18080/health
curl -fsS http://127.0.0.1:18080/api/public/config
```

The second body has `payments_sandbox` set to `true` and `sandbox` inside `payment_providers`.

## 3. Sign in to admin

1. Open http://127.0.0.1:18081
2. Use `admin@example.test` and the password from `.env.test`.
3. Open plans. An empty database already has "Тестовый месяц": 100 in the default currency, 30 days, 100 GB, 3 devices.
4. Create a second plan and disable it. The cabinet must hide a disabled plan.

## 4. Buy a plan in the cabinet

1. Open http://127.0.0.1:18082
2. Register a new email and password.
3. Open plans and pay for "Тестовый месяц". If the button does not send a provider, a request with an empty provider still uses sandbox, because no live gateway is configured.
4. The cabinet returns with `sandbox_payment`. Completion calls `POST /api/payments/sandbox/complete`.
5. The connection section shows a link that starts with `sandbox://local/`.

`scripts/sandbox-e2e.sh` already walked this path. A second email confirms the storefront is still up.

## 5. Top up the wallet

If the cabinet shows a wallet top-up, the amount must be from 50 to 100000. Sandbox marks the payment paid and credits `wallet_balance`. The same `Idempotency-Key` does not credit the amount twice.

## 6. What will not happen

- The test compose file does not start the bot. An empty `BOT_TOKEN` still stops the bot in production. Outside production the bot process waits instead of crash-looping if you start it yourself.
- `/api/public/servers` may list no nodes. That is expected without an agent and without Remnawave.
- A live provider returns an error or `503`: the production gate is closed and the gateway keys are empty.
- `provider=yookassa` is not rewritten to sandbox while the gate is closed. Sandbox is chosen automatically only when the provider is omitted and no live gateway is configured, or when `sandbox` is sent explicitly.

## 7. If startup fails

```bash
docker compose --env-file .env.test -f docker-compose.test.yml logs --tail 80 backend
```

If the API never becomes ready, the log usually shows Alembic or `APP_SECRET must be at least 32 characters`. Do not set `APP_ENV=production` in `.env.test`.
