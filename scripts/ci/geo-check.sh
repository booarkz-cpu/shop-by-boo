#!/usr/bin/env bash
# v28.95.0 (stage 20, N7): the Russian geo lists checked for real — the latest release of
# runetfreedom/russia-v2ray-rules-dat is looked up the way the shop does (SHA-256 published by GitHub), the very script of
# rw_steps.GEO puts the files in place, and Xray of the pinned node image loads a config that uses
# ext:ru-geosite.dat:ru-blocked and ext:ru-geoip.dat:ru-blocked with the files mounted the way node_compose mounts them.
# A wrong SHA-256 leaves the files as they were; «remove» and «undo» work. Needs root, Docker, python3, network.
set -euo pipefail
cd "$(dirname "$0")/../.."
dir=$(mktemp -d); trap 'rm -rf "$dir"; rm -rf /opt/remnanode/geo' EXIT
PYTHONPATH=backend APP_ENV=test MEDIA_DIR=/tmp/media BACKUP_DIR=/tmp/backups python3 - "$dir" <<'PY'
import asyncio, json, sys
from app import rw_plan, rw_releases, rw_steps
version, files = asyncio.run(rw_releases.geo_lists())
open(f"{sys.argv[1]}/geo.sh", "w").write(rw_steps.GEO)
json.dump({"version": version, "files": files, "image": rw_plan.IMAGES["node"], "dir": rw_plan.GEO_DIR}, open(f"{sys.argv[1]}/release.json", "w"))
PY
read -r version image geodir u1 s1 u2 s2 < <(python3 -c "
import json,sys; r=json.load(open('$dir/release.json')); f=r['files']
print(r['version'], r['image'], r['dir'], f['geoip']['url'], f['geoip']['sha256'], f['geosite']['url'], f['geosite']['sha256'])")
fail() { echo "FAIL: $*"; exit 1; }
echo "lists $version"
out=$(bash "$dir/geo.sh" install "$u1" "$s1" "$u2" "$s2") || fail "install: $out"
echo "ok: $out"
cat > "$dir/config.json" <<JSON
{"log": {"loglevel": "warning"},
 "outbounds": [{"protocol": "freedom", "tag": "direct"}, {"protocol": "blackhole", "tag": "block"}],
 "routing": {"rules": [{"type": "field", "domain": ["ext:ru-geosite.dat:ru-blocked"], "outboundTag": "block"},
                       {"type": "field", "ip": ["ext:ru-geoip.dat:ru-blocked"], "outboundTag": "block"}]}}
JSON
docker pull -q "$image" >/dev/null
docker run --rm --entrypoint /usr/local/bin/xray -v /opt/remnanode/geo/ru-geoip.dat:"$geodir/ru-geoip.dat":ro \
  -v /opt/remnanode/geo/ru-geosite.dat:"$geodir/ru-geosite.dat":ro -v "$dir/config.json":/tmp/config.json:ro "$image" \
  run -test -c /tmp/config.json || fail "Xray of the node image does not load the lists"
echo "ok: Xray of the node image loads ext:ru-geosite.dat:ru-blocked and ext:ru-geoip.dat:ru-blocked"
before=$(sha256sum /opt/remnanode/geo/ru-geosite.dat)
bash "$dir/geo.sh" install "$u1" "$s1" "$u2" "$(printf '0%.0s' $(seq 64))" >/dev/null 2>&1 && fail "a wrong SHA-256 was accepted" || true
[ "$(sha256sum /opt/remnanode/geo/ru-geosite.dat)" = "$before" ] || fail "a wrong SHA-256 changed the files"
echo "ok: a wrong SHA-256 changes nothing"
bash "$dir/geo.sh" install "https://example.com/geoip.dat" "$s1" "$u2" "$s2" >/dev/null 2>&1 && fail "another site was accepted" || echo "ok: only the release of the source"
bash "$dir/geo.sh" remove | grep -qx removed || fail "remove"
[ ! -e /opt/remnanode/geo/ru-geosite.dat ] || fail "remove left the file"
bash "$dir/geo.sh" undo; [ -e /opt/remnanode/geo/ru-geosite.dat ] || fail "undo did not bring the file back"
echo "ok: remove and undo"
