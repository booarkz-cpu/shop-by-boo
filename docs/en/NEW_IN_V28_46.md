# What is new in v28.46.0

- **CloudPayments refunds through the API.**
  - The shop finds the transaction by order and calls `/payments/refund`.
  - `X-Request-ID` makes a repeat safe.
  - The refund status is read back from CloudPayments.
- **CloudPayments auto-renew.**
  - The card token from the «Pay» notification is saved, encrypted, when the customer has auto-renew on. A working YooKassa card stays first.
  - The auto-renew pass charges the card through `/payments/tokens/charge`.
  - The rule is the same as for YooKassa: three declines turn auto-renew off.
  - Recurring payments must be enabled in the CloudPayments contract.
- **Not included.** Refunds through the API for the other extra gateways, and auto-renew through Cashera and Lava subscriptions.
