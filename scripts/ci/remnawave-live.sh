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
# v28.65.0 (stage 9): the node and the subscription page of the latest release, started the way their official
# docker-compose-prod.yml files run them (node: host network, NODE_PORT, SECRET_KEY from the panel's keygen;
# subscription page: on remnawave-network, REMNAWAVE_PANEL_URL + REMNAWAVE_API_TOKEN).
secret=$(curl -fsS "${PROXY[@]}" -H "Authorization: Bearer $token" "$URL/api/keygen" | python3 -c 'import json,sys; print(json.load(sys.stdin)["response"]["pubKey"])')
echo "::add-mask::$secret"
docker run -d -q --name remnanode --network host --cap-add NET_ADMIN -e NODE_PORT=2222 -e SECRET_KEY="$secret" remnawave/node:latest >/dev/null
gateway=$(docker network inspect remnawave-network -f '{{(index .IPAM.Config 0).Gateway}}')
docker run -d -q --name remnawave-subscription-page --network remnawave-network -p 127.0.0.1:3010:3010 \
  -e APP_PORT=3010 -e REMNAWAVE_PANEL_URL=http://remnawave:3000 -e REMNAWAVE_API_TOKEN="$token" \
  -e INTERNAL_JWT_SECRET="$(openssl rand -hex 32)" -e MARZBAN_LEGACY_LINK_ENABLED=false \
  -e MARZBAN_LEGACY_DROP_REVOKED_SUBSCRIPTIONS=false remnawave/subscription-page:latest >/dev/null
for _ in $(seq 1 40); do curl -s -o /dev/null -H "X-Forwarded-For: 127.0.0.1" -H "X-Forwarded-Proto: https" "http://127.0.0.1:3010/" && break; sleep 3; done
node_version=$(docker inspect remnawave/node:latest -f '{{index .Config.Labels "org.opencontainers.image.version"}}' 2>/dev/null || echo "?")
subpage_version=$(docker inspect remnawave/subscription-page:latest -f '{{index .Config.Labels "org.opencontainers.image.version"}}' 2>/dev/null || echo "?")
echo "Remnawave node ${node_version:-?}, subscription page ${subpage_version:-?}" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
version=$(docker compose exec -T remnawave sh -c 'cat package.json 2>/dev/null' | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version","?"))' 2>/dev/null || echo "?")
echo "Remnawave panel $version" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
cd "${GITHUB_WORKSPACE:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel)}"
set +e
REMNAWAVE_LIVE_URL="$URL" REMNAWAVE_LIVE_TOKEN="$token" REMNAWAVE_LIVE_VERSION="$version" \
  REMNAWAVE_LIVE_NODE_ADDRESS="$gateway" REMNAWAVE_LIVE_SUBPAGE_URL=http://127.0.0.1:3010 \
  python -m pytest -q -rfE tests/live/test_remnawave_live.py -p no:cacheprovider
status=$?
# Logs of the two extra containers help when a mode check fails.
[[ $status -eq 0 ]] || { docker logs --tail 40 remnanode 2>&1 | sed 's/^/node: /'; docker logs --tail 40 remnawave-subscription-page 2>&1 | sed 's/^/subpage: /'; }
exit $status
