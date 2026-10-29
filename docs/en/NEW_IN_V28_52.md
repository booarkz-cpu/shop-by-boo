# What is new in v28.52.0

- **Support ratings and NPS** (`feedback.py`, migration `0086_feedback`):
  - after an operator answers, the customer rates the answer 1–5 in Telegram or the cabinet, and low scores reach the owner at once;
  - a quarterly NPS question (0–10) goes to paying customers;
  - the admin shows ratings per operator, NPS by month and comments.
- **Weekly digest** (`weekly_digest.py`). One Telegram message on the chosen day: revenue against the previous week, new and lost customers, gateways and nodes, ratings, and one piece of advice.
- **Cohorts** (`cohorts.py`). Retention after 1, 3, 6 and 12 months by month of the first payment, revenue per cohort, an optional split by acquisition source.
