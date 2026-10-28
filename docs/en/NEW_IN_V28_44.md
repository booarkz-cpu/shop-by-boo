# What is new in v28.44.0

- **Tribute** (`backend/app/tribute.py`) tops up the wallet through a donation in Telegram. Tribute does not take order payments, so it stays out of the gateway queue.
- **Setup.** The owner sets `TRIBUTE_DONATE_LINK` and `TRIBUTE_API_KEY`. The cabinet and Mini App wallet then show «Пополнить донатом в Telegram».
- **Crediting.** The notification arrives at `https://<API_DOMAIN>/api/webhooks/tribute` and is signed in `trbt-signature` (HMAC-SHA256 of the body with the API key). The shop credits the customer whose Telegram account matches `telegram_user_id`.
  - Only `new_donation` and `recurrent_donation` in the shop's currency are credited, each once.
  - Donations from unknown Telegram accounts are logged and not credited.
- **Settings registry.** 226 fields, 134 of them live.
