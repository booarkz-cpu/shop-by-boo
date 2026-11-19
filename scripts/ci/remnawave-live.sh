#!/usr/bin/env bash
# Start the exact stable Remnawave releases approved by the compatibility matrix, register an admin, create an API
# token and run the shop's live contract tests. Used by «Remnawave live contract» CI; secrets are random.
set -Eeuo pipefail
WORK="${RUNNER_TEMP:-/tmp}/remnawave"
mkdir -p "$WORK" && cd "$WORK"
PANEL_VERSION="3.4.11"
PANEL_COMMIT="6853666801d6d1925b6aec55824106100485777a"
PANEL_IMAGE="remnawave/backend:3.4.11@sha256:a5b9f81fe2cfacec1c41bd2bb43fa1a5980228b81aa2e744be4adffa3a00135b"
NODE_VERSION="3.4.6"
NODE_COMMIT="52d0f1c00c23bf99912687cb3b75faffb2d3bffb"
NODE_IMAGE="remnawave/node:3.4.6@sha256:3d5fde656a36920f53c5c080f2dc821df8318f453803b07c4e5242752a549d69"
SUBPAGE_VERSION="8.0.1"
SUBPAGE_COMMIT="9045728e6e197a2581c6da40f4f92b170a8bad53"
SUBPAGE_IMAGE="remnawave/subscription-page:8.0.1@sha256:ba8445b1e0d1c170cf314686ef638b73cabf42a0c6217d027e6cb958ca161ca6"

verify_image_digest() {
  local image="$1"\n  local expected="${image##*@}"
  docker image inspect "$image" --format '{{range .RepoDigests}}{{println .}}{{end}}' | grep -Fq "@$expected"
}

curl -fsSL -o docker-compose.yml "https://raw.githubusercontent.com/remnawave/backend/$PANEL_VERSION/docker-compose-prod.yml"
curl -fsSL -o .env "https://raw.githubusercontent.com/remnawave/backend/$PANEL_VERSION/.env.sample"
grep -Fq 'image: remnawave/backend:3' docker-compose.yml
sed -i "s|image: remnawave/backend:3$|image: $PANEL_IMAGE|" docker-compose.yml
grep -Fq "image: $PANEL_IMAGE" docker-compose.yml
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
# v28.70.0: only the panel, for the SelfSteal node job (the wizard installs the node over SSH).
if [[ -n "${PANEL_ONLY_ENV:-}" ]]; then
  printf 'REMNAWAVE_URL=%s\nREMNAWAVE_TOKEN=%s\n' "$URL" "$token" > "$PANEL_ONLY_ENV"
  exit 0
fi
# v28.65.0 (stage 9): the pinned node and subscription-page releases, started the way their official
# docker-compose-prod.yml files run them (node: host network, NODE_PORT, SECRET_KEY from the panel's keygen;
# subscription page: on remnawave-network, REMNAWAVE_PANEL_URL + REMNAWAVE_API_TOKEN).
secret=$(curl -fsS "${PROXY[@]}" -H "Authorization: Bearer $token" "$URL/api/keygen" | python3 -c 'import json,sys; print(json.load(sys.stdin)["response"]["pubKey"])')
echo "::add-mask::$secret"
docker run -d -q --name remnanode --network host --cap-add NET_ADMIN -e NODE_PORT=2222 -e SECRET_KEY="$secret" "$NODE_IMAGE" >/dev/null
gateway=$(docker network inspect remnawave-network -f '{{(index .IPAM.Config 0).Gateway}}')
docker run -d -q --name remnawave-subscription-page --network remnawave-network -p 127.0.0.1:3010:3010 \
  -e APP_PORT=3010 -e REMNAWAVE_PANEL_URL=http://remnawave:3000 -e REMNAWAVE_API_TOKEN="$token" \
  -e INTERNAL_JWT_SECRET="$(openssl rand -hex 32)" -e MARZBAN_LEGACY_LINK_ENABLED=false \
  -e MARZBAN_LEGACY_DROP_REVOKED_SUBSCRIPTIONS=false "$SUBPAGE_IMAGE" >/dev/null
for _ in $(seq 1 40); do curl -s -o /dev/null -H "X-Forwarded-For: 127.0.0.1" -H "X-Forwarded-Proto: https" "http://127.0.0.1:3010/" && break; sleep 3; done
version=$(docker compose exec -T remnawave sh -c 'cat package.json 2>/dev/null' | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version","?"))' 2>/dev/null || echo "?")
[[ "$version" == "$PANEL_VERSION" ]] || { echo "Panel version mismatch: expected $PANEL_VERSION, got $version" >&2; exit 1; }
verify_image_digest "$PANEL_IMAGE" || { echo "Panel image digest mismatch" >&2; exit 1; }
verify_image_digest "$NODE_IMAGE" || { echo "Node image digest mismatch" >&2; exit 1; }
verify_image_digest "$SUBPAGE_IMAGE" || { echo "Subscription page image digest mismatch" >&2; exit 1; }
{
  echo "Remnawave panel $version ($PANEL_COMMIT)"
  echo "Remnawave node $NODE_VERSION ($NODE_COMMIT), subscription page $SUBPAGE_VERSION ($SUBPAGE_COMMIT); image digests verified"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
cd "${GITHUB_WORKSPACE:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel)}"
set +e
REMNAWAVE_LIVE_URL="$URL" REMNAWAVE_LIVE_TOKEN="$token" REMNAWAVE_LIVE_VERSION="$version" \
  REMNAWAVE_LIVE_NODE_ADDRESS="$gateway" REMNAWAVE_LIVE_SUBPAGE_URL=http://127.0.0.1:3010 \
  python -m pytest -q -rfE tests/live/test_remnawave_live.py -p no:cacheprovider
status=$?
# Logs of the two extra containers help when a mode check fails.
[[ $status -eq 0 ]] || { docker logs --tail 40 remnanode 2>&1 | sed 's/^/node: /'; docker logs --tail 40 remnawave-subscription-page 2>&1 | sed 's/^/subpage: /'; }
exit $status
