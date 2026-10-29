# What is new in v28.51.0

- **Loyalty levels** (`loyalty.py`, migration `0085_loyalty`):
  - Bronze, Silver and Gold by tenure or total paid (refunds excluded), editable, up to eight levels;
  - a level may give wallet cashback, a discount on purchases and auto-renewals, and bonus days once on reaching it;
  - cashback counts orders paid after the levels were switched on, after a hold period, and is taken back on a refund;
  - the level discount does not stack with a promo code: the larger one wins;
  - customers see the level in the cabinet, the bot (`/level`) and the apps.
- **Freeze in the apps.** The Android and iOS apps can pause and resume the subscription.
