#!/usr/bin/env bash
set -Eeuo pipefail
command -v curl >/dev/null 2>&1 || { echo 'FAIL: в контейнере backend нет curl' >&2; exit 2; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
: "${STAGING_PUBLIC_BASE_URL:?Укажите публичный HTTPS URL staging}"
: "${STAGING_REMNAWAVE_URL:?Укажите HTTPS URL staging Remnawave}"
: "${STAGING_REMNAWAVE_TOKEN:?Не задан токен staging Remnawave}"
: "${STAGING_PLAN_ID:?Не задан ID тестового тарифа}"
: "${STAGING_RUNNER_TOKEN:?Не задан внутренний токен runner}"
STAGING_TIMEOUT_SECONDS="${STAGING_TIMEOUT_SECONDS:-1800}"
STAGING_PROVIDERS="${STAGING_PROVIDERS:-yookassa,platega,rollypay}"

case "$STAGING_PUBLIC_BASE_URL" in https://*) ;; *) echo 'FAIL: публичный URL должен использовать HTTPS' >&2; exit 2;; esac
case "$STAGING_REMNAWAVE_URL" in https://*) ;; *) echo 'FAIL: URL Remnawave должен использовать HTTPS' >&2; exit 2;; esac

health=$(curl -fsS --location --max-redirs 0 --proto "=https" --proto-redir "=https" --retry 10 --retry-delay 2 --max-time 20 "$STAGING_PUBLIC_BASE_URL/health")
python - "$health" <<'PY'
import json,sys
x=json.loads(sys.argv[1])
for k in ('database','redis'):
    if not x.get(k): raise SystemExit(f'FAIL: {k} недоступен')
if not x.get('ok'): raise SystemExit('FAIL: backend health degraded')
print('[PASS] PostgreSQL + Redis + backend health')
PY

if curl -fsS --max-redirs 0 --proto "=https" --proto-redir "=https" --retry 5 --retry-delay 2 --max-time 20 \
  -H "Authorization: Bearer $STAGING_REMNAWAVE_TOKEN" \
  "$STAGING_REMNAWAVE_URL" >/dev/null 2>&1; then
  echo '[PASS] Remnawave endpoint доступен'
else
  echo '[WARN] Корневой endpoint Remnawave не подтвердил доступ; продолжение через платёжный E2E.'
fi

post_local() {
  curl -sS --max-redirs 0 --proto "=http" --retry 2 --retry-delay 1 --max-time 40 \
    -X POST "http://127.0.0.1:8000$1" \
    -H "X-Staging-Runner-Token: $STAGING_RUNNER_TOKEN" \
    -H "Content-Type: application/json" \
    --data-binary "$2" || true
}

json_state() {
  python - "$1" "$2" <<'PY'
import json,sys
raw, kind = sys.argv[1], sys.argv[2]
try:
    data = json.loads(raw)
except Exception:
    print("wait")
    raise SystemExit(0)
if kind == "paid":
    print("paid" if data.get("paid") is True else "wait")
elif kind == "refund":
    print("done" if data.get("done") is True else "wait")
elif kind == "remnawave":
    print("ok" if data.get("ok") is True else "fail")
else:
    print("wait")
PY
}

now_ts=$(date +%s)
pay_deadline=$(( now_ts + STAGING_TIMEOUT_SECONDS - 120 ))
refund_deadline=$(( now_ts + STAGING_TIMEOUT_SECONDS - 20 ))
if (( pay_deadline < now_ts + 30 )); then
  echo 'FAIL: STAGING_TIMEOUT_SECONDS слишком мал для оплаты и возврата' >&2
  exit 2
fi

meta_dir=$(mktemp -d)
trap 'rm -rf "$meta_dir"' EXIT

IFS=',' read -r -a providers <<< "$STAGING_PROVIDERS"
for provider in "${providers[@]}"; do
  [[ -n "$provider" ]] || continue
  case "$provider" in yookassa|platega|rollypay) ;; *) echo "FAIL: неизвестный провайдер $provider"; exit 2;; esac
  echo "[RUN] $provider: создание sandbox-платежа через приложение"
  body=$(post_local "/api/internal/staging-e2e/payment" "{\"plan_id\":$STAGING_PLAN_ID,\"provider\":\"$provider\"}")
  python - "$provider" "$body" "$meta_dir/$provider.json" <<'PY'
import json,sys
from pathlib import Path
provider, raw, dest = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = json.loads(raw)
except Exception as exc:
    raise SystemExit(f'FAIL {provider}: ответ создания платежа не JSON: {exc}')
