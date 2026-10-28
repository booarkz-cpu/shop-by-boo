# What is new in v28.42.0

- «География клиентов» (Monitoring) has a vector map of countries above the list. A country's colour reflects how many customers it had in the selected period (a day, 7 or 30 days). Hovering a country shows its name and the number.
- The outlines are Natural Earth 1:110m Admin 0 Countries, which is public domain. The map has 174 countries in an equirectangular projection, without Antarctica, and takes 118 KB. It is bundled into the admin, so it makes no calls to outside services. To rebuild the paths, run `scripts/geo/natural-earth-to-svg.py`.
- The mobile admins show a «Страны за 7 дней» row in the sessions card.
