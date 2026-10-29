# What is new in v28.49.0

- **Payment antifraud** (`payment_fraud.py`):
  - rules for card testing, new accounts paying a large amount, many accounts on one address, and chargebacks;
  - a blocklist of addresses, e-mails, Telegram IDs and customer IDs;
  - wallet top-ups are now checked too;
  - every refusal is recorded, and the operator gets a Telegram card for reviews and refusals.
- **«Load live» workflow.** It runs k6 against the real API with read-only requests and a step-up profile. It runs only on demand.
- **Hot standby.** Every weekly drill now ends with a Telegram report, whether it passed or failed.
- **Not included: regions inside countries on the map.** The registry country data has no regions; that needs a GeoIP database.
