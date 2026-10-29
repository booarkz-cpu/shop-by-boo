# What is new in v28.45.0

- **Gateway package** `backend/app/gateways/`.
  - Each extra gateway now has its own module, plus a `GATEWAYS` table: keys, notification address, signature, re-check, refunds, recurring.
  - The queue, recovery and alert maps are built from this table.
  - `payments_extra.py` is kept as a compatibility module.
- **Gateway health** (`gateway_ops.py`, admin «Платёжные агенты → Здоровье касс», a mobile admin card).
  - Every 6 hours the shop makes one authenticated call to each configured gateway; no money moves.
  - After 2 failures in a row the gateway leaves the queue for 6 hours and the operator is alerted. It comes back on its own once the probe passes.
  - A report shows paid orders that came without a notification and orders stuck in pending.
  - Optional «best gateway first»: once a day the gateways are reordered by conversion.
- **Payments acceptance workflow.**
  - It runs for every gateway whose keys are in repository secrets.
  - For each one it runs the probe, creates a small payment page and reads the payment back as unpaid.
  - No money moves. It runs weekly and on demand.
