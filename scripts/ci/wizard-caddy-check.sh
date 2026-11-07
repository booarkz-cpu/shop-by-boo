#!/usr/bin/env bash
# v28.97.0 (stage 20, N7): every Caddyfile the Remnawave wizard writes is validated by Caddy of the pinned image —
# open, secret-link, TinyAuth and shop-gate panels, a separate subscription page, and a former panel domain kept
# after «Сменить домен панели» (subscriptions and the shop's API stay, the rest is redirected). Needs Docker.
set -euo pipefail
cd "$(dirname "$0")/../.."
dir=$(mktemp -d); trap 'rm -rf "$dir"' EXIT
image=$(PYTHONPATH=backend APP_ENV=test MEDIA_DIR=/tmp/media BACKUP_DIR=/tmp/backups python3 - "$dir" <<'PY'
import sys
from app import rw_plan as p
cases = {
    "open": p.caddyfile({"panel.example.com": 3000, "sub.example.com": 3010}, "acme", "owner@example.com"),
    "cookie": p.caddyfile({"panel.example.com": 3000}, "internal", None, protect={"panel.example.com": ("corgi_k", "v" * 24)}),
    "tinyauth": p.caddyfile({"panel.example.com": 3000, "auth.example.com": p.TINYAUTH_PORT}, "acme", "owner@example.com",
                            guard={"panel.example.com": p.TINYAUTH_PORT}),
    "gate": p.caddyfile({"panel.example.com": 3000}, "acme", "owner@example.com", gate={"panel.example.com": "https://shop.example.com"}),
    "moved": p.caddyfile({"new-panel.example.com": 3000}, "acme", "owner@example.com",
                         moved={"panel.example.com": "new-panel.example.com", "older.example.com": "new-panel.example.com"}),
    "moved-cookie": p.caddyfile({"new-panel.example.com": 3000}, "internal", None, protect={"new-panel.example.com": ("corgi_k", "v" * 24)},
                                moved={"panel.example.com": "new-panel.example.com"}),
}
for name, text in cases.items():
    open(f"{sys.argv[1]}/{name}.Caddyfile", "w").write(text)
print(p.IMAGES["caddy"])
PY
)
docker pull -q "$image" >/dev/null
for f in "$dir"/*.Caddyfile; do
  docker run --rm -v "$f:/etc/caddy/Caddyfile:ro" --entrypoint caddy "$image" validate --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null 2>"$dir/err" \
    || { echo "FAIL: $(basename "$f")"; cat "$dir/err"; exit 1; }
  echo "ok: $(basename "$f" .Caddyfile)"
done
