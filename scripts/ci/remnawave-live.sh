#!/usr/bin/env bash
# Start the newest Remnawave panel (official compose and .env.sample), register an admin, create an API token and
# run the shop's live contract tests against it. Used by the «Remnawave live contract» CI job; secrets are random.
set -Eeuo pipefail
WORK="${RUNNER_TEMP:-/tmp}/remnawave"
mkdir -p "$WORK" && cd "$WORK"
REF="${REMNAWAVE_REF:-main}"
curl -fsSL -o docker-compose.yml "https://raw.githubusercontent.com/remnawave/backend/refs/heads/$REF/docker-compose-prod.yml"
curl -fsSL -o .env "https://raw.githubusercontent.com/remnawave/backend/refs/heads/$REF/.env.sample"
for key in JWT_AUTH_SECRET JWT_API_TOKENS_SECRET APP_SECRET METRICS_PASS WEBHOOK_SECRET_HEADER; do
  sed -i "s/^$key=.*/$key=$(openssl rand -hex 32)/" .env
done
sed -i "s/^FRONT_END_DOMAIN=.*/FRONT_END_DOMAIN=localhost/; s|^SUB_PUBLIC_DOMAIN=.*|SUB_PUBLIC_DOMAIN=localhost/api/sub|" .env
docker compose up -d
URL=http://127.0.0.1:3000
PROXY=(-H "X-Forwarded-Proto: https" -H "X-Forwarded-For: 127.0.0.1" -H "Content-Type: application/json")
for _ in $(seq 1 90); do
  [[ "$(curl -s -o /dev/null -w '%{http_code}' "${PROXY[@]}" "$URL/api/auth/status")" == 200 ]] && break
  sleep 3
done
password="Ci$(openssl rand -hex 16)Aa1"
jwt=$(curl -fsS "${PROXY[@]}" -X POST "$URL/api/auth/register" -d "{\"username\":\"ciadmin\",\"password\":\"$password\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["response"]["accessToken"])')
token=$(curl -fsS "${PROXY[@]}" -H "Authorization: Bearer $jwt" -H "X-Remnawave-Client-Type: browser" -X POST "$URL/api/tokens" \
  -d '{"name":"corgi-ci","expiresInDays":1}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["response"]["token"])')
echo "::add-mask::$token"
version=$(docker compose exec -T remnawave sh -c 'cat package.json 2>/dev/null' | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version","?"))' 2>/dev/null || echo "?")
echo "Remnawave panel $version" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
cd "${GITHUB_WORKSPACE:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel)}"
REMNAWAVE_LIVE_URL="$URL" REMNAWAVE_LIVE_TOKEN="$token" REMNAWAVE_LIVE_VERSION="$version" \
  python -m pytest -q -rfE tests/live/test_remnawave_live.py -p no:cacheprovider