if not d.get('id') or not str(d.get('url') or '').startswith('https://') or not d.get('order_id'):
    raise SystemExit(f'FAIL {provider}: приложение не вернуло id и https checkout')
Path(dest).write_text(json.dumps({"id": d["id"], "order_id": d["order_id"], "amount": d.get("amount")}), encoding="utf-8")
print(f'[PASS] {provider}: платёж создан, id={d["id"]}')
print(f'[CHECKOUT] {provider} {d["url"]}')
print('[ACTION] Откройте строку CHECKOUT в журнале панели и завершите sandbox-оплату.')
PY
  id=$(python -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["id"])' "$meta_dir/$provider.json")
  order_id=$(python -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["order_id"])' "$meta_dir/$provider.json")
  amount=$(python -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["amount"])' "$meta_dir/$provider.json")
  verify_payload=$(python -c 'import json,sys; print(json.dumps({"provider":sys.argv[1],"payment_id":sys.argv[2],"order_id":sys.argv[3],"amount":sys.argv[4]}))' "$provider" "$id" "$order_id" "$amount")
  echo "[RUN] $provider: ожидание оплаты, повторного чтения и возврата"
  echo '[GATE] Пока нет отдельной итоговой строки, статус остаётся awaiting_checkout и шлюз закрыт.'
  paid=0
  while (( $(date +%s) < pay_deadline )); do
    state=$(json_state "$(post_local "/api/internal/staging-e2e/verify" "$verify_payload")" paid)
    if [[ "$state" == "paid" ]]; then paid=1; break; fi
    sleep 5
  done
  if (( paid != 1 )); then
    echo "FAIL: $provider не подтверждён до таймаута"
    exit 1
  fi
  echo "[PASS] $provider: сумма, валюта RUB и номер заказа совпали"
  state=$(json_state "$(post_local "/api/internal/staging-e2e/verify" "$verify_payload")" paid)
  if [[ "$state" != "paid" ]]; then
    echo "FAIL: $provider повторное чтение не подтвердило оплату"
    exit 1
  fi
  echo "[PASS] $provider: повторное чтение без второй выдачи"
  refund_payload=$(python -c 'import json,sys; print(json.dumps({"provider":sys.argv[1],"payment_id":sys.argv[2],"amount":sys.argv[3]}))' "$provider" "$id" "$amount")
  refund_raw=$(post_local "/api/internal/staging-e2e/refund" "$refund_payload")
  python - "$provider" "$refund_raw" "$meta_dir/$provider-refund.json" <<'PY'
import json,sys
from pathlib import Path
provider, raw, dest = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = json.loads(raw)
except Exception as exc:
    raise SystemExit(f'FAIL {provider}: ответ возврата не JSON: {exc}')
if not d.get("id"):
    raise SystemExit(f'FAIL {provider}: возврат не вернул id')
Path(dest).write_text(json.dumps({"id": d["id"], "done": bool(d.get("done"))}), encoding="utf-8")
PY
  refund_id=$(python -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["id"])' "$meta_dir/$provider-refund.json")
  refund_done=$(python -c 'import json,sys; print("done" if json.load(open(sys.argv[1],encoding="utf-8")).get("done") else "wait")' "$meta_dir/$provider-refund.json")
  status_payload=$(python -c 'import json,sys; print(json.dumps({"provider":sys.argv[1],"refund_id":sys.argv[2]}))' "$provider" "$refund_id")
  while [[ "$refund_done" != "done" ]] && (( $(date +%s) < refund_deadline )); do
    refund_done=$(json_state "$(post_local "/api/internal/staging-e2e/refund-status" "$status_payload")" refund)
    if [[ "$refund_done" == "done" ]]; then break; fi
    sleep 5
  done
  if [[ "$refund_done" != "done" ]]; then
    echo "FAIL: $provider возврат не подтверждён"
    exit 1
  fi
  echo "[PASS] $provider: возврат подтверждён"
done

rw_state=$(json_state "$(post_local "/api/internal/staging-e2e/remnawave" '{}')" remnawave)
if [[ "$rw_state" != "ok" ]]; then
  echo 'FAIL: staging Remnawave не подтвердил токен'
  exit 1
fi
echo '[PASS] staging Remnawave принял токен'
echo '[INCOMPLETE] Проверены ответы провайдеров и возврат, но webhook, выдача VPN и повторная доставка не подтверждены.'
echo '[GATE] Production-платежи остаются закрытыми до полного сквозного E2E.'
