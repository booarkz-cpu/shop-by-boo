#!/usr/bin/env python3
# usage: python3 scripts/geo/natural-earth-to-svg.py ne_110m_admin_0_countries.geojson admin/src/worldMap.json
"""Natural Earth 1:110m countries (public domain) -> compact SVG paths keyed by ISO 3166-1 alpha-2, equirectangular."""
import json, sys
src, out = sys.argv[1], sys.argv[2]
W, H = 1000.0, 470.0          # lon -180..180, lat 83.7..-60 (no Antarctica)
LAT_TOP, LAT_BOTTOM = 83.7, -60.0
def xy(lon, lat):
    return round((lon + 180) / 360 * W, 1), round((LAT_TOP - lat) / (LAT_TOP - LAT_BOTTOM) * H, 1)
def ring(r):
    pts = [xy(*p[:2]) for p in r]
    s, last = [], None
    for p in pts:
        if p != last: s.append(p); last = p
    if len(s) < 3: return ""
    return "M" + "L".join(f"{x:g} {y:g}" for x, y in s) + "Z"
data = json.load(open(src))
res = {}
for f in data["features"]:
    p = f["properties"]
    iso = next((p.get(k) for k in ("ISO_A2_EH", "ISO_A2", "WB_A2") if p.get(k) and p.get(k) != "-99"), None)
    if not iso or iso == "AQ": continue
    g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    d = "".join(ring(r) for poly in polys for r in poly)
    if d:
        res[iso] = {"n": p.get("NAME") or p.get("ADMIN"), "d": (res.get(iso, {}).get("d", "") + d)}
json.dump({"w": W, "h": H, "source": "Natural Earth 1:110m Admin 0 Countries (public domain)", "countries": res},
          open(out, "w"), ensure_ascii=False, separators=(",", ":"))
print(len(res), "countries")
