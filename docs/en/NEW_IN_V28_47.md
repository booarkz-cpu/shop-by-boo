# What is new in v28.47.0

The shop migration head is now `0082_status_subscribers`.

## Status page
- The public page is at `https://<API_DOMAIN>/status`. It shows regions by server (no addresses), payments, components and «service» incidents.
- An outage opens automatically when every server of a country stays down past a set time. It closes when a server is back.
- Subscribers get outage and recovery news in Telegram and as push. They subscribe in the cabinet, in the Mini App or with the bot `/status` command.

## Prices by country
- A region is a list of countries with a markup or discount, or exact plan prices, and gateways placed first in the queue.
- The country comes from `CF-IPCountry` or the client address. The shop's own server addresses are skipped.
- The plans list and checkout use the same price.
