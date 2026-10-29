# What is new in v28.53.0

- **Speed test in the apps** (`speed_test.py`, migration `0087_speed_tests`):
  - the Android and iOS apps measure the response time and download 10 MB through the current connection;
  - results with the VPN on build a per-server speed map of 7 days, and slow servers are reported once a day;
  - no IP addresses are kept, and rows are kept for 30 days.
- **Node load forecast** (`node_forecast.py`). Daily peaks of users online give the growth per day and the days left to each node's limit; the owner is warned in advance.
