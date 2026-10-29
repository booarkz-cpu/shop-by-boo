# What is new in v28.54.0

- **Ad / children's filter** (`dns_filter.py`, migration `0088_filter_and_regions`):
  - customers switch it in the cabinet, the bot (`/filter`) or the apps, and a family owner sets it for a member;
  - the shop moves the panel user to a squad whose profile blocks ads (and adult sites), and puts it back after renewals.
- **Customer regions** (`geoip.py`). With a free MaxMind key the shop downloads GeoLite2-City weekly and shows regions inside countries.
- **Availability from Russia** (`ripe_atlas.py`). One-off RIPE Atlas `sslcert` measurements from Russian probes feed the block monitor as a virtual probe.
