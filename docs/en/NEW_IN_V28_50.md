# What is new in v28.50.0

- **Subscription freeze** (`subscription_freeze.py`, migration `0084_subscription_freeze`):
  - a customer pauses a paid subscription instead of cancelling it, in the cabinet or with `/freeze` in the bot;
  - the panel user is switched off and the end date moves by the frozen days;
  - an early thaw takes back the unused days; a purchase, a gift or bonus days thaw the subscription first;
  - the owner sets the days per freeze and the days and freezes per year; the operator can thaw any subscription.
- **Renewal retries** (`dunning.py`):
  - declined renewals are retried on the owner's schedule, with a configurable grace period and failure limit;
  - the customer gets a message after every decline;
  - the renewal is paid from the wallet when the balance covers the plan;
  - while the rules are off, the previous behaviour stays.
